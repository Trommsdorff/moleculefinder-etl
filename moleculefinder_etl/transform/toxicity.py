"""Parse LD50 rows out of a PubChem PUG-View 'Toxicity' record.

LD50 values live under *Toxicological Information → Non-Human Toxicity Values*,
in two shapes this parser handles:

    "LD50 Rat oral 192 mg/kg"                 # HSDB canonical: LD50 species route value
    "LD50: 127 mg/kg (Oral, Mouse) (A308)"    # DrugBank style: LD50: value (route, species)

We only accept a row when it names a *known* species and route and a body-weight
unit (mg/kg, g/kg, ug/kg) — the inputs the dose-makes-the-poison hook needs to
scale a dose to a reader's weight. Prose mentions ("the LD50 for humans is
estimated at 150-200 mg/kg") are skipped on purpose: constraining species and
route to fixed vocabularies is what stops junk like species="for"/"values" from
leaking in. Everything is normalized into mg/kg and labeled via `confidence.py`.

A LIMIT IS NOT A VALUE (Garrett's ruling, 2026-11-15, the 2026-12-care tranche). Where a source
reports "LD50 Rat oral > 10,000 mg/kg" (no animal died at the highest amount tested), the figure is
a lower bound. Until 2026-11-15 this parser read the ">" and threw it away, so 27 live pages showed
the bound as if it were the LD50. A row now keeps the qualifier its source gives, as `qualifier`
(QUALIFIERS below: ">" greater than, "<" less than, "~" about); a row without the key is a plain
value. The qualifier is part of the value: two rows that differ only in it are two rows, and the
record's own LD50 carries it as `ld50_qualifier` (assemble._apply_primary_ld50). The parser reads
no other shape than before: a range ("3000-4000 mg/kg"), "more than"/"greater than" in words,
"+/-" and "> or =" are still skipped whole, so no value reaches the site from them.
"""
from __future__ import annotations
import re

from ..sources import registry
from .confidence import label_for

# Known laboratory species -> normalized name. Membership in this set is the
# guard that keeps prose words from being read as a species.
_SPECIES = {
    "rat": "rat", "rats": "rat",
    "mouse": "mouse", "mice": "mouse", "mus": "mouse",
    "rabbit": "rabbit", "rabbits": "rabbit",
    "guinea pig": "guinea pig", "guinea-pig": "guinea pig",
    "dog": "dog", "dogs": "dog", "cat": "cat", "cats": "cat",
    "monkey": "monkey", "hamster": "hamster", "gerbil": "gerbil",
    "pigeon": "pigeon", "chicken": "chicken", "chick": "chicken",
    "frog": "frog", "mammal": "mammal", "bird": "bird", "pig": "pig",
    "cattle": "cattle", "cow": "cattle", "sheep": "sheep", "horse": "horse",
    "quail": "quail", "duck": "duck", "guinea": "guinea pig",
    "human": "human", "women": "human", "woman": "human", "men": "human", "man": "human",
}
# Route synonyms -> the `tox_route` enum {oral, dermal, inhalation, iv, other}.
_ROUTE = {
    "oral": "oral", "po": "oral", "ingestion": "oral", "intragastric": "oral",
    "dermal": "dermal", "skin": "dermal", "percutaneous": "dermal", "topical": "dermal",
    "inhalation": "inhalation", "ihl": "inhalation", "respiratory": "inhalation",
    "iv": "iv", "intravenous": "iv",
    # everything below has no dedicated enum value, so it collapses to 'other'
    "ip": "other", "intraperitoneal": "other",
    "sc": "other", "subcutaneous": "other",
    "im": "other", "intramuscular": "other",
    "rectal": "other", "parenteral": "other", "ocular": "other", "ophthalmic": "other",
    "unknown": "other", "unreported": "other",
}
# unit (lowercased) -> multiplier into mg/kg
_UNIT_TO_MGKG = {"mg/kg": 1.0, "g/kg": 1000.0, "ug/kg": 0.001, "µg/kg": 0.001, "mcg/kg": 0.001}

# Longest-first alternations so "guinea pig" wins over "pig", "intravenous" over "iv".
_SPECIES_RE = "|".join(sorted((re.escape(k) for k in _SPECIES), key=len, reverse=True))
_ROUTE_RE = "|".join(sorted((re.escape(k) for k in _ROUTE), key=len, reverse=True))
_UNIT_RE = "|".join(sorted((re.escape(u) for u in _UNIT_TO_MGKG), key=len, reverse=True))
_NUM = r"(?P<qual>[<>~])?\s*(?P<value>[\d,]+(?:\.\d+)?)"

# The qualifiers a row may carry, and the plain words every surface prints them in. Absent = a value.
QUALIFIERS = {">": "more than", "<": "less than", "~": "about"}

# "LD50 Rat oral 192 mg/kg"
_FORM_A = re.compile(
    rf"LD50\s+(?P<species>{_SPECIES_RE})\s+(?P<route>{_ROUTE_RE})\s+{_NUM}\s*(?P<unit>{_UNIT_RE})",
    re.I,
)
# "LD50: 127 mg/kg (Oral, Mouse)"
_FORM_B = re.compile(
    rf"LD50:?\s+{_NUM}\s*(?P<unit>{_UNIT_RE})\s*\(\s*(?P<route>{_ROUTE_RE})\s*,\s*(?P<species>{_SPECIES_RE})\s*\)",
    re.I,
)


def _to_mgkg(value: str, unit: str) -> float:
    return round(float(value.replace(",", "")) * _UNIT_TO_MGKG[unit.lower()], 4)


def parse_ld50(pug_view: dict | None, *, withheld: list | None = None, gate: bool = True) -> list[dict]:
    """Return toxicity_value rows sorted oral-first, then lowest (deadliest) first.

    Each row: endpoint, species, route (enum), value_num (mg/kg), unit, confidence, and
    `sources`: the registry keys of every source whose own text reports that row.

    THE SOURCE-LICENCE RULE (2026-10-23): each PUG-View Information item names its reference,
    and an item counts only when that reference is a registered source that may be displayed
    (`registry.may_display`). A row no displayable source reports is not returned at all; a row
    that two sources report keeps only the displayable ones. An unregistered source counts as
    not displayable. When `withheld` is a list, each (species, route, value, source name) a
    non-displayable source alone reported is appended to it, for the run log.

    `gate=False` is for tracing only (the dataset's `ld50_sources`): every source counts, and
    `sources` holds the registry key, or the raw SourceName when it is not registered.
    """
    if not pug_view:
        return []
    rec = pug_view.get("Record", pug_view)
    names = {r.get("ReferenceNumber"): r.get("SourceName") for r in rec.get("Reference", []) or []}
    by_key: dict[tuple, dict] = {}
    refused: dict[tuple, set] = {}
    for info in _iter_information(rec):
        source_name = names.get(info.get("ReferenceNumber"))
        key_src = registry.pugview_key(source_name)
        ok = registry.may_display(key_src)
        if not gate:
            ok, key_src = True, key_src or source_name or "(no source named)"
        for text in _iter_strings(info):
            if "LD50" not in text:
                continue
            for rx in (_FORM_A, _FORM_B):
                for m in rx.finditer(text):
                    species = _SPECIES[m.group("species").lower()]
                    route = _ROUTE[m.group("route").lower()]
                    value = _to_mgkg(m.group("value"), m.group("unit"))
                    qual = m.group("qual")
                    key = (species, route, value, qual)
                    if not ok:
                        refused.setdefault(key, set()).add(source_name or "(no source named)")
                        continue
                    row = by_key.get(key)
                    if row is None:
                        row = by_key[key] = {
                            "endpoint": "LD50", "species": species, "route": route,
                            "value_num": value, "unit": "mg/kg", "confidence": label_for("ld50_raw"),
                            "sources": [],
                        }
                        if qual:
                            row["qualifier"] = qual
                    if key_src not in row["sources"]:
                        row["sources"].append(key_src)
    rows = list(by_key.values())
    for row in rows:
        row["sources"].sort()
    if withheld is not None:
        for key in sorted((k for k in refused if k not in by_key), key=lambda k: (*k[:3], k[3] or "")):
            item = {"species": key[0], "route": key[1], "value_num": key[2], "sources": sorted(refused[key])}
            if key[3]:
                item["qualifier"] = key[3]
            withheld.append(item)
    # Oral first (the route the dose hook scales), then most-potent first.
    rows.sort(key=lambda r: (r["route"] != "oral", r["value_num"]))
    return rows


def _iter_information(node):
    """Yield every Information item in a PUG-View tree (each names its ReferenceNumber)."""
    if isinstance(node, dict):
        for info in node.get("Information", []) or []:
            if isinstance(info, dict):
                yield info
        for k, v in node.items():
            if k != "Information":
                yield from _iter_information(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_information(v)


def _iter_strings(node):
    """Yield every 'String' leaf in a PUG-View JSON tree."""
    if isinstance(node, dict):
        if "String" in node and isinstance(node["String"], str):
            yield node["String"]
        for v in node.values():
            yield from _iter_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_strings(v)


# ── Choosing the one row a board or a dose lens should use ───────────────────
# The Deadliest board says it ranks "the lowest reported oral LD50", and until
# 2026-09 it did not. `assemble_record` took `toxicity[0]`, and `parse_ld50` sorts
# oral-first only among the rows a molecule happens to have: a molecule with NO oral
# row contributed its intravenous or intraperitoneal value instead. 25 of the 162
# molecules with toxicity data were ranked that way, which is how stearic acid
# reached rank 3 on an IV rat value of 21.5 mg/kg and palmitic acid rank 10 on an IV
# mouse value of 57. Both are ordinary dietary fats; eaten, neither is remotely that
# toxic. The board is the second most-visited page on the site.
#
# `best_oral` returns the whole row, so the route and species travel with the number
# and can be displayed beside it. It is the oral half of `primary_ld50` below, the one
# LD50 every surface reads.
ORAL_FLOOR_MG_PER_KG = 1.0

# Slugs allowed below that floor. A sub-1 mg/kg ORAL LD50 is real for a handful of
# genuinely potent toxins and is otherwise a parsing artifact or a units error, so
# it has to be named rather than inferred. Nothing in the current 498 qualifies (the
# only sub-floor oral row is oxymetazoline at 0.8 mg/kg, against published rat oral
# figures an order of magnitude higher); the list is here for the drugs-wing
# tranches, which do contain compounds that belong under it.
POTENT_TOXIN_SLUGS = frozenset({
    "botulinum-toxin", "tetrodotoxin", "batrachotoxin", "ricin", "abrin",
    "aflatoxin-b1", "tcdd", "aconitine", "strychnine", "digoxin", "colchicine",
    "fentanyl", "carfentanil", "vx", "sarin",
})

# Preference order among oral rows. Rat first because it is the standard reference
# species most published oral LD50 values use, so ranking on it compares like with
# like; mouse next; any other species last.
_ORAL_SPECIES_RANK = {"rat": 0, "mouse": 1}


def best_oral(rows: list[dict] | None, slug: str | None = None) -> dict | None:
    """The LD50 row to rank and display: oral rat, else oral mouse, else oral any.

    Lowest (deadliest) value within the preferred species tier. Non-oral rows are
    never returned: a board that says oral must mean it. Implausible sub-floor values
    are dropped unless the molecule is a named potent toxin. Returns None when the
    molecule has no usable oral row, which correctly removes it from the board rather
    than ranking it on a route it was not measured by.
    """
    oral = [r for r in (rows or [])
            if r.get("route") == "oral" and isinstance(r.get("value_num"), (int, float))]
    if slug not in POTENT_TOXIN_SLUGS:
        oral = [r for r in oral if r["value_num"] >= ORAL_FLOOR_MG_PER_KG]
    if not oral:
        return None
    # A plain value before a limit at the same figure (no molecule has both today).
    oral.sort(key=lambda r: (_ORAL_SPECIES_RANK.get(r.get("species"), 2), r["value_num"], bool(r.get("qualifier"))))
    return oral[0]


# ── The one LD50 a molecule shows (Garrett, 2026-09-12) ──────────────────────
# `best_oral` fixed what the boards and the dose lens read, but not the Safety panel, which
# kept leading with `toxicity[0]`: the parser's first row, the lowest oral value in ANY
# species. So 53 molecules printed one LD50 on their own page and another on the Deadliest and
# Safest boards, in the /vs tables and, on 11 of them, in the dose lens right above the panel.
# Acetaminophen's panel read 338 mg/kg in the mouse; its comparison tables read 1,944 in the
# rat. `primary_ld50` is the one choice: `assemble._apply_primary_ld50` stamps it on the record
# and leads the toxicity list with it, and every reader takes that row.
def primary_ld50(rows: list[dict] | None, slug: str | None = None) -> dict | None:
    """The molecule's one LD50: oral rat, then oral mouse, then any oral, then any other route.

    The oral tiers are `best_oral` (the lowest value in the first tier that has one). With no
    usable oral row it is the lowest value reported by any other route, so a molecule measured
    only by injection still shows one number, and its route says so. The whole row comes back,
    species and route with it.

    A sub-floor oral value is dropped, not demoted: it is a parsing artifact or a units error,
    and falling through to "any other route" must not bring it back. A value by another route
    has no floor, because an injected dose under 1 mg/kg is ordinary for a potent drug. Ties
    break on route and then species, so the choice never follows the order PubChem happens to
    list its strings in. Only mg/kg values compete.
    """
    rows = [r for r in (rows or []) if (r.get("unit") or "mg/kg") == "mg/kg"]
    oral = best_oral(rows, slug)
    if oral:
        return oral
    other = [r for r in rows
             if r.get("route") != "oral" and isinstance(r.get("value_num"), (int, float))]
    if not other:
        return None
    return min(other, key=lambda r: (r["value_num"], r.get("route") or "", r.get("species") or "",
                                     bool(r.get("qualifier"))))


def row_key(r: dict) -> tuple:
    """A toxicity row's identity: species, route, value and qualifier (a limit is not the value)."""
    return (r.get("species"), r.get("route"), r.get("value_num"), r.get("qualifier"))


def words(qualifier: str | None) -> str:
    """'more than ' for '>', '' for a plain value: the words a sentence puts before the figure."""
    return f"{QUALIFIERS[qualifier]} " if qualifier else ""


