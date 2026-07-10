"""Export the static snapshot the Next.js build consumes (no live DB at build)."""
from __future__ import annotations
import json
from pathlib import Path
from ..config import SNAPSHOTS


def export(molecules: list[dict], leaderboards: dict[str, list[dict]]) -> Path:
    """Write per-molecule JSON + a compact search index + leaderboard files."""
    mol_dir = SNAPSHOTS / "molecules"
    mol_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for m in molecules:
        (mol_dir / f"{m['slug']}.json").write_text(json.dumps(m, ensure_ascii=False))
        index.append({"slug": m["slug"], "title": m["title"],
                      "formula": m.get("molecular_formula"),
                      "synonyms": m.get("synonyms", [])[:8]})
    (SNAPSHOTS / "index.json").write_text(json.dumps(index, ensure_ascii=False))
    lb_dir = SNAPSHOTS / "leaderboards"
    lb_dir.mkdir(parents=True, exist_ok=True)
    for slug, rows in leaderboards.items():
        (lb_dir / f"{slug}.json").write_text(json.dumps(rows, ensure_ascii=False))
    return SNAPSHOTS
