"""Type slug → family key (Color System Brief §2b).

A molecule's "family" is its primary kind:"type" membership, collapsed onto the ten
brief families that each own a hue. Several type slugs fold into one family
(nsaid+analgesic → analgesic; steroid+hormone → hormone; nucleoside → nucleobase).
The web mirrors this exact map in `lib/families.ts` (key → CSS var / hex); keep the
two in sync. Terpenes / pure hydrocarbons have no type and get no family (None) —
their all-carbon structure is the signal (brief §2b).
"""
from __future__ import annotations

FAMILY_OF_TYPE: dict[str, str] = {
    "stimulant": "stimulant",
    "depressant": "depressant",
    "analgesic": "analgesic",
    "nsaid": "analgesic",
    "opioid": "opioid",
    "neurotransmitter": "neuro",
    "hormone": "hormone",
    "steroid": "hormone",
    "vitamin": "vitamin",
    "nucleobase": "nucleobase",
    "nucleoside": "nucleobase",
    "amino-acid": "amino",
    "amino_acid": "amino",
}


def family_of(categories: list[dict] | None) -> str | None:
    """Primary family key from a record's categories (first kind:type that maps), else None."""
    for c in categories or []:
        if c.get("kind") == "type":
            fam = FAMILY_OF_TYPE.get((c.get("slug") or "").lower())
            if fam:
                return fam
    return None
