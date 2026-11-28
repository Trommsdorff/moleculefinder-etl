"""One fact, every surface: trust review 2 (`mfetl review facts`; brief ../TRUST-3-ONE-FACT-PROMPT.md, 2026-11-27).

The same fact is stated in many places on the site (a molecule's formula on its own page, in a comparison, in a board,
in the search index, in structured data), each built by different code. When two disagree, a reader who sees both
stops trusting either. This review reads pages from the LIVE site, pulls every fact each page states, and compares each
with the snapshot ETL `main` holds and, through it, with every other page that states it.

READ-ONLY. It reads https://moleculefinder.com (cold reads, politely: WORKERS at a time, a PAUSE after each, a stated
User-Agent), the snapshot (``data/snapshots``) and ``facts_differences.yaml``. It makes no PubChem request and writes
nothing but its report: ``<out>/facts-<date>.md`` and ``.json``, the heartbeat ``<out>/facts-last-run.json`` and, for a
class seen on two consecutive runs, one line in ``<out>/QUEUE.md`` (the drawing review's plumbing, shared). It never
blocks, stops or changes the weekly refresh, the news job or a deploy. Exit 0 when it ran, whatever it found.

WHICH PAGES. A pinned set (one or more of every page family and variant, each with its written reason, PINNED) plus a
sample of SAMPLE sitemap addresses spread across the families, drawn by a seed made from the date (two runs on a day
read the same pages, tomorrow reads others). On Tuesdays (after Monday's refresh) it reads EVERY sitemap address, plus
the embed card of every molecule. A page it could not read is "not read", never counted as agreeing.

THE FACTS (the brief's numbering; compared by VALUE, never by wording):
 1. name, formula, weight   wherever shown: a molecule page's top line, its Properties table, its JSON-LD, its short
                            answers and meta description; each /vs page; each /whats-in, board, hub, world and card row
                            (a row is the nearest block that links to one molecule only); the search index; the embed
                            card; the RSS feed. A structure hub (functional group, element) listing a molecule whose
                            page has no formula; a size hub ("over 1000 g/mol") against the record's weight.
 2. LD50                    value, unit, species, route, chemical form and the "more than" qualifier, all together.
 3. hazard label            signal word, pictograms, hazard statements, and the attribution.
 4. status                  "over the counter" or "prescription" on a label page against the label's own record; a
                            molecule page's licence line against its approval record.
 5. counts                  a hub's count in its title, description and heading against the molecules it lists and the
                            snapshot; /explore's group counts; a label page's or world's count; a board's length and
                            leader against its rows and the snapshot; the site-wide counts on every page that states one.
                            (A findings headline is review 5's, not this one's.)
 6. data date               the date a reader sees for the data ("Data refreshed", the molecule of the week, the feed's
                            build date) against meta.json.
 7. text about a missing fact  a sentence naming a molecule's formula, weight, drawing or 3D model on a page where that
                            molecule has none (a panel page, a repeat-unit page), unless the sentence says it has none.
 8. promise                 a title or description promising "formula", "structure" or "3D" on a page that shows none.
                            Titles and descriptions are frozen until 2026-12-08: reported for the freeze release.
 9. links                   a link to a molecule, label, comparison, hub or board that is not in the catalogue, or to a
                            page that answered 404 or 410; a name that links to another molecule's page.

VALUE RULES (stated once, here and in docs/MAC-TRUST-REVIEWS.md):
 - Formula: equal when the element counts and the charge are equal (any order, "C8H10N4O2" = "O2N4C8H10"). Written
   differently from the record's molecular_formula is its own shape, "one value, written two ways"; in editorial text
   that shape is ruled (facts_differences.yaml, conventional-formula-in-editorial-text: NaHCO3 holds exactly the
   atoms of PubChem's CHNaO3).
 - Weight (ruled 2026-11-27, Garrett's word on Cowork's ruling 1, brief ../TRUST-3B-FACT-FINDINGS-PROMPT.md): a shown
   weight AGREES when it equals the record's molecular_weight rounded half-up to the precision shown, down to whole
   grams ("253.81" and "254" for 253.8089 are the same fact, correctly rounded). Anything else is a finding: more
   decimals than the record has, "shown to more precision than the record"; within half a unit of the last printed
   place but not the half-up rounding, "rounded the wrong way"; otherwise "two different values".
 - LD50: the number exact, the unit mg/kg, the qualifier words ("more than" for ">"), the species and route words as the
   site writes them (oral; intravenous; on the skin; another route), the chemical form "pure <name>".
 - Counts: integers, commas dropped. Dates: ISO dates; a week range must contain the snapshot's refreshed date.
 - A deliberate difference (facts_differences.yaml) is the only excuse; each excused case is listed, not hidden.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import decimal
import hashlib
import html as htmllib
import json
import random
import re
import statistics
import sys
import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

import yaml

from . import drawings as shared

ROOT = Path(__file__).resolve().parents[2]
SNAP = ROOT / "data" / "snapshots"
DIFFERENCES = Path(__file__).with_name("facts_differences.yaml")
DEFAULT_OUT = ROOT.parent / "trust-reports"
SITE = "https://moleculefinder.com"
NAME = "facts"
USER_AGENT = shared.USER_AGENT
SAMPLE = 150
SAMPLES_SHOWN = 10
WORKERS = 4                     # pages read at once: a small fixed concurrency
PAUSE = 0.25                    # each reader waits this long after each page
FULL_READ_WEEKDAY = 1           # Tuesday (Monday is 0): the day after the weekly refresh

# fact -> (the brief's number, heading, the recommended fix a queue item carries)
FACTS = {
    "name": (1, "Name", "Make the surface read the record's title (the snapshot's `title`), or correct the record."),
    "formula": (1, "Formula", ("Make the surface print the record's molecular_formula (or the ruled display form), "
                              "or correct the record; a value no record carries is a stale surface.")),
    "weight": (1, "Weight", ("Make the surface print the record's molecular_weight at one rounding, or drop it where "
                            "the record has none.")),
    "structure hub": (1, "Structure hub", ("Take the membership from the structure the page shows, or rule the "
                                          "difference with its reason.")),
    "LD50": (2, "LD50", ("Print the record's one LD50 with its qualifier, species, route and chemical form together "
                        "(lib/molecule-page.ts ld50Line).")),
    "hazard label": (3, "Hazard label", ("Print the record's GHS block (signal word, pictograms, statements) and its "
                                        "sources, from one helper.")),
    "status": (4, "Status", "Make the line read the label's or the record's own status (doc_type, is_otc, approval)."),
    "count": (5, "Counts", "Compute the stated count from the list the page shows (or the snapshot), in one place."),
    "data date": (6, "Data date", "Print meta.json's refreshed date; a page that shows another date is stale."),
    "text about a missing fact": (7, "Text about a fact the page lacks",
                                  ("Rewrite the sentence (it names a formula, weight, drawing or model the molecule "
                                  "no longer has); a frozen field waits for the freeze release.")),
    "promise": (8, "Promises", ("Change the title or description at the freeze release (2026-12-08): it promises what "
                               "the page does not show.")),
    "link": (9, "Links", "Point the link at a live page, or drop it."),
}

# The pinned set: one or more of every page family and variant, each with its written reason.
PINNED: dict[str, str] = {
    "/": "Home: the molecule of the week (formula, weight, week), its cards and the site-wide counts.",
    "/m/caffeine": "A plain drawn molecule with an LD50, a hazard label and a 3D model; the site's most cited example "
                   "(classroom, embed docs, /vs, the coffee door).",
    "/m/ibuprofen": "An over-the-counter medicine with a licence line (Drugs@FDA) and labels that cite it.",
    "/m/atorvastatin": "A prescription medicine with a licence line.",
    "/m/candesartan": "An LD50 a source gives as a limit: \"more than\" must travel with the figure.",
    "/m/silicon-dioxide": "A no-structure panel page printing the conventional formula (SiO2; PubChem O2Si): the "
                          "ruled difference.",
    "/m/zinc-oxide": "A second panel page (ZnO), the lattice kind.",
    "/m/inulin": "A repeat-unit page with no formula or weight; once led a board at a fragment's weight.",
    "/m/glycogen": "A repeat-unit page; its comparison once spoke of its \"listed formula and weight\".",
    "/m/chitin": "A repeat-unit page whose hubs come from the unit (the ruled difference).",
    "/m/shellac": "The stand-in panel: no formula, weight, drawing or model, a kept title.",
    "/m/cyanocobalamin": "A metal drawn with its bonds (metal_bonds): no 3D model.",
    "/m/glucose": "A sugar drawn as its ring (a display structure).",
    "/m/ivermectin": "A true drawing with a structure note (a mixture of two components).",
    "/m/sodium-chloride": "An ionic salt drawn as its ions.",
    "/m/levonorgestrel": "The LD50 hold case (2026-11-21).",
    "/m/insulin": "The biggest board's leader: its weight on the board and on its page.",
    "/vs/caffeine-vs-theobromine": "A /vs page with both molecules' weight, formula, LD50 and hazard.",
    "/vs/glucose-vs-glycogen": "A /vs page with a repeat-unit molecule: text must not name a formula or weight it lacks.",
    "/vs/maltodextrin-vs-starch": "A /vs page of two molecules with no formula.",
    "/whats-in/coffee": "A door page (rows with formulas, a molecule count in its title).",
    "/whats-in/advil": "An over-the-counter label page (rows with PubChem's formulas, including the panel molecules).",
    "/whats-in/lipitor": "A prescription label page.",
    "/whats-in": "The labels index: the product counts.",
    "/vs": "The comparisons index.",
    "/best": "The boards index.",
    "/best/biggest": "A weight board: its leader in its description, its rows' weights against the pages.",
    "/best/lightest": "The other weight board (the smallest values, the most decimals).",
    "/best/sweetest": "A board whose description opens with its leader.",
    "/in/alcohols": "A functional-group hub with repeat-unit members (count in title, description, heading, list).",
    "/in/over-1000-g-mol": "The size hub: every member's weight must be over 1000 g/mol.",
    "/in/element-nitrogen": "An element hub with repeat-unit members.",
    "/in/coffee": "A food-list hub.",
    "/in/prescription-medicine": "A broad-group hub (the largest).",
    "/in/ghs-danger": "A hazard-class hub (the signal word Danger).",
    "/explore": "Every group with its count; the site-wide count.",
    "/roam": "The worlds with their molecule counts.",
    "/roam/all": "Every molecule on one map: names and formulas for the whole catalogue.",
    "/roam/morning-coffee": "A world page.",
    "/classroom": "Lesson facts read from the records, and embed cards (formula, weight, LD50 or hazard).",
    "/embed": "The embed docs page's example card (caffeine).",
    "/about/methodology": "The sources and the data date.",
    "/molecule-of-the-week": "Every week's molecule with its formula; this week against the snapshot's date.",
    "/search-index.json": "The search index: every molecule's name and formula, every label's count.",
    "/molecule-of-the-week/feed.xml": "The RSS feed: each week's formula and the build date.",
    "/embed/caffeine.json": "An embed card with an LD50.",
    "/embed/silicon-dioxide.json": "An embed card for a panel molecule (PubChem's formula, by the ruling).",
    "/embed/inulin.json": "An embed card for a molecule with no formula or weight.",
}

SPECIES_PLURAL = {"rats": "rat", "mice": "mouse", "dogs": "dog", "rabbits": "rabbit", "guinea pigs": "guinea pig",
                  "cats": "cat", "monkeys": "monkey"}
ROUTE_WORDS = {"oral": "oral", "iv": "intravenous", "dermal": "on the skin", "other": "another route"}
QUALIFIER_WORDS = {">": "more than", "<": "less than", "~": "about"}
PICTOGRAMS = {"GHS01": "Explosive", "GHS02": "Flammable", "GHS03": "Oxidizer", "GHS04": "Compressed gas",
              "GHS05": "Corrosive", "GHS06": "Toxic", "GHS07": "Irritant", "GHS08": "Health hazard",
              "GHS09": "Environmental"}
ELEMENTS = {"H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm", "Md", "No", "Lr"}

_FORMULA_TOKEN = re.compile(r"(?<![\w-])((?:[A-Z][a-z]?\d*){1,40}(?:[+-]\d*)?)(?![\w])")
_WEIGHT = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*g/mol")
_LD50 = re.compile(r"(?:(more than|less than|about)\s+)?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*mg/kg")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
_NEGATION = re.compile(r"\b(no|not|none|without|neither|nor|never)\b", re.IGNORECASE)
_MISSING_WORDS = {
    "formula": re.compile(r"\bformulas?\b", re.IGNORECASE),
    "weight": re.compile(r"\b(molecular weight|weight|g/mol|heavier|lighter|heaviest|lightest)\b", re.IGNORECASE),
    "drawing": re.compile(r"\b(drawing|drawn|2D)\b", re.IGNORECASE),
    "3D model": re.compile(r"\b(?:3D|3-D) (?:models?|structures?|views?|conformers?)\b|\bin 3D\b"),
}
_PROMISES = {"formula": re.compile(r"\bformulas?\b", re.IGNORECASE),
             "structure": re.compile(r"\bstructures?\b", re.IGNORECASE),
             "3D": re.compile(r"\b3D (?:models?|structures?|views?)\b|\bin 3D\b")}
_SITE_COUNT = re.compile(r"\b(?:(?:all|search)\s+(?:the\s+)?(\d{1,3}(?:,\d{3})*)\s+molecules\b"
                         r"|(\d{1,3}(?:,\d{3})*)\s+molecules\s+(?:on|in)\s+(?:MoleculeFinder|the catalog(?:ue)?)\b)",
                         re.IGNORECASE)
_PRODUCT_COUNT = re.compile(r"\b(?:all|every)\s+(?:the\s+)?(\d{1,3}(?:,\d{3})*)\s+(?:product pages|products|labels|"
                            r"product labels)\b", re.IGNORECASE)
_WEEK = re.compile(r"\bThis week\s+(\d{1,2})(?:\s+([A-Z][a-z]+))?\s+to\s+(\d{1,2})\s+([A-Z][a-z]+)(?:\s+(\d{4}))?")
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August",
                                      "September", "October", "November", "December"], 1)}


# ── reading the live site ───────────────────────────────────────────────────────────────────────
def family_of(path: str) -> str:
    """A page family: the first part of its address (home, m, vs, whats-in, in, best, roam, ...); the index pages
    and the machine files are their own families."""
    if path == "/":
        return "home"
    if path.endswith((".json", ".xml")):
        return {"/search-index.json": "search index", "/sitemap.xml": "sitemap"}.get(
            path, "embed card" if path.startswith("/embed/") else "feed")
    parts = path.strip("/").split("/")
    return parts[0] if len(parts) > 1 else f"{parts[0]} (index)" if parts[0] in (
        "vs", "whats-in", "best", "roam", "findings", "legal", "about") else parts[0]


def sample_paths(paths: list[str], pinned: set[str], day: dt.date, k: int = SAMPLE) -> list[str]:
    """``k`` sitemap addresses outside the pinned set, spread across the families (two of each family that has two,
    the rest in proportion to the family's size), drawn by a seed made from the date."""
    seed = int(hashlib.sha256(f"moleculefinder-facts-{day.isoformat()}".encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    pools: dict[str, list[str]] = defaultdict(list)
    for p in sorted(set(paths) - pinned):
        pools[family_of(p)].append(p)
    fams = sorted(pools)
    take = {f: min(2, len(pools[f])) for f in fams}
    left = k - sum(take.values())
    total = sum(len(pools[f]) - take[f] for f in fams)
    if left > 0 and total:
        shares = {f: left * (len(pools[f]) - take[f]) / total for f in fams}
        extra = {f: int(shares[f]) for f in fams}
        rest = left - sum(extra.values())
        for f in sorted(fams, key=lambda f: (-(shares[f] - extra[f]), f))[:rest]:
            extra[f] += 1
        for f in fams:
            take[f] = min(len(pools[f]), take[f] + extra[f])
    out = []
    for f in fams:
        out += rng.sample(pools[f], take[f])
    return sorted(out)


def is_full_read(day: dt.date) -> bool:
    """The Tuesday rule: every sitemap address on the day after Monday's refresh."""
    return day.weekday() == FULL_READ_WEEKDAY


def read_all(paths: list[str], fetch, site: str, workers: int = WORKERS, pause: float = PAUSE) -> dict[str, dict]:
    """path -> {"status", "body"} for each page answered, or {"why"} for each it could not read. A small fixed number
    of readers, each pausing after every page."""
    out: dict[str, dict] = {}
    lock = threading.Lock()

    def one(path: str) -> None:
        try:
            status, body = fetch(site + path)
            r = {"status": status, "body": body}
        except Exception as e:                      # noqa: BLE001 (a page it cannot read is "not read", never 0)
            r = {"why": f"{type(e).__name__}: {e}"[:160]}
        finally:
            if pause:
                time.sleep(pause)
        with lock:
            out[path] = r

    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        list(ex.map(one, paths))
    return out


def sitemap_paths(xml_text: str, site: str = SITE) -> list[str]:
    root = ET.fromstring(xml_text)
    locs = [e.text.strip() for e in root.iter() if e.tag.endswith("loc") and e.text]
    return sorted({(u.removeprefix(site)) or "/" for u in locs})


# ── a small HTML tree (the standard library's parser; the pages are Next's well-formed output) ──
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
SKIP = {"script", "style", "svg", "template", "noscript", "head"}
INLINE = {"sub", "sup"}


class Node:
    __slots__ = ("attrs", "kids", "parent", "tag")

    def __init__(self, tag: str, attrs: dict, parent: Node | None):
        self.tag, self.attrs, self.kids, self.parent = tag, attrs, [], parent

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def iter(self):
        for k in self.kids:
            if isinstance(k, Node):
                yield k
                yield from k.iter()

    def find_all(self, pred):
        return [n for n in self.iter() if pred(n)]

    def text(self, hidden: bool = False) -> str:
        """The text a reader sees: no script, style, drawing or head, and (unless ``hidden``) nothing marked
        aria-hidden (a formula is typeset for the eye with sub tags and read from its hidden twin)."""
        parts: list[str] = []

        def walk(n: Node) -> None:
            for k in n.kids:
                if isinstance(k, str):
                    parts.append(k)
                elif k.tag in SKIP or (not hidden and k.attrs.get("aria-hidden") == "true"):
                    continue
                else:
                    sep = "" if k.tag in INLINE else " "
                    parts.append(sep)
                    walk(k)
                    parts.append(sep)
        walk(self)
        return " ".join("".join(parts).split())


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur)
        self.cur.kids.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.kids.append(Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.kids.append(data)


_SVG = re.compile(r"<svg\b.*?</svg>", re.DOTALL | re.IGNORECASE)
_SCRIPT = re.compile(r"<script\b(?![^>]*application/ld\+json)[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)


def parse_html(text: str) -> Node:
    b = _Builder()
    b.feed(_SCRIPT.sub("", _SVG.sub("<svg></svg>", text)))
    b.close()
    return b.root


@dataclass
class Page:
    path: str
    family: str
    raw: str
    root: Node
    title: str = ""
    description: str = ""
    jsonld: list = field(default_factory=list)
    main: Node | None = None

    @property
    def body(self) -> Node:
        return self.main or self.root


def page_of(path: str, raw: str) -> Page:
    root = parse_html(raw)
    pg = Page(path, family_of(path), raw, root)
    for n in root.iter():
        if n.tag == "title" and not pg.title:
            pg.title = htmllib.unescape("".join(k for k in n.kids if isinstance(k, str))).strip()
        elif n.tag == "meta" and n.attrs.get("name") == "description":
            pg.description = n.attrs.get("content") or ""
        elif n.tag == "script" and "ld+json" in (n.attrs.get("type") or ""):
            try:
                pg.jsonld.append(json.loads("".join(k for k in n.kids if isinstance(k, str))))
            except ValueError:
                pass
        elif n.tag == "main" and pg.main is None:
            pg.main = n
    return pg


def href_of(n: Node) -> str:
    h = n.attrs.get("href") or ""
    if h.startswith(SITE):
        h = h[len(SITE):] or "/"
    return h.split("#")[0].split("?")[0]


def mol_links(n: Node) -> list[tuple[str, Node]]:
    out = [(href_of(a)[3:], a) for a in ([n] if n.tag == "a" else []) + n.find_all(lambda x: x.tag == "a")
           if href_of(a).startswith("/m/")]
    return [(s, a) for s, a in out if s and "/" not in s]


# ── values ──────────────────────────────────────────────────────────────────────────────────────
def formula_value(s: str | None):
    """(element counts, charge), or None when the text is not a formula of real elements."""
    if not s:
        return None
    s = s.replace(" ", "")
    if not re.fullmatch(r"(?:[A-Z][a-z]?\d*)+(?:[+-]\d*)?", s):
        return None
    got = shared.formula_counts(s)
    if not got or not got[0] or any(e not in ELEMENTS for e in got[0]):
        return None
    return frozenset(got[0].items()), got[1]


def number(s: str) -> float:
    return float(s.replace(",", ""))


def decimals(s: str) -> int:
    return len(s.split(".", 1)[1]) if "." in s else 0


def weight_shape(printed: str, record: float | None) -> str | None:
    """None when the printed weight is the record's, or the record's rounded half-up to the precision shown (down to
    whole grams); else the shape of the difference (the rule in the module docstring, ruled 2026-11-27)."""
    if record is None:
        return "stated here, absent there"
    w = decimal.Decimal(printed.replace(",", ""))
    r = decimal.Decimal(str(record))
    shown, held = decimals(printed), max(0, -int(r.as_tuple().exponent))
    if shown > held:
        return "shown to more precision than the record"
    if w == r.quantize(decimal.Decimal(1).scaleb(-shown), rounding=decimal.ROUND_HALF_UP):
        return None
    if abs(w - r) <= decimal.Decimal(5).scaleb(-shown - 1):
        return "rounded the wrong way"
    return "two different values"


# ── the snapshot: what each fact should be ──────────────────────────────────────────────────────
class Truth:
    def __init__(self, snap: Path):
        self.recs = shared.load_records(snap)
        self.refreshed = json.loads((snap / "meta.json").read_text()).get("refreshed")
        prods = json.loads((snap / "products.json").read_text()).get("products") or []
        self.products = {p["slug"]: p for p in prods}
        doors = json.loads((snap / "doors.json").read_text()).get("doors") or []
        self.doors = {d.get("slug"): d for d in doors if isinstance(d, dict) and d.get("slug")}
        self.comparisons = json.loads((snap / "comparisons.json").read_text())
        self.boards = {p.stem: json.loads(p.read_text()) for p in sorted((snap / "leaderboards").glob("*.json"))
                       if p.stem != "index"}
        worlds = json.loads((snap / "worlds.json").read_text())
        self.worlds = {w["slug"]: w for w in worlds.get("worlds") or []}
        srcs = json.loads((snap / "sources.json").read_text()).get("sources") or []
        self.short = {s["key"]: s.get("short") or s.get("name") for s in srcs}
        self.hubs: dict[str, dict] = {}
        for slug, r in self.recs.items():
            for c in r.get("categories") or []:
                h = self.hubs.setdefault(c["slug"], {"kind": c.get("kind"), "name": c.get("name"), "members": set(),
                                                     "from_unit": set()})
                h["members"].add(slug)
                if c.get("from") == "repeat_unit":
                    h["from_unit"].add(slug)
        self.by_title: dict[str, str] = {}
        for slug, r in sorted(self.recs.items()):
            self.by_title.setdefault((r.get("title") or "").lower(), slug)
        self.formula_values = {formula_value(r.get("molecular_formula")) for r in self.recs.values()
                               if r.get("molecular_formula")}
        self.names = sorted(((t, s) for t, s in self.by_title.items() if len(t) >= 3), key=lambda x: -len(x[0]))
        self._name_re = None

    def formula(self, slug):
        return (self.recs.get(slug) or {}).get("molecular_formula")

    def shown_formula(self, slug):
        """The formula a molecule page shows: the panel's conventional form where the ruling gives one."""
        r = self.recs.get(slug) or {}
        return (r.get("structure_none") or {}).get("formula") or r.get("molecular_formula")

    def weight(self, slug):
        return (self.recs.get(slug) or {}).get("molecular_weight")

    def ld50(self, slug):
        r = self.recs.get(slug) or {}
        if r.get("ld50_mg_per_kg") is None:
            return None
        return {"value": float(r["ld50_mg_per_kg"]), "qualifier": QUALIFIER_WORDS.get(r.get("ld50_qualifier") or "", ""),
                "species": r.get("ld50_species"), "route": ROUTE_WORDS.get(r.get("ld50_route") or "", r.get("ld50_route")),
                "form": "pure " + (r["title"] if re.search(r"[A-Z]{2,}", r["title"])
                                   else r["title"][:1].lower() + r["title"][1:])}

    def ghs(self, slug):
        g = (self.recs.get(slug) or {}).get("ghs") or {}
        if not g or not (g.get("signal_word") or g.get("pictograms") or g.get("h_statements")):
            return None
        return {"signal": g.get("signal_word"), "pictos": {PICTOGRAMS[p] for p in g.get("pictograms") or []
                                                           if p in PICTOGRAMS},
                "codes": set(g.get("pictograms") or []), "h": set(g.get("h_statements") or []),
                "sources": {self.short.get(k, k) for k in g.get("sources") or []}}

    def name_regex(self):
        """Every catalogue title (three letters or more), longest first, as whole words, any case."""
        if self._name_re is None:
            alts = "|".join(re.escape(t) for t, _ in self.names)
            self._name_re = re.compile(rf"(?<![\w-])({alts})(?:'s)?(?![\w-])", re.IGNORECASE)
        return self._name_re

    def named(self, text: str) -> list[tuple[int, int, str]]:
        """(start, end, slug) for every molecule title named in the text."""
        return [(m.start(), m.end(), self.by_title[m.group(1).lower()]) for m in self.name_regex().finditer(text)]


# ── the deliberate differences ──────────────────────────────────────────────────────────────────
def _panel_formula(truth: Truth, subject: str, ctx: dict) -> bool:
    return bool(((truth.recs.get(subject) or {}).get("structure_none") or {}).get("formula"))


def _repeat_unit_membership(truth: Truth, subject: str, ctx: dict) -> bool:
    return subject in (truth.hubs.get(ctx.get("hub") or "") or {}).get("from_unit", set())


def _same_atoms(truth: Truth, subject: str, ctx: dict) -> bool:
    """The printed formula holds exactly the record's atoms (and charge): NaHCO3 for PubChem's CHNaO3."""
    got = formula_value(ctx.get("printed"))
    return got is not None and got == formula_value(truth.formula(subject))


SUBJECT_RULES = {"panel-formula": _panel_formula, "repeat-unit-membership": _repeat_unit_membership,
                 "same-atoms": _same_atoms}


def load_differences(path: Path = DIFFERENCES) -> dict:
    d = (yaml.safe_load(path.read_text()) or {}).get("differences") or {}
    for name, e in d.items():
        missing = [k for k in ("date", "by", "what", "reason", "fact", "shape", "surfaces", "subjects") if not e.get(k)]
        if missing:
            raise ValueError(f"facts_differences.yaml {name}: missing {', '.join(missing)}")
        if e["subjects"] not in SUBJECT_RULES:
            raise ValueError(f"facts_differences.yaml {name}: unknown subjects rule {e['subjects']}")
        if e["fact"] not in FACTS:
            raise ValueError(f"facts_differences.yaml {name}: unknown fact {e['fact']}")
    return d


# ── the run's findings ──────────────────────────────────────────────────────────────────────────
class Review:
    def __init__(self, truth: Truth, differences: dict):
        self.truth = truth
        self.differences = differences
        self.findings: list[dict] = []
        self.compared: Counter = Counter()            # (fact, surface, against) -> facts compared
        self.pages: dict[str, set] = defaultdict(set)  # fact -> pages it was compared on
        self.excused: dict[str, list] = defaultdict(list)
        self.unattributed: Counter = Counter()          # fact -> values found in prose with no molecule to own them
        self.notes: list[str] = []

    def check(self, fact: str, surface: str, against: str, subject: str, path: str, shape: str | None,
              detail: str = "", **ctx) -> bool:
        """Count one comparison; ``shape`` None means the two agree. A disagreement a deliberate difference covers is
        listed under its ruling, never dropped."""
        self.compared[(fact, surface, against)] += 1
        self.pages[fact].add(path)
        if shape is None:
            return True
        for name, e in self.differences.items():
            if e["fact"] == fact and e["shape"] == shape and surface in e["surfaces"] \
                    and SUBJECT_RULES[e["subjects"]](self.truth, subject, ctx):
                self.excused[name].append({"subject": subject, "path": path, "surface": surface, "detail": detail})
                return True
        self.findings.append({"fact": fact, "surface": surface, "against": against, "shape": shape,
                              "subject": subject, "path": path, "detail": detail})
        return False

    def total(self) -> int:
        return sum(self.compared.values())


# ── fact 1: name, formula, weight ───────────────────────────────────────────────────────────────
def check_formula(rv: Review, surface: str, slug: str, path: str, printed: str, against: str = "the record") -> None:
    t = rv.truth
    if slug not in t.recs:
        return
    val = formula_value(printed)
    rec = t.formula(slug)
    if val is None:
        rv.check("formula", surface, against, slug, path, "not a formula", f"printed {printed!r}")
        return
    if rec is None:
        rv.check("formula", surface, against, slug, path, "stated here, absent there",
                 f"printed {printed}; the record has no formula")
        return
    if formula_value(rec) != val:
        rv.check("formula", surface, against, slug, path, "two different values", f"printed {printed}, record {rec}")
    elif printed.replace(" ", "") != rec:
        rv.check("formula", surface, against, slug, path, "one value, written two ways",
                 f"printed {printed}, record {rec}", printed=printed)
    else:
        rv.check("formula", surface, against, slug, path, None)


def check_weight(rv: Review, surface: str, slug: str, path: str, printed: str, against: str = "the record") -> None:
    if slug not in rv.truth.recs:
        return
    rec = rv.truth.weight(slug)
    shape = weight_shape(printed, rec)
    rv.check("weight", surface, against, slug, path, shape,
             "" if shape is None else f"printed {printed} g/mol, record {rec if rec is not None else 'none'}")


def check_name(rv: Review, surface: str, slug: str, path: str, printed: str) -> None:
    rec = (rv.truth.recs.get(slug) or {}).get("title")
    if rec is None:
        return
    same = " ".join(printed.split()).lower() == rec.lower()
    rv.check("name", surface, "the record", slug, path, None if same else "two different values",
             "" if same else f"printed {printed!r}, record {rec!r}")


def formula_elements(n: Node) -> list[Node]:
    """The elements that typeset a formula: the hidden twin (`vh`) of a sub-tag formula, or an element whose class
    names a formula and whose whole text is one."""
    out = []
    for x in [n] + n.find_all(lambda _: True):
        c = x.classes
        if "vh" in c and formula_value(x.text(hidden=True)) and x.parent is not None and any(
                isinstance(k, Node) and k.attrs.get("aria-hidden") == "true" for k in x.parent.kids) or any("formula" in k for k in c) and not any("vh" in (y.classes) for y in x.find_all(lambda _: True)) \
                and formula_value(x.text()):
            out.append(x)
    return out


def typeset_matches(rv: Review, page: Page) -> None:
    """A typeset formula (the sub-tag version a reader sees) against its hidden twin (the version read aloud)."""
    for x in page.root.find_all(lambda n: "vh" in n.classes):
        p = x.parent
        if p is None:
            continue
        twin = [k for k in p.kids if isinstance(k, Node) and k.attrs.get("aria-hidden") == "true"]
        if not twin or not formula_value(x.text(hidden=True)):
            continue
        seen = twin[0].text(hidden=True).replace(" ", "")
        heard = x.text(hidden=True).replace(" ", "")
        rv.check("formula", "typeset formula", "its read-aloud twin", page.path, page.path,
                 None if seen == heard else "two different values", f"shown {seen}, read {heard}")


def weight_elements(n: Node) -> list[Node]:
    """Elements whose whole visible text is one weight ("194.19 g/mol", "5,808 g/mol")."""
    return [x for x in [n] + n.find_all(lambda _: True)
            if re.fullmatch(r"\s*(?:\d[\d,]*(?:\.\d+)?)\s*g/mol\s*", x.text() or "")
            and not any(re.fullmatch(r"\s*(?:\d[\d,]*(?:\.\d+)?)\s*g/mol\s*", y.text() or "")
                        for y in x.kids if isinstance(y, Node))]


def row_surface(page: Page) -> str:
    return {"home": "home card", "m": "molecule page card", "vs": "/vs row", "whats-in": "/whats-in row",
            "best": "board row", "in": "hub page row", "roam": "world card", "classroom": "classroom card",
            "molecule-of-the-week": "molecule of the week row", "explore": "/explore row", "embed": "embed docs card",
            "findings": "findings row"}.get(page.family.replace(" (index)", ""), f"{page.family} row")


def row_blocks(page: Page) -> list[tuple[str, Node]]:
    """(slug, block) for each molecule link: the largest ancestor, at most five levels up, whose links all go to that
    one molecule (a row, a card). A link inside the page's own top line is the page's, not a row."""
    out, seen = [], set()
    for slug, a in mol_links(page.body):
        block, n = a, a
        for _ in range(5):
            p = n.parent
            if p is None or p.tag in ("main", "body", "#root") or {s for s, _ in mol_links(p)} != {slug}:
                break
            n = p
            block = n
        if id(block) not in seen:
            seen.add(id(block))
            out.append((slug, block))
    return out


def name_text(x: Node, slug: str) -> str:
    """A name cell's name: the text of its link to the molecule if it holds one, else its text without any formula."""
    for s, a in mol_links(x):
        if s == slug:
            return a.text()
    hide = {id(f) for f in formula_elements(x)} | {id(f.parent) for f in formula_elements(x) if f.parent is not None}
    parts = []

    def walk(n: Node) -> None:
        for k in n.kids:
            if isinstance(k, str):
                parts.append(k)
            elif id(k) not in hide and k.tag not in SKIP and k.attrs.get("aria-hidden") != "true":
                parts.append(" ")
                walk(k)
                parts.append(" ")
    walk(x)
    return " ".join("".join(parts).split())


def check_rows(rv: Review, page: Page) -> None:
    surface = row_surface(page)
    for slug, block in row_blocks(page):
        if slug not in rv.truth.recs:
            continue
        fs = {x.text(hidden=True).replace(" ", "") for x in formula_elements(block)}
        if len(fs) == 1:
            check_formula(rv, surface, slug, page.path, fs.pop())
        elif len(fs) > 1:
            rv.unattributed["formula"] += len(fs)
        ws = {x.text().replace("g/mol", "").strip() for x in weight_elements(block)}
        if len(ws) == 1:
            check_weight(rv, surface, slug, page.path, ws.pop())
        elif len(ws) > 1:
            rv.unattributed["weight"] += len(ws)
        for x in block.find_all(lambda n: any(c.endswith("__name") for c in n.classes)):
            # a name cell is the molecule's only when it holds the link or sits inside it (a door's card also names
            # the product the molecule is in)
            inside = any(a.tag == "a" and href_of(a) == f"/m/{slug}" for a in _ancestors(x))
            if inside or any(s == slug for s, _ in mol_links(x)):
                check_name(rv, surface, slug, page.path, name_text(x, slug))
        check_ld50_in(rv, surface, slug, page.path, block.text())
        check_hazard_text(rv, surface, slug, page.path, block.text())


def check_molecule_page(rv: Review, page: Page, slug: str) -> None:
    t = rv.truth
    r = t.recs.get(slug)
    if r is None:
        return
    for h1 in page.body.find_all(lambda n: n.tag == "h1")[:1]:
        check_name(rv, "molecule page top line", slug, page.path, h1.text())
    facts = page.body.find_all(lambda n: "meet__facts" in n.classes)
    top_f = [x.text(hidden=True).replace(" ", "") for f in facts[:1] for x in formula_elements(f)]
    top_w = [x.text().replace("g/mol", "").strip() for f in facts[:1] for x in weight_elements(f)]
    for f in top_f[:1]:
        check_formula(rv, "molecule page top line", slug, page.path, f)
    for w in top_w[:1]:
        check_weight(rv, "molecule page top line", slug, page.path, w)
    props = {}
    for dl in page.body.find_all(lambda n: n.tag == "dl"):
        for d in dl.find_all(lambda n: n.tag == "div"):
            dt_ = [k for k in d.kids if isinstance(k, Node) and k.tag == "dt"]
            dd = [k for k in d.kids if isinstance(k, Node) and k.tag == "dd"]
            if dt_ and dd:
                props.setdefault(" ".join(dt_[0].text().split()[:2]), dd[0])
    if "Molecular formula" in props:
        fe = formula_elements(props["Molecular formula"])
        if fe:
            check_formula(rv, "molecule page Properties", slug, page.path, fe[0].text(hidden=True).replace(" ", ""))
    if "Molecular weight" in props:
        m = _WEIGHT.search(props["Molecular weight"].text())
        if m:
            check_weight(rv, "molecule page Properties", slug, page.path, m.group(1))
    # Shown here, absent there, the other way: the record has a formula or weight the page does not show.
    has_f = bool(top_f or "Molecular formula" in props)
    has_w = bool(top_w or "Molecular weight" in props)
    if r.get("molecular_formula"):
        rv.check("formula", "molecule page", "the record", slug, page.path,
                 None if has_f else "stated there, absent here", "" if has_f else "the record has a formula")
    if r.get("molecular_weight") is not None and not r.get("macromolecule"):
        rv.check("weight", "molecule page", "the record", slug, page.path,
                 None if has_w else "stated there, absent here", "" if has_w else "the record has a weight")
    for j in page.jsonld:
        if j.get("@type") == "MolecularEntity":
            if j.get("name"):
                check_name(rv, "molecule page JSON-LD", slug, page.path, j["name"])
            if j.get("molecularFormula"):
                check_formula(rv, "molecule page JSON-LD", slug, page.path, j["molecularFormula"])
            elif r.get("molecular_formula"):
                rv.check("formula", "molecule page JSON-LD", "the record", slug, page.path,
                         "stated there, absent here", "no molecularFormula")
            if j.get("molecularWeight"):
                check_weight(rv, "molecule page JSON-LD", slug, page.path, str(j["molecularWeight"]).split()[0])
        if j.get("@type") == "FAQPage":
            for q in j.get("mainEntity") or []:
                text = ((q.get("acceptedAnswer") or {}).get("text")) or ""
                check_prose(rv, "molecule page short answers", page.path, text, subject=slug)
    # LD50 and hazard: the Safety panel
    for b in page.body.find_all(lambda n: "pg--ld50" in n.classes):
        v = b.find_all(lambda n: "ld50__value" in n.classes)
        c = b.find_all(lambda n: "ld50__context" in n.classes)
        if v:
            check_ld50_in(rv, "molecule page Safety", slug, page.path, v[0].text() + " " + (c[0].text() if c else ""))
    if t.ld50(slug) and not page.body.find_all(lambda n: "pg--ld50" in n.classes):
        rv.check("LD50", "molecule page Safety", "the record", slug, page.path, "stated there, absent here",
                 "the record has an LD50; the page shows none")
    ghs = page.body.find_all(lambda n: "pg--ghs" in n.classes)
    if ghs:
        check_ghs_block(rv, slug, page.path, ghs[0])
    elif t.ghs(slug):
        rv.check("hazard label", "molecule page Safety", "the record", slug, page.path, "stated there, absent here",
                 "the record has a hazard label; the page shows none")
    check_licence(rv, slug, page)


# ── prose: sentences that name molecules ────────────────────────────────────────────────────────
def sentences(text: str) -> list[str]:
    return [s for s in _SENT.split(" ".join((text or "").split())) if s]


def owner(named: list[tuple[int, int, str]], pos: int, end: int, text: str, subject: str | None) -> str | None:
    """Who a value at ``pos`` belongs to: the molecule after "for" ("151.16 g/mol for Acetaminophen"), else the
    nearest molecule named before it in the sentence, else the page's own molecule."""
    after = re.match(r"(?:\s*\([^)]*\))?(?:,?\s+in\s+[a-z ]+?)?\s+for\s+", text[end:])
    if after:
        for s, _e, slug in named:
            if s == end + after.end():
                return slug
    before = [slug for s, e, slug in named if e <= pos]
    return before[-1] if before else subject


def check_prose(rv: Review, surface: str, path: str, text: str, subject: str | None = None,
                also: tuple = ()) -> None:
    """Formulas, weights and LD50s in running text, each owned by the molecule named nearest before it. A value that
    matches a molecule the sentence names (or the page's own, or a /vs page's pair: ``also``) is never reported: only
    a value no named molecule carries is a finding."""
    t = rv.truth
    for sent in sentences(htmllib.unescape(text)):
        named = t.named(sent)
        cands = {slug for _, _, slug in named} | ({subject} if subject else set()) | {s for s in also if s in t.recs}
        for m in _FORMULA_TOKEN.finditer(sent):
            tok = m.group(1)
            val = formula_value(tok)
            if not re.search(r"\d", tok) or val is None:
                continue
            vals = {s: formula_value(t.formula(s)) for s in cands if t.formula(s)}
            mine = [s for s, v in vals.items() if v == val]
            if mine:                                    # the formula of a molecule the sentence (or page) names
                check_formula(rv, surface, mine[0], path, tok)
                continue
            # A group (CH3, NHCOCH3), a vitamin's letter (B12, K2), or another catalogue molecule's formula under a name
            # the sentence does not use, is not held to the molecule named before it: only a molecular formula in
            # Hill order (C, then H, then three elements or more) that no catalogue molecule carries is.
            if val in t.formula_values or len(val[0]) < 3 or not re.match(r"C\d*H\d", tok):
                rv.unattributed["formula"] += 1
                continue
            who = owner(named, m.start(), m.end(), sent, subject)
            if who is None or (t.recs[who].get("scope_family") == "element" and len(val[0]) > 1):
                rv.unattributed["formula"] += 1
                continue
            check_formula(rv, surface, who, path, tok)
        for m in _WEIGHT.finditer(sent):
            who = owner(named, m.start(), m.end(), sent, subject)
            if who is None:
                rv.unattributed["weight"] += 1
                continue
            others = [s for s in cands if s != who and t.weight(s) is not None
                      and weight_shape(m.group(1), t.weight(s)) in (None, "rounded the wrong way")]
            if others and weight_shape(m.group(1), t.weight(who)) not in (None, "rounded the wrong way"):
                rv.compared[("weight", surface, "the record")] += 1
                continue
            check_weight(rv, surface, who, path, m.group(1))
        if "mg/kg" in sent:
            for m in _LD50.finditer(sent):
                who = owner(named, m.start(), m.end(), sent, subject)
                if who is None:
                    rv.unattributed["LD50"] += 1
                    continue
                check_ld50_in(rv, surface, who, path, sent[m.start():m.start() + 160], only_first=True,
                              before=sent[:m.start()])
        if re.search(r"signal word", sent):
            who = owner(named, sent.find("signal word"), sent.find("signal word"), sent, subject)
            if who:
                check_hazard_text(rv, surface, who, path, sent)


# ── fact 2: LD50 ────────────────────────────────────────────────────────────────────────────────
def ld50_context(after: str) -> dict:
    """Species, route and chemical form from the words after the figure: "(rat, oral)" or "pure caffeine, rat, oral"."""
    m = re.match(r"\s*\(([^)]*)\)", after) or re.match(r"\s*(pure [^,]+, [a-z ]+, (?:oral|intravenous|on the skin|"
                                                       r"another route|iv|other|dermal))\b", after)
    parts = [p.strip() for p in (m.group(1).split(",") if m else [])]
    out = {"species": None, "route": None, "form": None, "route_code": None}
    routes = set(ROUTE_WORDS.values())
    for p in parts:
        if p.startswith("pure "):
            out["form"] = p
        elif p in routes:
            out["route"] = p
        elif p in ROUTE_WORDS:                       # the record's code printed raw ("iv", "other")
            out["route"], out["route_code"] = ROUTE_WORDS[p], p
        elif p and out["species"] is None and re.fullmatch(r"[a-z][a-z ]*", p):
            out["species"] = p
    if not m:
        sp = re.match(r"\s+in\s+(rats|mice|dogs|rabbits|guinea pigs|cats|monkeys)\b", after)
        if sp:
            out["species"] = SPECIES_PLURAL[sp.group(1)]
    return out


def check_ld50_in(rv: Review, surface: str, slug: str, path: str, text: str, only_first: bool = False,
                  before: str = "") -> None:
    """Each LD50 in ``text`` against the record's one LD50. ``before`` is the sentence ahead of the figure: a route or
    species it names ("their reported oral LD50 values ... 2400 mg/kg in rats") counts as stated."""
    t = rv.truth
    if slug not in t.recs:
        return
    for m in list(_LD50.finditer(text))[:1 if only_first else None]:
        rec = t.ld50(slug)
        qual, val = (m.group(1) or ""), number(m.group(2))
        printed = f"{qual + ' ' if qual else ''}{m.group(2)} mg/kg"
        if rec is None:
            rv.check("LD50", surface, "the record", slug, path, "stated here, absent there",
                     f"printed {printed}; the record has no LD50")
            continue
        ctx = ld50_context(text[m.end():])
        if ctx["route"] is None:
            r = re.findall(r"\b(oral|intravenous)\b", before + " " + text[:m.start()])
            ctx["route"] = r[-1] if r else None
        if abs(val - rec["value"]) > 1e-9:
            rv.check("LD50", surface, "the record", slug, path, "two different values",
                     f"printed {printed}, record {rec['qualifier'] + ' ' if rec['qualifier'] else ''}{rec['value']:g}")
            continue
        if qual != rec["qualifier"]:
            rv.check("LD50", surface, "the record", slug, path, "the qualifier differs",
                     f"printed {printed!r}, record {(rec['qualifier'] or 'a value, no qualifier')!r}")
            continue
        wrong = [f"{k} {ctx[k]!r}, record {rec[k]!r}" for k in ("species", "route", "form")
                 if ctx[k] is not None and ctx[k] != rec[k]]
        if wrong:
            rv.check("LD50", surface, "the record", slug, path, "two different values", "; ".join(wrong))
            continue
        if ctx["route_code"]:
            rv.check("LD50", surface, "the record", slug, path, "one value, written two ways",
                     f"route printed as the code {ctx['route_code']!r}, elsewhere {rec['route']!r}")
            continue
        missing = [k if k != "form" else "chemical form" for k in ("species", "route", "form") if ctx[k] is None]
        rv.check("LD50", surface, "the copy rule", slug, path,
                 f"stated without its {' and '.join(missing)}" if missing else None,
                 f"printed {text[m.start():m.end() + 40]!r}" if missing else "")
        rv.compared[("LD50", surface, "the record")] += 1


# ── fact 3: hazard label ────────────────────────────────────────────────────────────────────────
def check_ghs_block(rv: Review, slug: str, path: str, block: Node) -> None:
    t = rv.truth
    rec = t.ghs(slug)
    text = block.text()
    surface = "molecule page Safety"
    if rec is None:
        rv.check("hazard label", surface, "the record", slug, path, "stated here, absent there",
                 "a hazard block; the record has no label")
        return
    sig = [n.text() for n in block.find_all(lambda n: "sig" in n.classes)]
    if rec["signal"] or sig:
        rv.check("hazard label", surface, "the record", slug, path,
                 None if (sig[:1] or [None])[0] == rec["signal"] else "two different values",
                 f"signal word {sig[:1]}, record {rec['signal']}")
    codes = set(re.findall(r"\b(GHS0\d)\b", text))
    rv.check("hazard label", surface, "the record", slug, path, None if codes == rec["codes"] else
             "two different values", f"pictograms {sorted(codes)}, record {sorted(rec['codes'])}")
    hs = {n.text() for n in block.find_all(lambda n: n.tag == "b" and re.fullmatch(r"(EU)?H\d{3}[A-Za-z]*", n.text()))}
    rv.check("hazard label", surface, "the record", slug, path, None if hs == rec["h"] else "two different values",
             f"statements {sorted(hs)}, record {sorted(rec['h'])}")
    head = block.find_all(lambda n: n.tag == "h3")
    m = re.search(r"Hazard label \(GHS\),\s*(.+?) via PubChem", head[0].text() if head else "")
    if m:
        names = {x.strip() for x in m.group(1).split(",")}
        rv.check("hazard label", surface, "the record's sources", slug, path,
                 None if names == rec["sources"] else "two different values",
                 f"attributed to {sorted(names)}, record {sorted(rec['sources'])}")
    else:
        rv.check("hazard label", surface, "the record's sources", slug, path, "stated without its attribution",
                 "no 'via PubChem' line")


def check_hazard_text(rv: Review, surface: str, slug: str, path: str, text: str) -> None:
    """A hazard label in a sentence or a card: "the signal word Warning and the hazard pictogram Irritant",
    "GHS hazard label: signal word Warning; Irritant ... ECHA via PubChem"."""
    m = re.search(r"signal word (Danger|Warning)", text)
    if not m or slug not in rv.truth.recs:
        return
    rec = rv.truth.ghs(slug)
    if rec is None:
        rv.check("hazard label", surface, "the record", slug, path, "stated here, absent there",
                 f"{m.group(0)!r}; the record has no label")
        return
    rv.check("hazard label", surface, "the record", slug, path,
             None if m.group(1) == rec["signal"] else "two different values",
             f"signal word {m.group(1)}, record {rec['signal']}")
    rest = text[m.end():]
    pm = re.match(r"\s*(?:and the hazard pictograms? |; )([A-Z][A-Za-z ,]+?)(?:\.|\s+from\b|\s+[A-Z]{2,}|$)", rest)
    if pm:
        names = {x.strip() for x in re.split(r",\s*|\s+and\s+", pm.group(1)) if x.strip()}
        names = {x for x in names if x in PICTOGRAMS.values()}
        if names:
            rv.check("hazard label", surface, "the record", slug, path,
                     None if names == rec["pictos"] else "two different values",
                     f"pictograms {sorted(names)}, record {sorted(rec['pictos'])}")


# ── fact 4: status ──────────────────────────────────────────────────────────────────────────────
def check_label_status(rv: Review, page: Page, slug: str) -> None:
    p = rv.truth.products.get(slug)
    if not p or (p.get("source") or {}).get("type") != "dailymed":
        return
    doc = ((p.get("source") or {}).get("doc_type") or "").upper()
    want = "over the counter" if "OTC" in doc else "prescription" if "PRESCRIPTION" in doc else None
    text = page.body.text()
    said = ("over the counter" if re.search(r"sold over the counter|with a Drug Facts label", text, re.IGNORECASE) else
            "prescription" if re.search(r"\bA prescription medicine\b", text) else None)
    if want is None and said is None:
        return
    rv.check("status", "/whats-in label line", "the label's record", slug, page.path,
             None if said == want else "two different values" if said and want else
             "stated here, absent there" if said else "stated there, absent here",
             f"the page says {said or 'nothing'}, the label is {doc or 'not a drug label'}")


def check_licence(rv: Review, slug: str, page: Page) -> None:
    r = rv.truth.recs.get(slug) or {}
    text = page.body.text()
    appr = r.get("approval") or {}
    m = re.search(r"([A-Z][\w ,()-]+?) licen[sc]es? \S.{0,80}? for human use", text) or \
        re.search(r"under the ([A-Z][\w ]+?)'s OTC Monograph", text)
    if appr or m:
        same = bool(m and appr and (appr.get("regulator") or "").lower() in m.group(0).lower())
        rv.check("status", "molecule page licence line", "the record's approval", slug, page.path,
                 None if same else "stated here, absent there" if m and not appr else
                 "stated there, absent here" if appr and not m else "two different values",
                 f"the page: {m.group(0) if m else 'no licence line'}; the record: {appr.get('regulator') or 'none'}")
    otc = bool(re.search(r"Sold over the counter, without a prescription", text))
    rx = bool(re.search(r"Dispensed on prescription, not sold on a shelf", text))
    # The third status (2026-11-27, ruling 4): sold both ways, which holds only where is_otc is true.
    both = bool(re.search(r"Sold over the counter in some products and on prescription in others", text))
    if otc or rx or both:
        said = "both ways" if both else "over the counter" if otc else "prescription"
        rv.check("status", "molecule page status line", "the record's is_otc", slug, page.path,
                 None if (otc or both) == bool(r.get("is_otc")) else "two different values",
                 f"the page says {said}, is_otc {r.get('is_otc')}")


# ── fact 5: counts ──────────────────────────────────────────────────────────────────────────────
def listed(page: Page, within: Node | None = None) -> set[str]:
    return {s for s, _ in mol_links(within or page.body)}


def check_hub(rv: Review, page: Page, slug: str) -> None:
    t = rv.truth
    hub = t.hubs.get(slug)
    grids = page.body.find_all(lambda n: "roam__grid" in n.classes)
    shown = set().union(*(listed(page, g) for g in grids)) if grids else set()
    snap = len(hub["members"]) if hub else None
    if hub is None:
        rv.check("count", "hub page", "the snapshot", slug, page.path, "stated here, absent there",
                 "a live hub no snapshot record belongs to")
        return
    rv.check("count", "hub page list", "the snapshot", slug, page.path,
             None if len(shown) == snap else "two different values", f"lists {len(shown)}, snapshot {snap}")
    for surface, text in (("hub title", page.title), ("hub description", page.description),
                          ("hub heading", page.body.text())):
        for m in re.finditer(r"(\d[\d,]*)\s+(?:molecules|examples|shown)\b", text):
            n = int(m.group(1).replace(",", ""))
            rv.check("count", surface, "its list", slug, page.path, None if n == len(shown) else
                     "two different values", f"states {n}, lists {len(shown)}")
            if surface != "hub heading":
                break
    # structure hubs: every member must have a structure on its page (the ruled exception: repeat-unit memberships)
    if hub["kind"] in ("functional_group", "element"):
        for s in sorted(shown):
            if s in t.recs and not t.formula(s):
                rv.check("structure hub", "hub page row", "its molecule page", s, page.path,
                         "listed in a structure hub, no formula on its page", f"/in/{slug} lists /m/{s}", hub=slug)
            elif s in t.recs:
                rv.check("structure hub", "hub page row", "its molecule page", s, page.path, None)
    m = re.fullmatch(r"(over|under)-(\d+)-g-mol", slug)
    if m:
        lim = float(m.group(2))
        for s in sorted(shown):
            w = t.weight(s)
            ok = w is not None and (w > lim if m.group(1) == "over" else w < lim)
            rv.check("weight", "size hub row", "the record", s, page.path,
                     None if ok else "stated here, absent there" if w is None else "two different values",
                     f"in /in/{slug}; record weight {w}")


def check_board(rv: Review, page: Page, slug: str) -> None:
    t = rv.truth
    b = t.boards.get(slug)
    rows = page.body.find_all(lambda n: n.tag == "a" and "rank__row" in n.classes)
    order = [href_of(r)[3:] for r in rows]
    if b is None:
        return
    entries = b.get("entries") or []
    rv.check("count", "board length", "the snapshot", slug, page.path,
             None if len(order) == len(entries) else "two different values",
             f"{len(order)} rows, snapshot {len(entries)}")
    if entries and order:
        rv.check("count", "board leader", "the snapshot", slug, page.path,
                 None if order[0] == entries[0]["slug"] else "two different values",
                 f"first row {order[0]}, snapshot {entries[0]['slug']}")
        first = rows[0].find_all(lambda n: "rank__name" in n.classes)
        first_name = first[0].text() if first else ""
        m = re.match(r"(.+?) leads the .+? board at ([\d,.]+)", page.description)
        if m:
            rv.check("count", "board description leader", "its first row", slug, page.path,
                     None if m.group(1) == first_name else "two different values",
                     f"names {m.group(1)}, first row {first_name}")
            named = t.by_title.get(m.group(1).lower())
            if b.get("metric") == "molecular_weight" and named:
                check_weight(rv, "board description", named, page.path, m.group(2))
    by_slug = {e["slug"]: e for e in entries}
    for r in rows:
        s = href_of(r)[3:]
        e = by_slug.get(s)
        val = r.find_all(lambda n: "rank__val" in n.classes)
        if e and val and b.get("metric") != "molecular_weight":
            printed = re.sub(r"[^\d.,]", " ", val[0].text()).split()
            if printed:
                v = number(printed[0])
                rv.check("count", "board row value", "the snapshot's board", s, page.path,
                         None if abs(v - float(e["value_num"])) <= 0.5 * 10 ** -decimals(printed[0]) + 1e-9
                         else "two different values", f"printed {printed[0]}, board {e['value_num']}")


def check_counts(rv: Review, page: Page) -> None:
    """Site-wide counts, /explore's and /roam's group counts, a label page's molecule count."""
    t = rv.truth
    text = " | ".join([page.body.text(), page.description] + [n.attrs.get("placeholder", "") for n in page.root.find_all(
        lambda n: n.tag == "input" and n.attrs.get("placeholder"))])
    for m in _SITE_COUNT.finditer(text):
        n = int((m.group(1) or m.group(2)).replace(",", ""))
        rv.check("count", "site-wide molecule count", "the snapshot", "site", page.path,
                 None if n == len(t.recs) else "two different values", f"states {n}, snapshot {len(t.recs)}")
    for m in _PRODUCT_COUNT.finditer(text if page.family != "findings" else ""):
        n = int(m.group(1).replace(",", ""))
        rv.check("count", "site-wide label count", "the snapshot", "site", page.path,
                 None if n == len(t.products) else "two different values", f"states {n}, snapshot {len(t.products)}")
    for a in page.body.find_all(lambda n: n.tag == "a" and href_of(n).startswith("/in/")):
        m = re.fullmatch(r"(.+?)\s+(\d[\d,]*)", a.text()) or (
            re.fullmatch(rf"{re.escape(a.text())}\s+(?:·\s*)?(\d[\d,]*)", a.parent.text()) if a.parent is not None
            and a.text() else None)
        if m and m.lastindex == 1:
            m = re.fullmatch(r"(.+?)\s+(?:·\s*)?(\d[\d,]*)", a.parent.text())
        hub = t.hubs.get(href_of(a)[4:])
        if m and hub and page.family in ("explore",):
            n = int(m.group(2).replace(",", ""))
            rv.check("count", "/explore group count", "the snapshot", href_of(a)[4:], page.path,
                     None if n == len(hub["members"]) else "two different values",
                     f"states {n}, snapshot {len(hub['members'])}")
    for a in page.body.find_all(lambda n: n.tag == "a" and href_of(n).startswith("/roam/")):
        m = re.search(r"(\d+)\s+molecules?\b", a.text())
        w = t.worlds.get(href_of(a)[6:])
        if m and w:
            rv.check("count", "world count", "the snapshot", w["slug"], page.path,
                     None if int(m.group(1)) == w.get("count") else "two different values",
                     f"states {m.group(1)}, snapshot {w.get('count')}")
    if page.family == "whats-in":
        slug = page.path.split("/")[2]
        p = t.products.get(slug)
        m = re.search(r":\s*(\d+)\s+molecules", page.title)
        if p and m:
            n = len({x["slug"] for x in p.get("molecules") or []})
            rv.check("count", "label page title", "the label's record", slug, page.path,
                     None if int(m.group(1)) == n else "two different values", f"states {m.group(1)}, record {n}")
        if p:
            rows = listed(page) & {x["slug"] for x in p.get("molecules") or []}
            n = len({x["slug"] for x in p.get("molecules") or []})
            rv.check("count", "label page rows", "the label's record", slug, page.path,
                     None if len(rows) == n else "two different values", f"links {len(rows)} of its {n} molecules")


# ── fact 6: the data date ───────────────────────────────────────────────────────────────────────
def check_dates(rv: Review, page: Page) -> None:
    t = rv.truth
    for n in page.body.find_all(lambda n: n.tag == "time"):
        p = n.parent
        ctx = (p.text() if p is not None else "")
        if re.search(r"refreshed|updated|as of", ctx, re.IGNORECASE):
            d = n.attrs.get("datetime") or n.attrs.get("dateTime") or n.text()
            rv.check("data date", "data refreshed line", "meta.json", page.path, page.path,
                     None if d[:10] == t.refreshed else "two different values",
                     f"shows {d[:10]}, meta.json {t.refreshed}")
    for m in _WEEK.finditer(page.body.text()):
        rf = dt.date.fromisoformat(t.refreshed)
        year = int(m.group(5) or rf.year)
        try:
            end = dt.date(year, MONTHS[m.group(4)], int(m.group(3)))
            start = dt.date(year, MONTHS[m.group(2) or m.group(4)], int(m.group(1)))
        except (KeyError, ValueError):
            continue
        if start > end:
            start = start.replace(year=year - 1)
        rv.check("data date", "molecule of the week, this week", "meta.json", page.path, page.path,
                 None if start <= rf <= end else "two different values",
                 f"shows {start} to {end}, meta.json {t.refreshed}")


# ── facts 7 and 8: text about a missing fact; promises ──────────────────────────────────────────
def lacks(r: dict) -> set[str]:
    out = set()
    if not r.get("molecular_formula"):
        out.add("formula")
    if r.get("molecular_weight") is None:
        out.add("weight")
    if not r.get("structure_svg") and not r.get("structure_repeat_unit"):
        out.add("drawing")
    if not r.get("has_3d"):
        out.add("3D model")
    return out


def prose_texts(page: Page) -> list[tuple[str, str]]:
    """(surface, text) of the running text a reader reads: the title, the description, the short answers, and each
    paragraph, list item and definition in the page's main part."""
    out = [("title", page.title), ("meta description", page.description)]
    for j in page.jsonld:
        if j.get("@type") == "FAQPage":
            out += [("short answers", f"{q.get('name', '')} {(q.get('acceptedAnswer') or {}).get('text', '')}")
                    for q in j.get("mainEntity") or []]
    for n in page.body.find_all(lambda n: n.tag in ("p", "li", "dd", "figcaption", "h2", "h3")):
        if not any(isinstance(k, Node) and k.tag in ("p", "li", "dd") for k in n.iter()):
            out.append(("page text", n.text()))
    return out


def check_missing_refs(rv: Review, page: Page) -> None:
    t = rv.truth
    lacking = {s: lacks(r) for s, r in t.recs.items()}
    own = page.path[3:] if page.family == "m" else None
    for surface, text in prose_texts(page):
        for sent in sentences(htmllib.unescape(text)):
            for _s, _e, slug in t.named(sent):
                if slug == own and surface in ("title", "meta description"):
                    continue                        # its own title and description are promises (fact 8)
                miss = lacking.get(slug) or set()
                if t.recs[slug].get("scope_family") == "element" and not sent[_s:_e][:1].isupper():
                    continue                        # "carbon" as a common noun, not the element's page
                hits = [w for w in sorted(miss) if _MISSING_WORDS[w].search(sent[_s:])]   # said of it, after its name
                if not miss:
                    continue
                if hits and not _NEGATION.search(sent):
                    rv.check("text about a missing fact", surface, "its molecule page", slug, page.path,
                             f"names a {hits[0]} the molecule's page does not show", sent[:200])
                else:
                    rv.check("text about a missing fact", surface, "its molecule page", slug, page.path, None)


def shows(page: Page) -> dict[str, bool]:
    """What the page itself shows: a formula (a molecule page's top line; elsewhere any typeset formula), a structure
    drawing (the 2D drawing, a repeat unit, or any RDKit drawing inline) and a 3D model (its control)."""
    formula = bool(page.body.find_all(lambda n: "meet__formula" in n.classes)) if page.family == "m" \
        else bool(formula_elements(page.body))
    return {"formula": formula,
            "structure": 'class="v3__2d"' in page.raw or 'class="meet__unit"' in page.raw
                         or (page.family != "m" and "xmlns:rdkit" in page.raw),   # a molecule page: its own drawing
            "3D": 'aria-label="Structure view"' in page.raw}


def check_promises(rv: Review, page: Page, subject: str) -> None:
    s = shows(page)
    kind = {"m": "molecule page", "in": "hub page", "vs": "/vs page", "whats-in": "/whats-in page",
            "best": "board page", "roam": "world page"}.get(page.family, f"{page.family} page")
    for where, text in (("title", page.title), ("meta description", page.description)):
        if where == "meta description" and (page.family != "m" or _NEGATION.search(text or "")):
            continue    # a description promises only on a molecule's own page; "no diagram" is not a promise
        for word, rx in _PROMISES.items():
            if rx.search(text or ""):
                rv.check("promise", f"{kind} {where}", "what the page shows", subject, page.path,
                         None if s[word] else f"promises {word}, the page shows none", text[:160])


# ── fact 9: links ───────────────────────────────────────────────────────────────────────────────
def known_path(t: Truth, href: str, sitemap: set[str]) -> bool | None:
    """True when the catalogue has the address, False when it should not exist, None when this review cannot say."""
    parts = href.strip("/").split("/")
    if href in sitemap:
        return True
    if len(parts) == 2:
        kind, slug = parts
        if kind == "m":
            return slug in t.recs
        if kind == "vs":
            return slug in t.comparisons
        if kind == "whats-in":
            return slug in t.products or slug in t.doors
        if kind == "in":
            return slug in t.hubs
        if kind == "best":
            return slug in t.boards
    return None


def check_links(rv: Review, page: Page, sitemap: set[str], statuses: dict[str, int]) -> None:
    t = rv.truth
    for a in page.body.find_all(lambda n: n.tag == "a"):
        h = href_of(a)
        if not h.startswith("/") or h.startswith("//") or h.split("/")[1] not in ("m", "vs", "whats-in", "in", "best",
                                                                                 "roam"):
            continue
        ok = known_path(t, h, sitemap)
        st = statuses.get(h)
        if st in (404, 410):
            rv.check("link", f"{row_surface(page)} link", "the page it links to", h, page.path,
                     f"links to a page that answers {st}", f"{page.path} -> {h}")
        elif ok is False:
            rv.check("link", f"{row_surface(page)} link", "the catalogue", h, page.path,
                     "links to a page the catalogue does not have", f"{page.path} -> {h}")
        elif ok:
            rv.check("link", f"{row_surface(page)} link", "the catalogue", h, page.path, None)
        if h.startswith("/m/"):
            txt = a.text()
            other = t.by_title.get(txt.lower())
            if other and other != h[3:] and h[3:] in t.recs:
                rv.check("link", f"{row_surface(page)} link", "the name it carries", h[3:], page.path,
                         "a name that links to another molecule's page", f"'{txt}' -> {h}")


# ── the machine files ───────────────────────────────────────────────────────────────────────────
def check_search_index(rv: Review, body: str, path: str) -> None:
    t = rv.truth
    entries = json.loads(body)
    mols = [e for e in entries if not e.get("type")]
    for e in mols:
        s = e.get("slug")
        if s not in t.recs:
            rv.check("link", "search index", "the catalogue", f"/m/{s}", path,
                     "links to a page the catalogue does not have", f"/m/{s}")
            continue
        check_name(rv, "search index", s, path, e.get("title") or "")
        if e.get("formula"):
            check_formula(rv, "search index", s, path, e["formula"])
        elif t.formula(s):
            rv.check("formula", "search index", "the record", s, path, "stated there, absent here", "no formula")
    for e in entries:
        if e.get("type") == "product" and e.get("src") != "door" and e.get("n") is not None:
            p = t.products.get(e["slug"])
            if p:
                n = len({x["slug"] for x in p.get("molecules") or []})
                rv.check("count", "search index label count", "the label's record", e["slug"], path,
                         None if e["n"] == n else "two different values", f"states {e['n']}, record {n}")
    rv.check("count", "search index molecules", "the snapshot", "site", path,
             None if len(mols) == len(t.recs) else "two different values",
             f"{len(mols)} molecules, snapshot {len(t.recs)}")


def check_embed(rv: Review, body: str, path: str) -> None:
    d = json.loads(body)
    s = d.get("slug")
    t = rv.truth
    if s not in t.recs:
        return
    check_name(rv, "embed card", s, path, d.get("name") or "")
    if d.get("formula"):
        check_formula(rv, "embed card", s, path, d["formula"])
    elif t.formula(s):
        rv.check("formula", "embed card", "the record", s, path, "stated there, absent here", "no formula")
    if d.get("weight") is not None:
        check_weight(rv, "embed card", s, path, str(d["weight"]))
    elif t.weight(s) is not None:
        rv.check("weight", "embed card", "the record", s, path, "stated there, absent here", "no weight")
    hz = d.get("hazard") or {}
    if hz.get("kind") == "ld50":
        check_ld50_in(rv, "embed card", s, path, hz.get("text") or "")
    elif hz.get("kind") == "ghs":
        check_hazard_text(rv, "embed card", s, path, (hz.get("text") or "") + " ")
        rec = t.ghs(s)
        m = re.fullmatch(r"(.+?) via PubChem", hz.get("source") or "")
        if rec and m:
            names = {x.strip() for x in m.group(1).split(",")}
            rv.check("hazard label", "embed card", "the record's sources", s, path,
                     None if names == rec["sources"] else "two different values",
                     f"attributed to {sorted(names)}, record {sorted(rec['sources'])}")


def check_feed(rv: Review, body: str, path: str) -> None:
    t = rv.truth
    root = ET.fromstring(body)
    lb = root.find("./channel/lastBuildDate")
    if lb is not None and lb.text:
        try:
            d = dt.datetime.strptime(lb.text.strip(), "%a, %d %b %Y %H:%M:%S %Z").date().isoformat()
        except ValueError:
            d = lb.text.strip()
        rv.check("data date", "RSS build date", "meta.json", path, path,
                 None if d == t.refreshed else "two different values", f"shows {d}, meta.json {t.refreshed}")
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        slug = link.rsplit("/m/", 1)[-1] if "/m/" in link else None
        if not slug:
            continue
        if slug not in t.recs:
            rv.check("link", "RSS item", "the catalogue", f"/m/{slug}", path,
                     "links to a page the catalogue does not have", link)
            continue
        m = re.search(r"Formula:\s*([A-Za-z0-9+-]+)\.", item.findtext("description") or "")
        if m:
            check_formula(rv, "RSS item", slug, path, m.group(1))
        title = item.findtext("title") or ""
        tm = re.match(r"Week \d+, \d{4}: (.+)$", title)
        if tm:
            check_name(rv, "RSS item", slug, path, tm.group(1))


# ── the repetition measure (reported, never a finding) ──────────────────────────────────────────
BLOCK_TAGS = {"p", "li", "dd", "dt", "td", "th", "h1", "h2", "h3", "h4", "figcaption", "summary", "blockquote",
              "label", "button", "caption"}


def _own_text(n: Node) -> str:
    """A block's text without the blocks nested in it (they are pieces of their own); its links' text stays."""
    parts: list[str] = []

    def walk(x: Node) -> None:
        for k in x.kids:
            if isinstance(k, str):
                parts.append(k)
            elif k.tag in SKIP or k.attrs.get("aria-hidden") == "true" or k.tag in BLOCK_TAGS:
                continue
            else:
                sep = "" if k.tag in INLINE else " "
                parts.append(sep)
                walk(k)
                parts.append(sep)
    walk(n)
    return " ".join("".join(parts).split())


def pieces(node: Node) -> list[str]:
    """The page's visible text cut into pieces: each paragraph, list item, cell, heading or caption (its own text, the
    links in it included, the blocks nested in it cut out as pieces of their own) and each link that stands outside
    any such block (a card), split into sentences; whitespace collapsed. Exact text, case kept."""
    out = []
    for n in node.find_all(lambda n: n.tag in BLOCK_TAGS or n.tag == "a"):
        anc = list(_ancestors(n))
        if any(a.tag in SKIP or a.attrs.get("aria-hidden") == "true" for a in anc):
            continue
        if n.tag == "a" and any(a.tag in BLOCK_TAGS or a.tag == "a" for a in anc):
            continue                                # a link inside a block is part of the block's text
        out += sentences(_own_text(n))
    return [p for p in out if p]


def _ancestors(n: Node):
    p = n.parent
    while p is not None:
        yield p
        p = p.parent


def repetition(by_family: dict[str, dict[str, list[str]]], top: int = 10) -> dict:
    """Per family (three pages or more): a piece is SHARED when it appears on at least half of the family's pages
    read; a page's UNIQUE share is the characters of the pieces found on that page alone over all its characters."""
    out = {}
    for fam, pages in sorted(by_family.items()):
        if len(pages) < 3:
            continue
        on = Counter()
        for ps in pages.values():
            on.update(set(ps))
        half = len(pages) / 2
        shares, own = {}, {}
        for path, ps in pages.items():
            total = sum(len(p) for p in ps)
            uniq = sum(len(p) for p in ps if on[p] == 1)
            shares[path] = uniq / total if total else 0.0
            own[path] = uniq
        shared_blocks = sorted(((p, c) for p, c in on.items() if c >= half), key=lambda x: (-len(x[0]), x[0]))[:top]
        vals = sorted(shares.values())
        shared_chars = {path: sum(len(p) for p in ps if on[p] >= half) for path, ps in pages.items()}
        tot = {path: sum(len(p) for p in ps) for path, ps in pages.items()}
        out[fam] = {
            "pages": len(pages),
            "unique_share_median": round(statistics.median(vals), 3),
            "unique_share_min": round(vals[0], 3), "unique_share_max": round(vals[-1], 3),
            "shared_share_median": round(statistics.median(
                [shared_chars[p] / tot[p] if tot[p] else 0.0 for p in pages]), 3),
            "longest_shared": [{"text": p[:240], "chars": len(p), "pages": c} for p, c in shared_blocks],
            "least_own_text": [{"path": p, "own_chars": own[p], "unique_share": round(shares[p], 3)}
                               for p in sorted(pages, key=lambda p: (own[p], p))[:top]],
        }
    return out


# ── one page ────────────────────────────────────────────────────────────────────────────────────
def check_page(rv: Review, page: Page, sitemap: set[str], statuses: dict[str, int]) -> None:
    fam = page.family
    parts = page.path.strip("/").split("/")
    typeset_matches(rv, page)
    if fam == "m":
        check_molecule_page(rv, page, parts[1])
        check_promises(rv, page, parts[1])
        check_prose(rv, "meta description", page.path, page.description, subject=parts[1])
    else:
        pair = tuple((rv.truth.comparisons.get(parts[1]) or {}).get(k) for k in ("a", "b")) if fam == "vs" else ()
        check_prose(rv, "meta description", page.path, page.description, also=pair)
        check_prose(rv, "title", page.path, page.title, also=pair)
        check_promises(rv, page, page.path)
        for j in page.jsonld:
            if j.get("@type") == "FAQPage":
                for q in j.get("mainEntity") or []:
                    check_prose(rv, f"{row_surface(page).split(' ')[0]} short answers", page.path,
                                ((q.get("acceptedAnswer") or {}).get("text")) or "", also=pair)
    if fam == "vs":
        check_vs(rv, page, parts[1])
    if fam == "whats-in":
        check_label_status(rv, page, parts[1])
    if fam == "in":
        check_hub(rv, page, parts[1])
    if fam == "best":
        check_board(rv, page, parts[1])
    check_rows(rv, page)
    pair = tuple((rv.truth.comparisons.get(parts[1]) or {}).get(k) for k in ("a", "b")) if fam == "vs" else ()
    for p in page.body.find_all(lambda n: n.tag == "p" and not mol_links(n)):
        check_prose(rv, f"{row_surface(page).split(' row')[0].split(' card')[0]} text", page.path, p.text(),
                    subject=parts[1] if fam == "m" else None, also=pair)
    check_counts(rv, page)
    check_dates(rv, page)
    check_missing_refs(rv, page)
    check_links(rv, page, sitemap, statuses)


def check_vs(rv: Review, page: Page, pair: str) -> None:
    c = rv.truth.comparisons.get(pair) or {}
    for table in page.body.find_all(lambda n: n.tag == "table" and "vs-table" in n.classes):
        for tr in table.find_all(lambda n: n.tag == "tr"):
            row = tr.attrs.get("data-row")
            cells = [k for k in tr.kids if isinstance(k, Node) and k.tag == "td"]
            heads = [h for h in table.find_all(lambda n: n.tag == "th" and n.parent is not None
                                               and n.parent.parent is not None and n.parent.parent.tag == "thead")]
            slugs = [s for h in heads for s, _ in mol_links(h)]
            if len(slugs) != len(cells) or not cells:
                continue
            for s, td in zip(slugs, cells):
                if row == "weight":
                    w = _WEIGHT.search(td.text())
                    if w:
                        check_weight(rv, "/vs side by side", s, page.path, w.group(1))
                    elif rv.truth.weight(s) is not None:
                        rv.check("weight", "/vs side by side", "the record", s, page.path, "stated there, absent here",
                                 "no weight in its cell")
                    fe = formula_elements(td)
                    if fe:
                        check_formula(rv, "/vs side by side", s, page.path, fe[0].text(hidden=True).replace(" ", ""))
                if row and "ld50" in row:
                    check_ld50_in(rv, "/vs side by side", s, page.path, td.text())
                if row and ("hazard" in row or "ghs" in row):
                    sig = td.text().split(" ")[0] if td.text() else ""
                    rec = rv.truth.ghs(s)
                    if sig in ("Danger", "Warning"):
                        rv.check("hazard label", "/vs side by side", "the record", s, page.path,
                                 None if rec and rec["signal"] == sig else "two different values",
                                 f"signal word {sig}, record {rec['signal'] if rec else 'none'}")
    if c:
        mentioned = {s for s, _ in mol_links(page.body)}
        for k in ("a", "b"):
            if c.get(k) and c[k] not in mentioned:
                rv.check("link", "/vs page", "its pair", c[k], page.path, "a molecule of the pair is not linked",
                         f"{pair}: /m/{c[k]}")


# ── the report ──────────────────────────────────────────────────────────────────────────────────
def class_key(f: dict) -> str:
    return f"{f['fact']} / {f['surface']} against {f['against']} / {f['shape']}"


def summarise(rv: Review) -> dict[str, dict]:
    classes: dict[str, dict] = {}
    for f in rv.findings:
        k = class_key(f)
        c = classes.setdefault(k, {"fact": f["fact"], "surface": f["surface"], "against": f["against"],
                                   "shape": f["shape"], "records": [], "addresses": [], "details": {}, "count": 0})
        c["count"] += 1
        item = f"{f['subject']} @ {f['path']}"
        if item not in c["details"]:
            c["records"].append(f["subject"]) if f["subject"] not in c["records"] else None
            c["addresses"].append(f["path"]) if f["path"] not in c["addresses"] else None
            c["details"][item] = f["detail"]
    for k, c in classes.items():
        c["of"] = rv.compared[(c["fact"], c["surface"], c["against"])]
        c["noun"] = f"{c['fact']} facts on {c['surface']}"
        c["pages"] = len(c["addresses"])
    order = {f: FACTS[f][0] for f in FACTS}
    return dict(sorted(classes.items(), key=lambda kv: (order.get(kv[1]["fact"], 99), -kv[1]["count"], kv[0])))


def verdict_line(classes: dict, facts: int, read: int, not_read: int) -> str:
    return (f"VERDICT: {len(classes)} finding class{'es' if len(classes) != 1 else ''} found "
            f"({sum(c['count'] for c in classes.values()):,} findings); {facts:,} facts compared; {read:,} pages read; "
            f"{not_read:,} pages not read.")


def _jsonable(x):
    return sorted(x) if isinstance(x, (set, frozenset)) else str(x)


def write_report(out: Path, day: dt.date, rv: Review, live: dict, meta: dict, rep: dict | None) -> dict:
    classes = summarise(rv)
    prev = shared.previous_report(out, day, NAME)
    pc = (prev or {}).get("classes") or {}
    for k, c in classes.items():
        before = pc.get(k)
        c["change"] = ("first run" if prev is None else "new" if before is None else f"{c['count'] - before['count']:+d}")
        if before:
            c["added"] = sorted(set(c["records"]) - set(before["records"]))[:20]
            c["left"] = sorted(set(before["records"]) - set(c["records"]))[:20]
    gone = sorted(set(pc) - set(classes)) if prev else []
    verdict = verdict_line(classes, rv.total(), len(live["read"]), len(live["not_read"]))
    queued = shared.queue_new(out, classes, prev, day, name=NAME, recommend=lambda c: FACTS[c["fact"]][2])
    by_fact = Counter()
    pages_by_fact = {}
    for (f, _s, _a), n in rv.compared.items():
        by_fact[f] += n
    for f, ps in rv.pages.items():
        pages_by_fact[f] = len(ps)
    data = {
        "verdict": verdict, "date": day.isoformat(), "time": meta["time"], "etl_commit": meta["commit"],
        "snapshot_refreshed": rv.truth.refreshed, "records": len(rv.truth.recs), "mode": live["mode"],
        "seconds": live.get("seconds"), "classes": classes, "gone_since_last_run": gone,
        "previous_run": (prev or {}).get("date"),
        "facts_compared": {f: {"facts": by_fact[f], "pages": pages_by_fact.get(f, 0)} for f in FACTS if by_fact[f]},
        "surfaces": {f"{f} / {s} against {a}": n for (f, s, a), n in sorted(rv.compared.items())},
        "unattributed": dict(rv.unattributed),
        "excused": {k: {"entry": {x: rv.differences[k][x] for x in ("date", "by", "what", "reason")},
                        "count": len(v), "cases": v[:50]} for k, v in rv.excused.items()},
        "differences": {k: {x: v[x] for x in ("date", "by", "what", "reason", "fact", "shape", "surfaces", "subjects")}
                        for k, v in rv.differences.items()},
        "live": {k: live[k] for k in ("mode", "pinned", "sampled", "read", "not_read", "seed", "statuses_not_200")},
        "repetition": rep, "queued_today": queued, "notes": rv.notes,
    }
    (out / f"{NAME}-{day.isoformat()}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False, default=_jsonable)
                                                        + "\n")
    (out / f"{NAME}-{day.isoformat()}.md").write_text(render_md(data))
    return data


def render_md(d: dict) -> str:
    L = [d["verdict"], "", f"# One fact, every surface, {d['date']}", ""]
    w = L.append
    lv = d["live"]
    w(f"Trust review 2 (`mfetl review facts`, ETL `moleculefinder_etl/review/facts.py`), run {d['time']} against the "
      f"snapshot ETL `{d['etl_commit']}` holds (refreshed {d['snapshot_refreshed']}). Read-only: it changed nothing. "
      f"This run: **{lv['mode']}** read"
      + (f", {d['seconds']:.0f} seconds" if d.get("seconds") else "")
      + f". Previous run: {d['previous_run'] or 'none (this is the first)'}.")
    w("")
    w("## Findings, class by class")
    w("")
    w("Each class is the fact, the surface it was read on, what it was compared with, and the shape of the "
      "difference. The count is findings of all the facts of that kind compared on that surface.")
    w("")
    if not d["classes"]:
        w("None.")
    for k, c in d["classes"].items():
        w(f"### {k}")
        w(f"- **{c['count']:,} of {c['of']:,} {c['noun']}**, on {c['pages']:,} page(s); since the last run: "
          f"{c['change']}" + (f" (in: {', '.join(c['added'])})" if c.get("added") else "")
          + (f" (out: {', '.join(c['left'])})" if c.get("left") else ""))
        for item, det in list(c["details"].items())[:SAMPLES_SHOWN]:
            subj, path = item.split(" @ ", 1)
            w(f"  - {SITE}{path} ({subj})" + (f": {det}" if det else ""))
        if len(c["details"]) > SAMPLES_SHOWN:
            w(f"  - and {len(c['details']) - SAMPLES_SHOWN:,} more (the JSON lists every one)")
        w(f"- Recommended: {FACTS[c['fact']][2]}")
        w("")
    if d["gone_since_last_run"]:
        w("Classes found last run and not this run: " + "; ".join(d["gone_since_last_run"]) + ".")
        w("")
    if d["queued_today"]:
        w("Added to QUEUE.md today (seen on two consecutive runs): " + "; ".join(d["queued_today"]) + ".")
        w("")
    w("## Facts compared")
    w("")
    w("| # | fact | facts compared | pages |")
    w("|---|---|---|---|")
    for f, v in d["facts_compared"].items():
        w(f"| {FACTS[f][0]} | {f} | {v['facts']:,} | {v['pages']:,} |")
    if d["unattributed"]:
        w("")
        w("Values found in running text that no molecule named in the sentence (or the page) could own, so not "
          "compared: " + ", ".join(f"{k} {v:,}" for k, v in sorted(d["unattributed"].items())) + ".")
    w("")
    w("## Deliberate differences (facts_differences.yaml)")
    w("")
    for k, e in d["differences"].items():
        ex = (d["excused"].get(k) or {}).get("count", 0)
        w(f"- `{k}` ({e['date']}, {e['by']}): {e['what']} Excused today: {ex:,} case(s).")
    w("")
    rep = d.get("repetition")
    if rep:
        w("## Repetition (reported, never a finding)")
        w("")
        w("Method: each page's visible text in its main part is cut into pieces (every paragraph, list item, cell, "
          "heading, caption or link with no such element inside it, then split into sentences; whitespace collapsed, "
          "case kept). A piece is **shared** when it appears on at least half of the family's pages read; a page's "
          "**unique share** is the characters of the pieces found on that page alone over all its characters. "
          "Families of three pages or more.")
        w("")
        w("| family | pages | unique share, median | range | shared share, median |")
        w("|---|---|---|---|---|")
        for fam, r in rep.items():
            w(f"| {fam} | {r['pages']:,} | {r['unique_share_median']:.0%} | {r['unique_share_min']:.0%} to "
              f"{r['unique_share_max']:.0%} | {r['shared_share_median']:.0%} |")
        for fam, r in rep.items():
            w("")
            w(f"### {fam}")
            w("Longest shared blocks: " + "; ".join(f"\"{b['text'][:120]}\" ({b['chars']} chars, {b['pages']} pages)"
                                                    for b in r["longest_shared"][:10]))
            w("")
            w("Least own text: " + ", ".join(f"{x['path']} ({x['own_chars']} chars, {x['unique_share']:.0%})"
                                             for x in r["least_own_text"]))
        w("")
    w("## Pages read")
    w("")
    w(f"{len(lv['read']):,} read, {len(lv['not_read']):,} not read ({lv['mode']}; "
      f"{len(lv['pinned'])} pinned, {len(lv['sampled']):,} {'from the sitemap' if lv['mode'] == 'full' else 'sampled'}"
      f", seed `{lv['seed']}`).")
    for x in lv["not_read"]:
        w(f"- NOT READ {SITE}{x['path']}: {x['why']}")
    if lv.get("statuses_not_200"):
        w("")
        w("Answered, not 200 (each is a fact about the site, checked as a link): "
          + ", ".join(f"{p} {s}" for p, s in sorted(lv["statuses_not_200"].items())[:40]) + ".")
    w("")
    w("Pinned, each with its reason:")
    for p, why in lv["pinned"].items():
        w(f"- `{p}`: {why}")
    for n in d["notes"]:
        w("")
        w(f"Note: {n}")
    return "\n".join(L).rstrip() + "\n"


# ── the run ─────────────────────────────────────────────────────────────────────────────────────
def run(snap: Path = SNAP, out: Path = DEFAULT_OUT, day: dt.date | None = None, mode: str | None = None,
        fetch=shared.fetch_page, site: str = SITE, workers: int = WORKERS, pause: float = PAUSE,
        differences_path: Path = DIFFERENCES, sample: int = SAMPLE) -> dict:
    day = day or dt.date.today()
    mode = mode or ("full" if is_full_read(day) else "sample")
    started = time.monotonic()
    truth = Truth(snap)
    rv = Review(truth, load_differences(differences_path))
    meta = {"time": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "commit": shared.etl_commit()}
    sm = read_all(["/sitemap.xml"], fetch, site, 1, 0)["/sitemap.xml"]
    sitemap: list[str] = []
    if sm.get("status") == 200 and sm.get("body"):
        try:
            sitemap = sitemap_paths(sm["body"], site)
        except ET.ParseError as e:
            rv.notes.append(f"The sitemap did not parse ({e}); the sample comes from the snapshot.")
    if not sitemap:
        rv.notes.append("The sitemap could not be read: the sample was drawn from the snapshot's addresses.")
        sitemap = sorted({"/"} | {f"/m/{s}" for s in truth.recs} | {f"/vs/{s}" for s in truth.comparisons}
                         | {f"/whats-in/{s}" for s in truth.products} | {f"/in/{s}" for s in truth.hubs}
                         | {f"/best/{s}" for s in truth.boards})
    pinned = dict(PINNED)
    for p in list(pinned):
        if p.startswith("/m/") and p[3:] not in truth.recs or p.startswith("/embed/") and \
                p[7:-5] not in truth.recs or p.startswith("/vs/") and p[4:] not in truth.comparisons:
            rv.notes.append(f"Pinned {p} is not in the catalogue today; not read.")
            pinned.pop(p)
    if mode == "full":
        chosen = sorted(set(sitemap) - set(pinned))
    else:
        chosen = sample_paths(sitemap, set(pinned), day, sample)
    html_paths = sorted(set(pinned) | set(chosen))
    embeds = sorted({f"/embed/{p[3:]}.json" for p in html_paths if p.startswith("/m/")} - set(html_paths))
    got = read_all(html_paths + embeds, fetch, site, workers, pause)
    got["/sitemap.xml"] = sm
    read, not_read, statuses = [], [], {}
    for p, r in sorted(got.items()):
        if "why" in r:
            not_read.append({"path": p, "why": r["why"]})
        elif r["status"] in (404, 410):
            statuses[p] = r["status"]
            read.append(p)
        elif r["status"] != 200 or not r.get("body"):
            not_read.append({"path": p, "why": f"HTTP {r['status']}"})
        else:
            statuses[p] = 200
            read.append(p)
    sitemap_set = set(sitemap)
    for p, st in statuses.items():
        if st in (404, 410) and p in sitemap_set:
            rv.check("link", "sitemap", "the page it lists", p, "/sitemap.xml", f"links to a page that answers {st}", p)
        elif p in sitemap_set:
            rv.check("link", "sitemap", "the page it lists", p, "/sitemap.xml", None)
    texts: dict[str, dict[str, list[str]]] = defaultdict(dict)
    for p in read:
        r = got[p]
        if statuses.get(p) != 200:
            continue
        try:
            if p.endswith(".json") and p.startswith("/embed/"):
                check_embed(rv, r["body"], p)
            elif p == "/search-index.json":
                check_search_index(rv, r["body"], p)
            elif p.endswith("feed.xml"):
                check_feed(rv, r["body"], p)
            elif p == "/sitemap.xml":
                continue
            else:
                page = page_of(p, r["body"])
                check_page(rv, page, sitemap_set, statuses)
                if mode == "full":
                    texts[page.family][p] = pieces(page.body)
        except Exception as e:                      # noqa: BLE001 (a page it could not take apart is reported)
            rv.notes.append(f"{p} could not be checked: {type(e).__name__}: {e}"[:200])
    rep = repetition(texts) if mode == "full" else None
    live = {"mode": mode, "pinned": pinned, "sampled": chosen, "read": read, "not_read": not_read,
            "seed": f"moleculefinder-facts-{day.isoformat()}", "seconds": time.monotonic() - started,
            "statuses_not_200": {p: s for p, s in statuses.items() if s != 200}}
    out.mkdir(parents=True, exist_ok=True)
    return write_report(out, day, rv, live, meta, rep)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mfetl review facts", description=__doc__.split("\n\n")[0])
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="the reports folder (default: ../trust-reports)")
    p.add_argument("--snapshot", type=Path, default=SNAP, help="the snapshot to read (default: this checkout's)")
    p.add_argument("--date", type=dt.date.fromisoformat, default=None, help="the run's date (default: today)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--full", action="store_true", help="read every sitemap address (the Tuesday read), any day")
    g.add_argument("--sample", action="store_true", help="read the pinned set and the day's sample, even on Tuesday")
    p.add_argument("--site", default=SITE, help="the site to read (default: the live site)")
    a = p.parse_args(argv)
    out = a.out
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"review facts: could not run: the reports folder {out}: {e}", file=sys.stderr)
        return 2
    try:
        data = run(snap=a.snapshot, out=out, day=a.date, site=a.site.rstrip("/"),
                   mode="full" if a.full else "sample" if a.sample else None)
    except Exception as e:                          # noqa: BLE001 (could not run: say why, exit non-zero)
        why = f"{type(e).__name__}: {e}"
        shared.heartbeat(out, "could not run", f"COULD NOT RUN: {why}"[:400], 2, reason=why[:400], name=NAME)
        print(f"review facts: could not run: {why}", file=sys.stderr)
        return 2
    report = str(out / f"{NAME}-{data['date']}.md")
    shared.heartbeat(out, "ran", data["verdict"], 0, report=report, name=NAME)
    print(data["verdict"])
    print(f"report: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
