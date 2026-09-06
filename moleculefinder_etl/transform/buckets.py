"""Scope B buckets — the primary color + roam-cluster dimension for the everyday core.

The 8 everyday-core categories (food, body, plant, nutrient, everyday-chemistry, OTC,
scent, sweetener), plus the two added with the first catalog-growth tranche
(prescription-medicine, element-material). Mirrors the web's ``lib/buckets.ts`` — keep
the two in sync. The web owns the hues (``--bucket-*`` CSS tokens); this module owns
the labels + roam ring order.

The two 2026-09 additions exist because tranche 1 doubles the catalog with molecules the
original eight cannot hold honestly. 184 prescription medicines cannot go in
``otc-medicine``: the OTC line is hand-decided per ``otc_allowlist.yaml`` and is the one
classification this project refuses to guess. 70 pure elements and 8 engineered materials
cannot go in ``everyday-chemistry`` either: that bucket has 17 members and would become a
list of the periodic table wearing a household label.
"""
from __future__ import annotations

BUCKET_LABELS: dict[str, str] = {
    "body-endogenous": "Body",
    "food-flavor": "Food & flavor",
    "nutrient-vitamin": "Nutrient",
    "plant-compound": "Plant",
    "everyday-chemistry": "Everyday chemistry",
    "otc-medicine": "OTC medicine",
    "scent-aroma": "Scent & aroma",
    "sweetener": "Sweetener",
    # Added with catalog tranche 2026-09-A.
    "prescription-medicine": "Prescription medicine",
    "element-material": "Element & material",
}

# Ring order for the roam constellation / legend (mirrors BUCKET_ORDER in lib/buckets.ts).
BUCKET_ORDER: list[str] = [
    "food-flavor", "sweetener", "scent-aroma", "plant-compound",
    "nutrient-vitamin", "body-endogenous", "everyday-chemistry", "element-material",
    "otc-medicine", "prescription-medicine",
]


def bucket_label(slug: str | None) -> str | None:
    return BUCKET_LABELS.get(slug) if slug else None
