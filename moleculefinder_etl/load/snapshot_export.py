"""Export the static snapshot the Next.js build consumes (no live DB at build)."""
from __future__ import annotations
import json
from pathlib import Path
from ..config import SNAPSHOTS
from ..transform import roam_layout, relationships


def _prune(directory: Path, keep: set[str]) -> None:
    """Delete stale *.json so the snapshot mirrors the current data set: a dropped
    leaderboard or a removed molecule leaves no orphan file behind for the web build."""
    for f in directory.glob("*.json"):
        if f.name not in keep:
            f.unlink()


def export(molecules: list[dict], leaderboards: dict[str, dict]) -> Path:
    """Write per-molecule JSON + a compact search index + leaderboard files.

    Each leaderboard file is a self-describing board (metadata + enriched
    entries); `leaderboards/index.json` lists the boards for the /best index.
    """
    mol_dir = SNAPSHOTS / "molecules"
    mol_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for m in molecules:
        (mol_dir / f"{m['slug']}.json").write_text(json.dumps(m, ensure_ascii=False))
        # Fold brand names into the index so a search for "Advil" finds ibuprofen (the search
        # ranks over title + synonyms). Brands lead so they aren't truncated by the slice.
        index.append({"slug": m["slug"], "title": m["title"],
                      "formula": m.get("molecular_formula"),
                      "synonyms": ((m.get("brands") or []) + m.get("synonyms", []))[:10]})
    (SNAPSHOTS / "index.json").write_text(json.dumps(index, ensure_ascii=False))
    # Roam constellation: baked node positions for the static /roam map (§5).
    (SNAPSHOTS / "roam.json").write_text(
        json.dumps(roam_layout.build_roam(molecules), ensure_ascii=False))
    # Everyday Worlds: the 10 curated worlds (index + per-world detail) for /roam (spec §4/§5).
    (SNAPSHOTS / "worlds.json").write_text(
        json.dumps(relationships.build_worlds(molecules), ensure_ascii=False))
    _prune(mol_dir, {f"{m['slug']}.json" for m in molecules})
    lb_dir = SNAPSHOTS / "leaderboards"
    lb_dir.mkdir(parents=True, exist_ok=True)
    lb_index = []
    for slug, board in leaderboards.items():
        (lb_dir / f"{slug}.json").write_text(json.dumps(board, ensure_ascii=False))
        entries = board["entries"]
        lb_index.append({
            "slug": slug,
            "title": board["title"],
            "unit": board["unit"],
            "value_label": board["value_label"],
            "description": board["description"],
            "count": len(entries),
            "top": entries[0] if entries else None,
        })
    (lb_dir / "index.json").write_text(json.dumps(lb_index, ensure_ascii=False))
    _prune(lb_dir, {f"{slug}.json" for slug in leaderboards} | {"index.json"})
    return SNAPSHOTS
