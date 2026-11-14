"""Materialize leaderboards from assembled molecule data.

Each board is self-describing (title, unit, direction, description) and every
entry carries slug/title/formula, so the static site renders names and links
with no cid->slug join at build time (build plan §5, §12 M3). Boards are
materialized by the ETL for determinism; re-running reproduces them exactly.
"""
from __future__ import annotations

# board slug -> display + ranking metadata
BOARDS: dict[str, dict] = {
    # The Deadliest and Safest boards were removed in phase 10 of the everyday chemistry plan
    # (Garrett's rulings, 2026-11-09: no safest or deadliest rankings); their addresses answer 410
    # (web lib/gone.ts). Every LD50 stays on its molecule's page, with species, route and form.
    "sweetest": {
        "title": "Sweetest",
        "metric": "relative_sweetness",
        "direction": "desc",
        "unit": "× sugar",
        "value_label": "Sweetness",
        "confidence": "from_source",
        # SEO run 1 (2026-10-28): the board answers "sweetest molecule" first. rank() puts the
        # leader's sentence (LEADS) before this text, so the answer moves with the data.
        "description": "Table sugar is 1, and every value names its source.",
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


# Boards whose every entry names the source of its value, read from this record field.
SOURCE_FIELDS = {"sweetest": "relative_sweetness_source"}

# Boards whose description opens with the answer a searcher asked for, built from the leader.
# "Estimated": a sweetness is a tasting panel's figure, and the leader's source says "estimated".
LEADS = {"sweetest": "{title} is the sweetest molecule in MoleculeFinder, an estimated {value} times sweeter than sugar."}


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,}"


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
            # The registry key of the source that reports the value (SEO run 1: every Sweetest
            # entry names one). Kept out of BOARDS for the same reason as ORAL_ONLY.
            **({"source": m.get(SOURCE_FIELDS[board])} if board in SOURCE_FIELDS else {}),
        }
        for i, m in enumerate(have)
    ]
    out = {"slug": board, **meta, "entries": entries}
    if board in LEADS and entries:
        lead = LEADS[board].format(title=entries[0]["title"], value=_fmt(entries[0]["value_num"]))
        out["description"] = f"{lead} {meta['description']}"
    return out
