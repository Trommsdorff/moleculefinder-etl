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
"""
from __future__ import annotations
import re

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
_NUM = r">?<?~?\s*(?P<value>[\d,]+(?:\.\d+)?)"

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


def parse_ld50(pug_view: dict | None) -> list[dict]:
    """Return toxicity_value rows sorted oral-first, then lowest (deadliest) first.

    Each row: endpoint, species, route (enum), value_num (mg/kg), unit, confidence.
    """
    if not pug_view:
        return []
    seen: set[tuple] = set()
    rows: list[dict] = []
    for text in _iter_strings(pug_view):
        if "LD50" not in text:
            continue
        for rx in (_FORM_A, _FORM_B):
            for m in rx.finditer(text):
                species = _SPECIES[m.group("species").lower()]
                route = _ROUTE[m.group("route").lower()]
                value = _to_mgkg(m.group("value"), m.group("unit"))
                key = (species, route, value)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "endpoint": "LD50", "species": species, "route": route,
                    "value_num": value, "unit": "mg/kg", "confidence": label_for("ld50_raw"),
                })
    # Oral first (the route the dose hook scales), then most-potent first.
    rows.sort(key=lambda r: (r["route"] != "oral", r["value_num"]))
    return rows


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
