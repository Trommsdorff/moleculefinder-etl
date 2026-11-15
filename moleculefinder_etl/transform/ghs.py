"""Parse a PubChem PUG-View 'GHS Classification' record.

Pulls the three things a hazard chip needs: the signal word (most severe wins),
the H-statement codes, and the GHS pictogram codes. Pictograms are not in the
text leaves — PubChem carries them as pictogram image URLs in `Markup` nodes
(e.g. ``.../images/ghs/GHS07.svg``), so we walk those separately.
"""
from __future__ import annotations
import functools
import re

import yaml

from ..config import SEEDS_DIR
from ..sources import registry
from .confidence import label_for
from .toxicity import _iter_information, _iter_strings

_SIGNAL = re.compile(r"\b(Danger|Warning)\b")
_HCODE = re.compile(r"\bH\d{3}\b")
_PICTO = re.compile(r"GHS0\d")


def _iter_markup_urls(node):
    """Yield every Markup URL in a PUG-View tree (where pictogram icons live)."""
    if isinstance(node, dict):
        for m in node.get("Markup", []) or []:
            if isinstance(m, dict) and m.get("URL"):
                yield m["URL"]
        for v in node.values():
            yield from _iter_markup_urls(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_markup_urls(v)


def parse_ghs(pug_view: dict | None, *, withheld: list | None = None) -> dict | None:
    """The hazard chip's signal word, H codes and pictograms, plus `sources` (registry keys).

    THE SOURCE-LICENCE RULE (2026-10-23): only Information items whose reference is a
    registered source that may be displayed contribute (`registry.may_display`); an
    unregistered source counts as not displayable. When `withheld` is a list, the name of each
    source whose items were left out is appended once, for the run log."""
    if not pug_view:
        return None
    rec = pug_view.get("Record", pug_view)
    names = {r.get("ReferenceNumber"): r.get("SourceName") for r in rec.get("Reference", []) or []}
    signals, hcodes, pictos, used, refused = set(), set(), set(), set(), set()
    for info in _iter_information(rec):
        source_name = names.get(info.get("ReferenceNumber"))
        key = registry.pugview_key(source_name)
        s_, h_, p_ = set(), set(), set()
        for text in _iter_strings(info):
            s_.update(_SIGNAL.findall(text))
            h_.update(_HCODE.findall(text))
        for url in _iter_markup_urls(info):
            p_.update(_PICTO.findall(url))
        if not (s_ or h_ or p_):
            continue
        if not registry.may_display(key):
            refused.add(source_name or "(no source named)")
            continue
        signals |= s_
        hcodes |= h_
        pictos |= p_
        used.add(key)
    if withheld is not None:
        withheld.extend(sorted(refused))
    if not (signals or hcodes):
        return None
    # GHS uses the most severe applicable signal word.
    signal = "Danger" if "Danger" in signals else ("Warning" if "Warning" in signals else None)
    return {"signal_word": signal, "pictograms": sorted(pictos),
            "h_statements": sorted(hcodes), "confidence": label_for("ghs"), "sources": sorted(used)}


# ── The words for each code (phase 3A, 2026-11-14) ────────────────────────────────────────────
# The molecule page showed bare codes ("H302") because no source for the wording was registered.
# The words come from the US Hazard Communication Standard (registry key osha_hcs, public domain),
# keyed by code in seeds/hazard_statements.yaml. A code the standard has no words for (the aquatic
# hazards, acute toxicity category 5) is left out of ``h_wording`` and stays a code on the page.
# The classification itself, its codes, signal word, pictograms and sources, is untouched.
HAZARD_STATEMENTS = SEEDS_DIR / "hazard_statements.yaml"
WORDING_SOURCE = "osha_hcs"


@functools.lru_cache(maxsize=1)
def hazard_wording() -> dict[str, str]:
    """code -> the standard's words, from the seed. A malformed entry stops the build."""
    data = yaml.safe_load(HAZARD_STATEMENTS.read_text()) or {}
    out, problems = {}, []
    for code, e in (data.get("statements") or {}).items():
        text = str((e or {}).get("text") or "").strip()
        if not _HCODE.fullmatch(str(code)) or not text or not (e or {}).get("hcs") or not (e or {}).get("class"):
            problems.append(f"{code}: needs an H code, text, hcs and class")
        elif "—" in text or "–" in text:
            problems.append(f"{code}: a dash in the text")
        else:
            out[str(code)] = text
    if problems:
        raise SystemExit(f"{HAZARD_STATEMENTS.name}: " + "; ".join(problems))
    return out


# Phase 3B (Garrett, 2026-11-14): a code the HCS does not word takes the EU CLP Regulation's words where CLP words it
# (registry key eu_clp, acknowledged, shown with its attribution): the five aquatic codes H400 and H410 to H413. Those
# codes are listed in ``h_wording_clp``; ``h_wording_source`` stays the HCS and is present only when the HCS words a code.
CLP_SOURCE = "eu_clp"


@functools.lru_cache(maxsize=1)
def clp_wording() -> dict[str, str]:
    """code -> CLP Annex III's words, for the codes the HCS does not word. A malformed entry, or a code both
    sources word, stops the build (one code, one wording)."""
    data = yaml.safe_load(HAZARD_STATEMENTS.read_text()) or {}
    hcs = hazard_wording()
    out, problems = {}, []
    for code, e in (data.get("eu_clp") or {}).items():
        text = str((e or {}).get("text") or "").strip()
        if not _HCODE.fullmatch(str(code)) or not text or not (e or {}).get("clp") or not (e or {}).get("class"):
            problems.append(f"{code}: needs an H code, text, clp and class")
        elif "\u2014" in text or "\u2013" in text:
            problems.append(f"{code}: a dash in the text")
        elif str(code) in hcs:
            problems.append(f"{code}: the HCS already words it")
        else:
            out[str(code)] = text
    if problems:
        raise SystemExit(f"{HAZARD_STATEMENTS.name} (eu_clp): " + "; ".join(problems))
    return out


def with_wording(ghs: dict | None) -> dict | None:
    """A copy of the hazard label with ``h_wording`` ({code: words}, the codes a registered standard words),
    ``h_wording_source`` (the HCS, when it words any of them) and ``h_wording_clp`` (the codes worded by the EU
    CLP Regulation, when any), or the label as it is when none of its codes has words."""
    if not ghs:
        return ghs
    words, clp = hazard_wording(), clp_wording()
    codes = ghs.get("h_statements") or []
    worded = {c: words[c] for c in codes if c in words}
    from_clp = {c: clp[c] for c in codes if c in clp}
    if not worded and not from_clp:
        return ghs
    out = dict(ghs)
    if worded:
        registry.assert_not_blocked(WORDING_SOURCE)
        out["h_wording"] = worded
        out["h_wording_source"] = WORDING_SOURCE
    if from_clp:
        registry.assert_not_blocked(CLP_SOURCE)
        out["h_wording"] = {**(out.get("h_wording") or {}), **from_clp}
        out["h_wording_clp"] = sorted(from_clp)
    # The key order of a record that had words before phase 3B is unchanged (h_wording, h_wording_source).
    return out
