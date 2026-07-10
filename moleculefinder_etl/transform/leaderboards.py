"""Materialize leaderboards from assembled molecule data."""
from __future__ import annotations

BOARDS = {
    "deadliest":       ("ld50_mg_per_kg", "asc"),   # lower LD50 = deadlier
    "sweetest":        ("relative_sweetness", "desc"),
    "hottest":         ("scoville_shu", "desc"),
    "most-caffeinated": ("caffeine_mg", "desc"),
    "biggest":         ("molecular_weight", "desc"),
}


def rank(board: str, molecules: list[dict]) -> list[dict]:
    key, direction = BOARDS[board]
    have = [m for m in molecules if m.get(key) is not None]
    have.sort(key=lambda m: m[key], reverse=(direction == "desc"))
    return [{"molecule_cid": m["cid"], "rank": i + 1, "value_num": m[key]}
            for i, m in enumerate(have)]
