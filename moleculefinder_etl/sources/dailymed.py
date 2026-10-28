"""DailyMed SPL labels (US National Library of Medicine; the labels are public domain).

Growth plan run C1, "What's in it" (2026-10-22). A product page for a medicine, a cosmetic or a
household OTC product lists the molecules on its label. This module reads ONE label by its set
id and keeps only the structured facts the page uses:

* the label's ingredient list, each ingredient with its class (active or inactive), its name as
  the label prints it, its UNII code and the UNII of its active moiety (sertraline for
  "sertraline hydrochloride"), in label order;
* the OTC "Active ingredient" and "Purpose" sections as lines of text, so an active
  ingredient's purpose ("Pain reliever/fever reducer") can be read off the label itself;
* the label's title, labeler, document type, version and effective date, for the source line.

Nothing else: no warnings, no directions, no dosage, no images. Matching an ingredient to a
MoleculeFinder molecule is done elsewhere (``transform/products.py``) by UNII code only.

``parse`` is pure (bytes in, dict out) and is what the tests exercise. ``fetch`` is the one
network call; the products stage caches what it returns under ``data/raw_cache/dailymed``,
which travels with the snapshot like every other input (``moleculefinder_etl/inputs.py``).
"""
from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET

import requests

from ..config import USER_AGENT

log = logging.getLogger("mfetl")

SPL_URL = "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/{setid}.xml"
LABEL_PAGE = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}"
SETID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

_NS = "{urn:hl7-org:v3}"
UNII_SYSTEM = "2.16.840.1.113883.4.9"
ACTIVE_SECTION = "55106-9"          # OTC - ACTIVE INGREDIENT SECTION
PURPOSE_SECTION = "55105-1"         # OTC - PURPOSE SECTION
# Ingredient class codes. ACTIB/ACTIM/ACTIR are actives (basis of strength differs); IACT is an
# inactive ingredient, INGR a plain ingredient (cosmetic labels), COLR a colour additive. CNTM
# ("contains", e.g. an allergen statement) is not an ingredient of the product and is skipped.
_ACTIVE = {"ACTIB", "ACTIM", "ACTIR"}
_INACTIVE = {"IACT", "INGR", "COLR"}

_MIN_INTERVAL = 0.25                # seconds between requests: about 4 a second
_last = [0.0]
_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


class DailyMedError(RuntimeError):
    """DailyMed did not answer after retries. A failed run, not a silently missing label."""


def _tag(el: ET.Element) -> str:
    return el.tag.removeprefix(_NS)


_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"))


def _clean(text: str) -> str:
    """Whitespace collapsed and invisible characters (zero-width spaces, soft hyphens) removed;
    labels carry them, and "\u200bPurpose" must still read as the word Purpose."""
    return " ".join(text.translate(_INVISIBLE).split())


def _text(el: ET.Element | None) -> str:
    return _clean("".join(el.itertext())) if el is not None else ""


def _lines(text_el: ET.Element | None) -> tuple[list[str], list[list[str]]]:
    """A section's own <text> as lines (a paragraph, a list item or a <br/>-separated run each)
    and as table rows (each a list of cell texts). Nested sections are not read here."""
    lines: list[str] = []
    rows: list[list[str]] = []
    if text_el is None:
        return lines, rows
    buf: list[str] = []

    def flush() -> None:
        line = _clean("".join(buf))
        if line:
            lines.append(line)
        buf.clear()

    def walk(el: ET.Element) -> None:
        tag = _tag(el)
        if tag == "tr":
            flush()
            cells = [_text(c) for c in el if _tag(c) in ("td", "th")]
            cells = [c for c in cells if c]
            if cells:
                rows.append(cells)
                lines.append(" ".join(cells))
            return
        if tag == "br":
            flush()
            if el.tail:
                buf.append(el.tail)
            return
        if el.text:
            buf.append(el.text)
        for child in el:
            walk(child)
        if tag in ("paragraph", "item", "caption", "td", "th"):
            flush()
        if el.tail:
            buf.append(el.tail)

    for child in text_el:
        walk(child)
    flush()
    return lines, rows


def parse(xml: bytes, setid: str) -> dict:
    """The structured facts of one SPL document (see the module docstring)."""
    root = ET.fromstring(xml)
    doc_code = root.find(f"{_NS}code")
    version = root.find(f"{_NS}versionNumber")
    effective = root.find(f"{_NS}effectiveTime")
    labeler = root.find(f"{_NS}author/{_NS}assignedEntity/{_NS}representedOrganization/{_NS}name")

    products: list[str] = []
    ingredients: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for mp in root.iter(f"{_NS}manufacturedProduct"):
        name = mp.find(f"{_NS}name")
        if name is not None and _text(name) and _text(name) not in products:
            products.append(_text(name))
        for ing in list(mp.iter(f"{_NS}ingredient")) + list(mp.iter(f"{_NS}activeIngredient")) \
                + list(mp.iter(f"{_NS}inactiveIngredient")):
            tag = _tag(ing)
            cls = ing.get("classCode") or ("ACTIB" if tag == "activeIngredient" else
                                           "IACT" if tag == "inactiveIngredient" else "")
            if cls in _ACTIVE:
                role = "active"
            elif cls in _INACTIVE:
                role = "inactive"
            else:
                continue
            sub = None
            for name_ in ("ingredientSubstance", "activeIngredientSubstance", "inactiveIngredientSubstance"):
                sub = ing.find(f"{_NS}{name_}")
                if sub is not None:
                    break
            if sub is None:
                continue
            code = sub.find(f"{_NS}code")
            unii = code.get("code") if code is not None and code.get("codeSystem") == UNII_SYSTEM else None
            ing_name = _text(sub.find(f"{_NS}name"))
            moiety = []
            for am in sub.iter(f"{_NS}activeMoiety"):
                c = am.find(f"{_NS}code")
                if c is not None and c.get("codeSystem") == UNII_SYSTEM and c.get("code") and c.get("code") != unii \
                        and c.get("code") not in moiety:
                    moiety.append(c.get("code"))
            key = (role, unii or ing_name.upper())
            if key in seen:
                continue
            seen.add(key)
            ingredients.append({"role": role, "name": ing_name, "unii": unii, "moiety": moiety})

    active_lines: list[str] = []
    purpose_lines: list[str] = []
    rows: list[list[str]] = []
    for sec in root.iter(f"{_NS}section"):
        code = sec.find(f"{_NS}code")
        c = code.get("code") if code is not None else None
        if c not in (ACTIVE_SECTION, PURPOSE_SECTION):
            continue
        lines, r = _lines(sec.find(f"{_NS}text"))
        rows.extend(r)
        (active_lines if c == ACTIVE_SECTION else purpose_lines).extend(lines)

    return {
        "setid": setid,
        "title": _text(root.find(f"{_NS}title")),
        "doc_type": (doc_code.get("displayName") or "") if doc_code is not None else "",
        "version": int(version.get("value")) if version is not None and (version.get("value") or "").isdigit() else None,
        "effective": (effective.get("value") or "")[:8] if effective is not None else "",
        "labeler": _text(labeler),
        "products": products,
        "ingredients": ingredients,
        "active_lines": active_lines,
        "purpose_lines": purpose_lines,
        "purpose_rows": [r for r in rows if len(r) >= 2],
    }


# ── purposes ──────────────────────────────────────────────────────────────────
_HEADER = re.compile(r"^(purposes?|uses?|active ingredients?\b.*|drug facts.*)$", re.IGNORECASE)
_DOSE = re.compile(r"\d\s*(mg|mcg|g|%|ml)\b", re.IGNORECASE)


def clean_purpose(text: str) -> str | None:
    """A purpose as the label states it, tidied: bullets and trailing stops off, an all-capitals
    line in sentence case. None for a line that is a header, carries a strength (then it is an
    active-ingredient line, not a purpose) or is too long to be a purpose."""
    s = " ".join(text.split()).strip(" •*-–—·:;.,")
    if not s or _HEADER.match(s) or _DOSE.search(s) or len(s) > 60:
        return None
    if s.upper() == s and any(ch.isalpha() for ch in s):
        s = s[0] + s[1:].lower()
    s = s[0].upper() + s[1:]
    return re.sub(r"\s*[\u2014\u2013]\s*", ", ", s)


def _keys(name: str) -> list[str]:
    """How a label's own active-ingredient line names an ingredient: its full name, then its
    first word (``DEXTROMETHORPHAN HYDROBROMIDE`` is "Dextromethorphan HBr 15 mg" on the line).
    Within one label only: this pairs a label's two lists, it never matches a molecule."""
    full = " ".join(name.lower().split())
    first = re.sub(r"[^a-z]", "", full.split(" ")[0]) if full else ""
    return [k for k in dict.fromkeys([full, first]) if len(k) >= 4]


def purposes(spl: dict) -> dict[str, str]:
    """{active ingredient name: purpose} read off the label, deterministically:
    1. a table row whose first cell names the ingredient and whose last cell is a purpose;
    2. else, the active and purpose lines paired by position when the label lists as many of
       each (the common "Acetaminophen 325 mg / Pain reliever" layout);
    3. else, a label with exactly one distinct purpose gives it to every active.
    An active with none of these gets no purpose (the page then says "active ingredient")."""
    actives = [i["name"] for i in spl.get("ingredients", []) if i["role"] == "active"]
    out: dict[str, str] = {}
    for name in actives:
        for row in spl.get("purpose_rows", []):
            if any(k in row[0].lower() for k in _keys(name)):
                p = clean_purpose(row[-1])
                if p:
                    out[name] = p
                    break
    # Header lines and footnotes ("*nonsteroidal anti-inflammatory drug") are not ingredients.
    a_lines = [l for l in spl.get("active_lines", [])
               if not _HEADER.match(l.strip(" :")) and not l.lstrip().startswith(("*", "†"))]
    p_lines = [p for p in (clean_purpose(l) for l in spl.get("purpose_lines", [])) if p]
    if len(a_lines) == len(p_lines):
        for line, p in zip(a_lines, p_lines):
            for name in actives:
                if name not in out and any(k in line.lower() for k in _keys(name)):
                    out[name] = p
                    break
    distinct = list(dict.fromkeys(p_lines))
    if len(distinct) == 1:
        for name in actives:
            out.setdefault(name, distinct[0])
    return out


# ── strengths (SEO run 2, 2026-10-28) ─────────────────────────────────────────
# The strength an OTC label states for each active ingredient ("Ibuprofen 200 mg (NSAID)*"), read
# off the same active-ingredient lines and table rows ``purposes`` reads, never computed. The
# product comparison pages show it beside the active; a product page's active row carries it too.
_QTY = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:%|(?:mg|mcg|g|iu|units?)\b)", re.IGNORECASE)
_PER = re.compile(r"\((?:in|per) each ([^)]+)\)", re.IGNORECASE)


def strength_text(line: str) -> str | None:
    """The strength a line states, from its first quantity: "200 mg" from "Ibuprofen 200 mg
    (NSAID)*", "220 mg (naproxen 200 mg)" from Aleve's line, "0.24% (0.15% w/v fluoride ion)" from
    a toothpaste's. A parenthetical right after the quantity is kept only when it carries a
    quantity itself; "(NSAID)" is not a strength. None for a line with no quantity."""
    m = _QTY.search(line)
    if not m:
        return None
    text = m.group(0)
    rest = line[m.end():].lstrip()
    if rest.startswith("("):
        close = rest.find(")")
        if close > 0 and _QTY.search(rest[:close]):
            text += " " + rest[:close + 1]
    return " ".join(text.split())


def _active_lines(spl: dict) -> list[str]:
    """The label's active-ingredient lines less headers and footnotes, as ``purposes`` reads them."""
    return [l for l in spl.get("active_lines", [])
            if not _HEADER.match(l.strip(" :")) and not l.lstrip().startswith(("*", "†"))]


def strengths(spl: dict) -> dict[str, str]:
    """{active ingredient name: the strength its line states}, paired the way ``purposes`` pairs
    them: a table row's first cell, else an active-ingredient line, naming the ingredient by its
    full name or first word. An active whose line states no quantity gets none."""
    actives = [i["name"] for i in spl.get("ingredients", []) if i["role"] == "active"]
    lines = [row[0] for row in spl.get("purpose_rows", []) if row] + _active_lines(spl)
    out: dict[str, str] = {}
    for name in actives:
        for line in lines:
            if any(k in line.lower() for k in _keys(name)):
                text = strength_text(line)
                if text:
                    out[name] = text
                    break
    return out


def strength_per(spl: dict) -> str | None:
    """What the strengths are stated for, from the section header "(in each tablet)": "tablet",
    "caplet", "chewable tablet", "5 mL". None when the label gives no such header."""
    lines = spl.get("active_lines", []) + [r[0] for r in spl.get("purpose_rows", []) if r] + spl.get("purpose_lines", [])
    for line in lines:
        m = _PER.search(line)
        if m:
            return " ".join(m.group(1).split())
    return None


# ── network ───────────────────────────────────────────────────────────────────
def fetch(setid: str) -> dict | None:
    """One label, parsed. None when DailyMed has no such set id (404: the label was withdrawn or
    archived); the products gate then reports it. A transient failure is retried three times
    and then raises, so a weekly run fails loudly instead of dropping pages."""
    if not SETID_RE.match(setid):
        raise ValueError(f"not a DailyMed set id: {setid!r}")
    url = SPL_URL.format(setid=setid)
    err: Exception | None = None
    for attempt in range(3):
        wait = _MIN_INTERVAL - (time.monotonic() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()
        try:
            r = _session.get(url, timeout=60)
        except requests.RequestException as exc:
            err = exc
        else:
            if r.status_code == 404:
                return None
            if r.status_code == 200:
                return parse(r.content, setid)
            err = DailyMedError(f"HTTP {r.status_code}")
            if r.status_code not in (429, 500, 502, 503, 504):
                break
        log.warning("dailymed %s: %s; retrying", setid, err)
        time.sleep(5 * (attempt + 1))
    raise DailyMedError(f"dailymed label {setid}: {type(err).__name__}: {err}")
