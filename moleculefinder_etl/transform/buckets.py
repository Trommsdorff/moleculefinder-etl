"""Scope B buckets — the primary color + roam-cluster dimension for the everyday core.

The 8 everyday-core categories (food, body, plant, nutrient, everyday-chemistry, OTC,
scent, sweetener). Mirrors the web's ``lib/buckets.ts`` — keep the two in sync. The web
owns the hues (``--bucket-*`` CSS tokens); this module owns the labels + roam ring order.
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
}

# Ring order for the roam constellation / legend (mirrors BUCKET_ORDER in lib/buckets.ts).
BUCKET_ORDER: list[str] = [
    "food-flavor", "sweetener", "scent-aroma", "plant-compound",
    "nutrient-vitamin", "body-endogenous", "everyday-chemistry", "otc-medicine",
]


def bucket_label(slug: str | None) -> str | None:
    return BUCKET_LABELS.get(slug) if slug else None
