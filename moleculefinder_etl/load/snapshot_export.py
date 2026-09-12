"""Export the static snapshot the Next.js build consumes (no live DB at build)."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from ..config import SNAPSHOTS
from ..transform import roam_layout, relationships
from . import snapshot_guard

# The snapshot's own date, for the "Data refreshed" line on every molecule page (feedback
# triage MF-9, 2026-09-12). One small file beside index.json rather than a field on each
# record, and it moves ONLY when the exported content moves: a date stamped on every run would
# change a committed file every week, and that is the churn run 3 removed (a data PR, a Vercel
# build and a deploy for nothing). A week with no data change leaves it byte-identical.
META = "meta.json"


def _prune(directory: Path, keep: set[str]) -> None:
    """Delete stale *.json so the snapshot mirrors the current data set: a dropped
    leaderboard or a removed molecule leaves no orphan file behind for the web build."""
    for f in directory.glob("*.json"):
        if f.name not in keep:
            f.unlink()


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def _prior_refreshed(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    value = data.get("refreshed") if isinstance(data, dict) else None
    return value if isinstance(value, str) and value else None


def export(molecules: list[dict], leaderboards: dict[str, dict],
           comparisons: dict[str, dict] | None = None, *, today: str | None = None) -> Path:
    """Write per-molecule JSON + a compact search index + leaderboard files + meta.json.

    Each leaderboard file is a self-describing board (metadata + enriched
    entries); `leaderboards/index.json` lists the boards for the /best index.

    ``comparisons`` is compiled by the caller, not here: validating the curated pairs
    needs the whole catalog, and export is a projection of whatever it is handed.

    Nothing is written until ``snapshot_guard`` has compared the records against the
    snapshot already on disk. This is the only place the snapshot is written, so it is the
    only place the check has to be: a run that would walk a summary, an LD50 or a QID
    backwards on the strength of a cache hit stops here with the whole previous snapshot
    still intact, rather than half-overwriting it.

    ``meta.json`` carries ``refreshed``, the UTC date the content last changed. Every output
    is rendered before anything is written so it can be compared with what is on disk: a
    difference in any file, or a file that is about to be pruned, stamps ``today`` (default:
    the current UTC date); otherwise the previous date is kept.
    """
    snapshot_guard.check(molecules, SNAPSHOTS)
    mol_dir = SNAPSHOTS / "molecules"
    lb_dir = SNAPSHOTS / "leaderboards"
    outputs: dict[Path, str] = {}

    index = []
    for m in molecules:
        outputs[mol_dir / f"{m['slug']}.json"] = json.dumps(m, ensure_ascii=False)
        # Fold brand names into the index so a search for "Advil" finds ibuprofen (the search
        # ranks over title + synonyms). Brands lead so they aren't truncated by the slice.
        index.append({"slug": m["slug"], "title": m["title"],
                      "formula": m.get("molecular_formula"),
                      "synonyms": ((m.get("brands") or []) + m.get("synonyms", []))[:10]})
    outputs[SNAPSHOTS / "index.json"] = json.dumps(index, ensure_ascii=False)
    # Roam constellation: baked node positions for the static /roam map (§5).
    outputs[SNAPSHOTS / "roam.json"] = json.dumps(roam_layout.build_roam(molecules), ensure_ascii=False)
    # Everyday Worlds: the 10 curated worlds (index + per-world detail) for /roam (spec §4/§5).
    outputs[SNAPSHOTS / "worlds.json"] = json.dumps(relationships.build_worlds(molecules), ensure_ascii=False)
    # Written comparisons for /vs/<a>-vs-<b> (build plan phase 5). The two records are read
    # straight from the molecule files by the page; only the prose needs curating, so only
    # the prose is exported. Which pairs get a page is the web's lib/compare-pairs.ts.
    outputs[SNAPSHOTS / "comparisons.json"] = json.dumps(comparisons or {}, ensure_ascii=False)

    lb_index = []
    for slug, board in leaderboards.items():
        outputs[lb_dir / f"{slug}.json"] = json.dumps(board, ensure_ascii=False)
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
    outputs[lb_dir / "index.json"] = json.dumps(lb_index, ensure_ascii=False)

    stale = [f for d in (mol_dir, lb_dir) if d.is_dir() for f in d.glob("*.json") if f not in outputs]
    changed = bool(stale) or any(_read_text(path) != text for path, text in outputs.items())
    meta_path = SNAPSHOTS / META
    refreshed = _prior_refreshed(meta_path)
    if changed or refreshed is None:
        refreshed = today or datetime.now(timezone.utc).date().isoformat()
    outputs[meta_path] = json.dumps({"refreshed": refreshed}, ensure_ascii=False)

    mol_dir.mkdir(parents=True, exist_ok=True)
    lb_dir.mkdir(parents=True, exist_ok=True)
    for path, text in outputs.items():
        path.write_text(text)
    _prune(mol_dir, {f"{m['slug']}.json" for m in molecules})
    _prune(lb_dir, {f"{slug}.json" for slug in leaderboards} | {"index.json"})
    return SNAPSHOTS
