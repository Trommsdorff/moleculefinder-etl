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
        # The route is now shown per row (`columns`), because until 2026-09 this board
        # claimed oral and ranked whatever route a molecule happened to have. It now
        # only ever ranks an oral value (transform/toxicity.best_oral), and it says so
        # on every row instead of asking the reader to trust the header.
        "columns": ["route", "species"],
        "description": (
            "Ranked by the lowest reported oral LD50, preferring the rat and then the "
            "mouse so the numbers compare like with like. Every row names its route and "
            "species. A molecule measured only by injection is not listed here, because "
            "an injected dose is not a swallowed one. Animal data shown as neutral "
            "science: an estimate, never a threshold to act on."
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
    # ── added 2026-09-05 (build plan phase 3) ────────────────────────────────
    # Three boards over columns the snapshot already carries. No new curation, no new
    # fetch: the data was there and simply had no page.
    "lightest": {
        "title": "Lightest",
        "metric": "molecular_weight",
        "direction": "asc",
        "unit": "g/mol",
        "value_label": "Mol. weight",
        "confidence": "from_source",
        "description": (
            "Ranked by molecular weight, smallest first: the simplest molecules in the "
            "canon, the gases and small acids most of everyday chemistry is built out of."
        ),
    },
    "safest": {
        "title": "Safest",
        "metric": "ld50_mg_per_kg",
        "direction": "desc",   # a HIGHER oral LD50 = a larger dose before harm
        "unit": "mg/kg",
        "value_label": "LD50",
        "confidence": "from_source",
        "columns": ["route", "species"],
        "description": (
            "The Deadliest board read the other way: ranked by the HIGHEST reported oral "
            "LD50, so the molecules that take the largest dose per kilogram of body weight "
            "to do harm come first. Same oral-only rule and the same route and species on "
            "every row. A high LD50 means an animal study found a large dose tolerable, "
            "nothing more: it is not a safety rating and not advice."
        ),
    },
    "most-searched": {
        "title": "Most searched",
        "metric": "pageviews_monthly",
        "direction": "desc",
        "unit": "views/mo",
        "value_label": "Wikipedia views",
        "confidence": "from_source",
        "description": (
            "The most famous molecules in the canon, ranked by average monthly views of "
            "their English Wikipedia article. This measures attention, not importance: it "
            "is an honest popularity board, and the one place on the site where the "
            "ranking says something about people rather than about molecules."
        ),
    },
}


def rank(board: str, molecules: list[dict]) -> dict:
    """Return a self-describing board: its metadata plus ranked, enriched entries."""
    meta = BOARDS[board]
    key, direction = meta["metric"], meta["direction"]
    have = [m for m in molecules if m.get(key) is not None]
    have.sort(key=lambda m: m[key], reverse=(direction == "desc"))
    # Extra per-row columns a board declares (the Deadliest board shows the route and
    # species its value was measured by). Read from `ld50_route` / `ld50_species` and
    # emitted as plain `route` / `species` so the web renders them without a mapping.
    extra = meta.get("columns") or []
    entries = [
        {
            "rank": i + 1,
            "cid": m["cid"],
            "slug": m["slug"],
            "title": m["title"],
            "formula": m.get("molecular_formula"),
            "value_num": m[key],
            **{c: m.get(f"ld50_{c}") for c in extra},
        }
        for i, m in enumerate(have)
    ]
    return {"slug": board, **meta, "entries": entries}
