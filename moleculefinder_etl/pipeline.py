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

from .config import (Settings, SEED_DIR, RAW_CACHE, CURATED_DIR, PUBCHEM_BATCH, SNAPSHOTS,
                     SYNONYMS_CACHE_TTL_DAYS)
from .transform import canon as canon_stage
from .transform import toxicity, ghs, assemble, leaderboards, relationships
from .sources import cache, pubchem
from .load import supabase_loader, snapshot_export
from . import freshness

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
    # Scope B everyday-core build: when scope_b_core.csv is present the canon IS the curated
    # 489 (each stamped with its bucket), not a demand-ranked slice — so the notability net and
    # the --target cap are bypassed. Falls back to the open notability build if the CSV is absent.
    if canon_stage.SCOPE_B_CSV.exists():
        log.info("stage 0: canon = Scope B everyday core (%s)", canon_stage.SCOPE_B_CSV.name)
        rows = canon_stage.build_scope_b_canon()
    else:
        log.info("stage 0: canon selection (target=%d)", settings.canon_target)
        rows = canon_stage.build_canon(settings.canon_target)
    canon_stage.write_parquet(rows)
    marquee = sum(r["tier"] == "marquee" for r in rows)
    hand = sum(bool(r.get("hand_model")) for r in rows)
    log.info("  canon: %d molecules (%d marquee, %d canon, %d hand-model)",
             len(rows), marquee, len(rows) - marquee, hand)
    return rows


# ── Stage 1: fetch ───────────────────────────────────────────────────────────
def _fetch_cached(cids: list[int], prefix: str, fetch_missing,
                  max_age_days: float | None = None) -> dict[int, object]:
    """Per-CID disk cache under raw_cache/pubchem; fetch only the misses in bulk.

    With no ``max_age_days`` an entry is bare JSON and a hit forever: the property cache, since
    a CID's formula is what the CID is. With one, entries are dated and expire through
    ``sources.cache``: the synonym cache since 2026-09-12. An entry written before that has no
    date, which is unknown age and never fresh, so the first run after the change fetches every
    list once.
    """
    cache_dir = RAW_CACHE / "pubchem"
    cache_dir.mkdir(parents=True, exist_ok=True)
    out: dict[int, object] = {}
    missing = []
    for c in cids:
        p = cache_dir / f"{prefix}-{c}.json"
        if max_age_days is None:
            if p.exists():
                out[c] = json.loads(p.read_text())
                continue
        else:
            hit = cache.read_json(p, max_age_days)
            if hit is not None:
                out[c] = hit.value
                continue
        missing.append(c)
    if missing:
        log.info("  %s: %d of %d not cached or expired, fetching", prefix, len(missing), len(cids))
        for i in range(0, len(missing), PUBCHEM_BATCH):
            chunk = missing[i:i + PUBCHEM_BATCH]
            fetched = fetch_missing(chunk)
            for c in chunk:
                val = fetched.get(c)
                p = cache_dir / f"{prefix}-{c}.json"
                if max_age_days is None:
                    p.write_text(json.dumps(val))
                else:
                    cache.write_json(p, val)
                out[c] = val
            log.info("  %s: cached %d/%d", prefix, len(out), len(cids))
    return out


def stage_fetch(settings: Settings) -> None:
    """Pull PubChem properties/synonyms/annotations for the canon (all cached)."""
    _require(SEED_DIR / "canon.parquet", "seed")
    canon = canon_stage.read_parquet()
    # Hand-modeled macromolecules have a synthetic CID and no PubChem compound — skip them.
    cids = [int(r["cid"]) for r in canon if not r.get("hand_model")]
    n_hand = sum(1 for r in canon if r.get("hand_model"))
    log.info("stage 1: fetch — %d CIDs (PubChem properties + synonyms + PUG-View Tox/GHS); "
             "%d hand-modeled molecules skip PubChem", len(cids), n_hand)

    props = _fetch_cached(cids, "props", lambda miss: {int(p["CID"]): p for p in pubchem.properties(miss)})
    # Cache prefix is "syn60", not "syn": the old entries hold a 20-name window and reusing
    # them would keep the starvation the deeper window exists to remove. Renaming the prefix
    # re-fetches once and leaves the stale files to be evicted. The lists expire after
    # SYNONYMS_CACHE_TTL_DAYS, so the weekly run's cache cannot keep an old list forever.
    syns = _fetch_cached(cids, "syn60", lambda miss: pubchem.synonyms(miss), SYNONYMS_CACHE_TTL_DAYS)

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


def _prior_snapshot() -> dict[int, dict]:
    """The last exported snapshot, keyed by CID, for fields that are carried forward.

    Only ``structure_svg`` uses it today (see ``assemble._carried_svg``): RDKit draws ~7% of
    the catalog differently on macOS than on Linux, so re-rendering on whichever machine
    happens to run the pipeline rewrote 53 files a week with no visible change. Reading the
    previous export makes the drawing a stored artifact. An absent or unreadable snapshot is
    not an error: everything simply redraws, which is what a first run does anyway.
    """
    out: dict[int, dict] = {}
    molecules = SNAPSHOTS / "molecules"
    if not molecules.is_dir():
        return out
    for path in sorted(molecules.glob("*.json")):
        try:
            rec = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(rec, dict) and rec.get("cid") is not None:
            out[int(rec["cid"])] = rec
    log.info("  carry-forward: read %d prior record(s) from %s", len(out), molecules)
    return out


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
    seed_by_cid = {m["cid"]: m for m in canon_stage.household_seed()}
    prior_by_cid = _prior_snapshot()

    taken: set[str] = set()
    records: list[dict] = []
    tox_freshness: dict[int, object] = {}
    for row in canon:
        cid = int(row["cid"])
        if row.get("hand_model"):                          # structureless macromolecule variant
            # Meta prefers the hand-authored YAML seed; the canon row (Scope B CSV) backfills
            # it so a hand-model row present only in the CSV still gets its bucket/family.
            meta = seed_by_cid.get(cid) or {
                "name": row.get("enwiki_title"), "bucket": row.get("scope_bucket"),
                "family": row.get("scope_family"), "is_otc": row.get("is_otc"),
                "dual_use": row.get("dual_use"),
            }
            records.append(assemble.assemble_handmodel(row, meta, taken))
            continue
        f = fetched_by_cid.get(cid, {})
        # Dated: the LD50 the export guard protects is parsed out of this annotation, so
        # the guard has to know whether the annotation came off the network or off the disk.
        tox_entry = pubchem.pug_view_dated(cid, "Toxicity")
        tox_freshness[cid] = tox_entry
        fetched = {
            "props": f.get("props") or {},
            "synonyms": f.get("synonyms") or [],
            "curated": curated_by_cid.get(cid),
            "toxicity": toxicity.parse_ld50(tox_entry.value),
            "ghs": ghs.parse_ghs(pubchem.pug_view(cid, "GHS Classification")),
        }
        rec = assemble.assemble_record(row, fetched, taken, prior=prior_by_cid.get(cid))
        seed = seed_by_cid.get(cid)                         # carry Scope B bucket onto add-core seeds
        if seed:
            assemble.apply_scope_bucket(rec, seed.get("bucket"), seed.get("family"))
        records.append(rec)

    assemble.attach_edges(records)
    kept, deferred = assemble.apply_filter4(records)

    # Everyday Worlds + Trails (spec §2): attach each molecule's curated found_in/affects/
    # becomes edges. Validates every world + relationship slug against the kept set and
    # fails the build on a dangling reference. resembles = the computed `edges` above.
    relationships.attach_trails(kept)
    # Curated plain-language "why it matters" (follow-up #1): shown in the world SELECTED panel
    # instead of PubChem's generic description. Fails the build on an unknown curated slug.
    relationships.attach_why_it_matters(kept)
    # Curated commercial/brand names (Advil, Benadryl...) for the "Also sold as" line + search.
    relationships.attach_brands(kept)
    # Odor detection thresholds for the "Most pungent" (stinkiest) leaderboard.
    relationships.attach_odor_thresholds(kept)
    # kind:"use" hubs from the hand-maintained OTC allowlist (what a medicine is taken
    # FOR), the one grouping a person browsing a pharmacy shelf actually thinks in.
    relationships.attach_otc_uses(kept)
    # Curated food-hub membership, so /in/coffee is a real page and not one molecule.
    relationships.attach_food_hubs(kept)
    # Curated non-food sources (phase 6): the household cleaner, the first aid kit, the
    # pharmacy shelf. "Where you will find it" promised foods OR products from the start
    # and only ever had the foods.
    relationships.attach_product_hubs(kept)
    # Element / GHS-hazard / size-band hubs, then prune every derived hub too thin to be
    # a page. Both run after all the curated overlays, so the prune counts the real
    # membership and never drops a curated hub.
    assemble.attach_derived_categories(kept)
    assemble.unify_category_kinds(kept)
    assemble.prune_thin_categories(kept)
    # The page description (phase 1). LAST of the attach passes on purpose: it composes
    # from the curated why_it_matters line, the foods, the odor threshold and everything
    # assembled above, so it has to see all of them. Raises on a duplicate or a
    # sub-100-character description rather than shipping one.
    assemble.attach_descriptions(kept)
    # The title's parenthetical: the Wikidata label where it differs from the title, else a
    # name on the synonym line that the description itself uses. After the description.
    assemble.attach_title_synonyms(kept, {int(r["cid"]): r.get("wikidata_label") for r in canon})

    # Hand the PUG-View fetch dates to the export guard. Written here rather than carried
    # on the records: a per-record timestamp would move every run and put all 788 molecule
    # files into every weekly diff, which is the churn run 3 existed to remove.
    freshness.merge({freshness.TOXICITY: freshness.from_entries(tox_freshness)})

    MOLECULES.write_text(json.dumps(kept, ensure_ascii=False))
    DEFERRED.write_text(json.dumps([{"cid": r["cid"], "slug": r["slug"], "title": r["title"]} for r in deferred],
                                   ensure_ascii=False))
    edges = sum(len(r["edges"]) for r in kept)
    hooks = sum(len(r["hooks"]) for r in kept)
    trails = sum(len(r["trails"]["affects"]) + len(r["trails"]["becomes"]) + len(r["trails"]["found_in"])
                 for r in kept)
    log.info("  assembled %d molecules (%d edges, %d hooks, %d trail edges); filter-4 demoted %d orphan(s)",
             len(kept), edges, hooks, trails, len(deferred))
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
    # Compiled here, against the whole catalog, so a curated pair naming a molecule that is
    # not in it fails the run instead of quietly exporting one fewer page.
    comparisons = relationships.build_comparisons(molecules)
    path = snapshot_export.export(molecules, boards, comparisons)
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
