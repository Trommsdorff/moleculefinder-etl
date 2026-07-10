"""Orchestrates the five ETL stages. Each is idempotent and resumable.

Stages hand off through files under ``data/seed`` so any stage can run alone and
a failed run resumes cheaply:

    seed      → data/seed/canon.parquet          (canon rows, ranked)
    fetch     → data/seed/fetched.json           (PubChem props + synonyms per CID;
                                                   PUG-View Tox/GHS warmed into raw_cache)
    transform → data/seed/molecules.json         (assembled records, filter-4 applied)
                data/seed/deferred.json          (orphans demoted by filter-4)
    load      → Supabase (idempotent upserts; skipped if creds absent)
    export    → data/snapshots/                  (per-molecule JSON + index + boards)
"""
from __future__ import annotations
import json
import logging
from pathlib import Path

from .config import Settings, SEED_DIR, RAW_CACHE, CURATED_DIR
from .transform import canon as canon_stage
from .transform import toxicity, ghs, assemble, leaderboards
from .sources import pubchem
from .load import supabase_loader, snapshot_export

import yaml

log = logging.getLogger("mfetl")

FETCHED = SEED_DIR / "fetched.json"
MOLECULES = SEED_DIR / "molecules.json"
DEFERRED = SEED_DIR / "deferred.json"


def _require(path: Path, prior: str) -> None:
    if not path.exists():
        raise SystemExit(f"missing {path.name}; run `mfetl {prior}` first")


def _load_curated() -> dict[int, dict]:
    out: dict[int, dict] = {}
    for path in sorted(CURATED_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text()) or {}
        if data.get("cid"):
            out[int(data["cid"])] = data
    return out


# ── Stage 0: canon ───────────────────────────────────────────────────────────
def stage_seed(settings: Settings) -> list[dict]:
    log.info("stage 0: canon selection (target=%d)", settings.canon_target)
    rows = canon_stage.build_canon(settings.canon_target)
    canon_stage.write_parquet(rows)
    marquee = sum(r["tier"] == "marquee" for r in rows)
    log.info("  canon: %d molecules (%d marquee, %d canon)", len(rows), marquee, len(rows) - marquee)
    return rows


# ── Stage 1: fetch ───────────────────────────────────────────────────────────
def _fetch_cached(cids: list[int], prefix: str, fetch_missing) -> dict[int, object]:
    """Per-CID disk cache under raw_cache/pubchem; fetch only the misses in bulk."""
    cache_dir = RAW_CACHE / "pubchem"
    cache_dir.mkdir(parents=True, exist_ok=True)
    out: dict[int, object] = {}
    missing = []
    for c in cids:
        p = cache_dir / f"{prefix}-{c}.json"
        if p.exists():
            out[c] = json.loads(p.read_text())
        else:
            missing.append(c)
    if missing:
        fetched = fetch_missing(missing)
        for c in missing:
            val = fetched.get(c)
            (cache_dir / f"{prefix}-{c}.json").write_text(json.dumps(val))
            out[c] = val
    return out


def stage_fetch(settings: Settings) -> None:
    """Pull PubChem properties/synonyms/annotations for the canon (all cached)."""
    _require(SEED_DIR / "canon.parquet", "seed")
    canon = canon_stage.read_parquet()
    cids = [int(r["cid"]) for r in canon]
    log.info("stage 1: fetch — %d CIDs (PubChem properties + synonyms + PUG-View Tox/GHS)", len(cids))

    props = _fetch_cached(cids, "props", lambda miss: {int(p["CID"]): p for p in pubchem.properties(miss)})
    syns = _fetch_cached(cids, "syn", lambda miss: pubchem.synonyms(miss))

    # Warm the PUG-View caches (Toxicity + GHS) so transform parses offline.
    tox_hits = ghs_hits = 0
    for i, cid in enumerate(cids, 1):
        if pubchem.pug_view(cid, "Toxicity"):
            tox_hits += 1
        if pubchem.pug_view(cid, "GHS Classification"):
            ghs_hits += 1
        if i % 25 == 0:
            log.info("  annotations: %d/%d CIDs", i, len(cids))

    FETCHED.parent.mkdir(parents=True, exist_ok=True)
    FETCHED.write_text(json.dumps([{"cid": c, "props": props.get(c) or {}, "synonyms": syns.get(c) or []}
                                   for c in cids]))
    log.info("  fetched %d CIDs (%d with toxicity, %d with GHS) -> %s", len(cids), tox_hits, ghs_hits, FETCHED.name)


# ── Stage 2: transform ───────────────────────────────────────────────────────
def stage_transform(settings: Settings) -> list[dict]:
    _require(SEED_DIR / "canon.parquet", "seed")
    _require(FETCHED, "fetch")
    from rdkit import RDLogger
    RDLogger.DisableLog("rdApp.*")           # silence per-molecule SMILES parse noise

    log.info("stage 2: transform (names, fingerprints, similarity, tox, hooks)")
    canon = canon_stage.read_parquet()
    fetched_by_cid = {f["cid"]: f for f in json.loads(FETCHED.read_text())}
    curated_by_cid = _load_curated()

    taken: set[str] = set()
    records: list[dict] = []
    for row in canon:
        cid = int(row["cid"])
        f = fetched_by_cid.get(cid, {})
        fetched = {
            "props": f.get("props") or {},
            "synonyms": f.get("synonyms") or [],
            "curated": curated_by_cid.get(cid),
            "toxicity": toxicity.parse_ld50(pubchem.pug_view(cid, "Toxicity")),
            "ghs": ghs.parse_ghs(pubchem.pug_view(cid, "GHS Classification")),
        }
        records.append(assemble.assemble_record(row, fetched, taken))

    assemble.attach_edges(records)
    kept, deferred = assemble.apply_filter4(records)

    MOLECULES.write_text(json.dumps(kept, ensure_ascii=False))
    DEFERRED.write_text(json.dumps([{"cid": r["cid"], "slug": r["slug"], "title": r["title"]} for r in deferred],
                                   ensure_ascii=False))
    edges = sum(len(r["edges"]) for r in kept)
    hooks = sum(len(r["hooks"]) for r in kept)
    log.info("  assembled %d molecules (%d edges, %d hooks); filter-4 demoted %d orphan(s)",
             len(kept), edges, hooks, len(deferred))
    return kept


# ── Stage 3: load ────────────────────────────────────────────────────────────
def stage_load(settings: Settings) -> None:
    _require(MOLECULES, "transform")
    molecules = json.loads(MOLECULES.read_text())
    if not settings.has_supabase:
        log.info("stage 3: load — SUPABASE_URL/SERVICE_KEY not set; skipping DB upserts "
                 "(the static snapshot in stage 4 does not need a DB). %d molecules staged.", len(molecules))
        return
    log.info("stage 3: load (idempotent upserts + ingest_run) — %d molecules", len(molecules))
    client = supabase_loader.get_client(settings)
    try:
        counts = supabase_loader.load_all(client, molecules)
        supabase_loader.record_run(client, "load", "ok", sum(counts.values()), notes=json.dumps(counts))
        log.info("  loaded: %s", counts)
    except Exception as e:                      # record the failure, then re-raise
        try:
            supabase_loader.record_run(client, "load", "failed", 0, notes=str(e)[:500])
        except Exception:
            pass
        raise


# ── Stage 4: export ──────────────────────────────────────────────────────────
def stage_export(settings: Settings) -> Path:
    _require(MOLECULES, "transform")
    molecules = json.loads(MOLECULES.read_text())
    boards = {slug: leaderboards.rank(slug, molecules) for slug in leaderboards.BOARDS}
    path = snapshot_export.export(molecules, boards)
    non_empty = {k: len(v["entries"]) for k, v in boards.items() if v["entries"]}
    log.info("stage 4: export — %d molecules + %d leaderboards -> %s", len(molecules), len(non_empty), path)
    log.info("  boards: %s", non_empty)
    return path


def run_all(settings: Settings) -> None:
    stage_seed(settings)
    stage_fetch(settings)
    stage_transform(settings)
    stage_load(settings)
    stage_export(settings)
