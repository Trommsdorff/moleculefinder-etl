"""Materialize leaderboards from assembled molecule data.

Each board is self-describing (title, unit, direction, description) and every
entry carries slug/title/formula, so the static site renders names and links
with no cid->slug join at build time (build plan §5, §12 M3). Boards are
materialized by the ETL for determinism; re-running reproduces them exactly.
"""
from __future__ import annotations

# board slug -> display + ranking metadata
BOARDS: dict[str, dict] = {
    "deadliest": {
        "title": "Deadliest",
        "metric": "ld50_mg_per_kg",
        "direction": "asc",  # a lower LD50 = a smaller lethal dose = deadlier
        "unit": "mg/kg",
        "value_label": "LD50",
        "confidence": "from_source",
        "description": (
            "Ranked by the lowest reported oral LD50. The smaller the lethal dose per "
            "kilogram of body weight, the deadlier. Animal data shown as neutral science: "
            "an estimate, never a threshold to act on."
        ),
    },
    "sweetest": {
        "title": "Sweetest",
        "metric": "relative_sweetness",
        "direction": "desc",
        "unit": "× sugar",
        "value_label": "Sweetness",
        "confidence": "from_source",
        "description": "Ranked by sweetness relative to table sugar (sucrose = 1×).",
    },
    "spiciest": {
        "title": "Spiciest",
        "metric": "scoville_shu",
        "direction": "desc",
        "unit": "SHU",
        "value_label": "Scoville",
        "confidence": "from_source",
        "description": (
            "Ranked by Scoville heat units, the pungency of the pure compound: from "
            "resiniferatoxin and the capsaicinoids that make chili peppers burn, down to the "
            "milder bite of ginger and black pepper. Values outside the capsaicinoids are "
            "comparative estimates, since the Scoville scale is defined for capsaicin-like compounds."
        ),
    },
    "pungent": {
        "title": "Most pungent",
        "metric": "odor_threshold",
        "direction": "asc",  # a lower odor threshold = smellable at a tinier amount = stinkier
        "unit": "ng/m3",
        "value_label": "Odor threshold",
        "confidence": "from_source",
        "description": (
            "The stinkiest molecules, ranked by odor detection threshold in air: the tinier the "
            "concentration a person can smell, the higher the rank. Sulfur compounds and the fecal, "
            "fishy, and sweaty notes top the list. Air-panel thresholds (Nagata 2003); values vary "
            "between studies, so these are representative published figures."
        ),
    },
    "biggest": {
        "title": "Biggest",
        "metric": "molecular_weight",
        "direction": "desc",
        "unit": "g/mol",
        "value_label": "Mol. weight",
        "confidence": "from_source",
        "description": "Ranked by molecular weight: the heaviest molecules in the canon.",
    },
}


def rank(board: str, molecules: list[dict]) -> dict:
    """Return a self-describing board: its metadata plus ranked, enriched entries."""
    meta = BOARDS[board]
    key, direction = meta["metric"], meta["direction"]
    have = [m for m in molecules if m.get(key) is not None]
    have.sort(key=lambda m: m[key], reverse=(direction == "desc"))
    entries = [
        {
            "rank": i + 1,
            "cid": m["cid"],
            "slug": m["slug"],
            "title": m["title"],
            "formula": m.get("molecular_formula"),
            "value_num": m[key],
        }
        for i, m in enumerate(have)
    ]
    return {"slug": board, **meta, "entries": entries}
