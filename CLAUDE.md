# CLAUDE.md — moleculefinder-etl

Public ETL for MoleculeFinder. Pulls PubChem + Wikidata (+ Wikipedia pageviews),
transforms, and loads **Supabase + a static JSON snapshot** the web app builds from.
Full design: `../MoleculeFinder_Technical_Build_Plan.md` (sections 4–7).

## Golden rules (do not break these)
1. **License firewall.** Never ingest a BLOCKED source (DrugBank, HMDB, FooDB,
   FlavorDB, Leffingwell, ChEMBL). Route every source attach through
   `sources/registry.py::assert_not_blocked()`. Foods/smell come from hand-curated
   YAML, never FooDB.
2. **Label everything.** Every stored value gets a confidence via
   `transform/confidence.py` — `from_source` / `computed` / `inferred`. No exceptions.
3. **Descriptions are CC0 only.** Wikidata `schema:description`, never Wikipedia prose.
4. **Respect PubChem limits.** ≤5 req/s, ≤400/min. Use `sources/pubchem.py` (it
   throttles + caches). Cache raw responses so runs are resumable.
5. **Idempotent loads.** Upsert by natural key (`ON CONFLICT`); one `ingest_run`
   row per stage.

## Commands
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
mfetl seed --target 200      # small canon for a fast smoke test (scale to 10000 later)
mfetl all
pytest                       # offline tests must stay green
ruff check .
```

## Status: LIVE = 125-molecule snapshot; the 125 -> 489 Scope B rebuild is BUILT + committed LOCAL, held for push
> Steps 1-4 DONE (commits `0ad32db` + `76a05b8`); nothing pushed, live site still serves 125.
> See `../scope-b-rebuild-STATUS.md` for the full state + the "To ship" checklist.

### Shipped + live (2026-07-10): M1 + M3-leaderboards + curation (batches 1 & 2)
`pipeline.py`'s five stages flow fetch → transform → load → export; `transform/assemble.py`
builds the per-molecule record. `mfetl all --target 200` produces a 125-molecule snapshot AND
(with Supabase creds) loads it. **M3:** `transform/leaderboards.py` emits self-describing boards
(metadata + enriched entries + `leaderboards/index.json`) that the web `/best` pages render.
**Curation, 55 overlays (was 5):** curated `types:` overlays fold into `kind:"type"` categories
(roam role pills + `/in/<type>`, ~16 clusters: vitamins/neurotransmitters/analgesics/steroids/…);
Sweetest board 2→9; `still_in_system` half-lives + `serving_mg` for theobromine/theophylline/nicotine
plus the OTC drugs (acetaminophen/ibuprofen/naproxen/melatonin) so StillInSystem fires on 8 across
0.75-14h; Hottest reframed as "Most pungent" (pure-compound Scoville: capsaicin 16M via
`capsaicinoid_ppm: 1000000`, piperine via a direct `scoville_shu` overlay); Most caffeinated dropped
(metric never wired, not an honest molecule board); `snapshot_export` prunes stale files; `_TYPE_NAMES`
fixes acronym labels (nsaid → NSAID). 42 offline tests pass; ruff clean. **Pushed + live; even with origin.**

**Color-as-Information (2026-07-11, pushed + live — commit `19a1cf6`):** for
`../MoleculeFinder-Color-System-Brief.md`. `transform/structures.py` now renders CPK-colored SVGs
(**verified recipe:** `updateAtomPalette` with **carbon = key 6** + `singleColourBonds` +
`setSymbolColour(#bdd6e6)` + `clearBackground=False` → uniform light skeleton, colored heteroatom
labels, transparent bg). `transform/families.py` maps type-slug → family key (the web mirrors it in
`lib/families.ts`); `assemble.py` bakes `family` per molecule + `neighbor_family` per edge.
`transform/roam_layout.py` bakes a deterministic family-clustered constellation → `roam.json`
(emitted by `snapshot_export`). Regenerate all of it with `mfetl transform && mfetl export`.

**Design principle (Garrett's call):** leaderboards rank **molecules by intrinsic properties**
(sweetness, LD50, weight, pure-compound pungency). Food-shaped rankings (hottest sauces, most
caffeinated drinks) are a **separate future content type**, not a board metric. The food angle
already lives in `foods:` categories + the new type tags.

**BUILT + committed local, held for push — the 125 -> 489 Scope B rebuild.** Read
`../scope-b-rebuild-STATUS.md` first. All four steps are DONE + tested in local `main`:
- **Step 1 — household seed + structureless hand-model path.** `sources/seeds/household_must_include.yaml`
  (38 must-includes). `canon.py`: `household_seed()`, `_synthetic_cid()` (hand-model rows get a stable
  **negative** CID), fetch **skips** hand-model rows; transform routes them to `assemble_handmodel()`.
- **Step 3 — buckets.** `transform/buckets.py` (labels + roam ring order; mirrors web `lib/buckets.ts`).
  `assemble.apply_scope_bucket()` stamps `scope_bucket`/`scope_family` + a `kind:"bucket"` category +
  `neighbor_bucket` on edges. `roam_layout.py` clusters by **bucket** and emits a `groups` legend.
- **Step 4 — DONE.** The 489 core is now the canon INPUT: `canon.build_scope_b_canon()` reads
  `sources/seeds/scope_b_core.csv` → exactly 489, each stamped with bucket/family, ranked by CSV
  pageviews, no notability net / no `--target`. The parquet schema carries `scope_bucket`/`scope_family`/
  `is_otc`/`dual_use` so `assemble_record` stamps all 489. Ran seed→fetch (471 CIDs)→transform (2240
  edges, 1124 hooks)→export; snapshot regenerated (489, `data/` committed). `mfetl load` **skipped**
  (stale-125 UNIQUE(slug) collision — reconcile Supabase at ship time; static site reads the snapshot).
- **CAS — DONE.** `assemble._extract_cas` pulls the first checksum-valid CAS from PubChem synonyms
  (checksum rejects same-shaped EC numbers) → `record.cas`; the web shows it beside the CID + JSON-LD.
Scope C (the 839-molecule drugs wing, `../drugs-wing-deferred.csv`) stays deferred.

## How it flows (disk-to-disk, resumable)
- `stage_seed` → `data/seed/canon.parquet` — canon: marquee names→CID
  (`pubchem.name_to_cid`, filter-2) + curated CIDs + Wikidata notability, ranked by pageviews.
- `stage_fetch` → `data/seed/fetched.json` — batched properties + synonyms; PUG-View
  Toxicity/GHS warmed into `data/raw_cache/`.
- `stage_transform` → `data/seed/molecules.json` — `assemble.py`; filter-4 applied.
- `stage_load` → Supabase upserts (idempotent) + `ingest_run`; **skips if no creds.**
- `stage_export` → `data/snapshots/` — per-molecule JSON + index + leaderboards.

## Supabase / DB
- Creds in `.env` (gitignored): `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (= the `sb_secret_…`
  key). `mfetl load` uses supabase-py (REST). Refresh the web repo's snapshot copy with
  `npm run sync-data` there.
- **DDL/migrations (no `psql` locally):** connect with `psycopg` over the Supabase **session
  pooler** (port 5432, IPv4) and apply `supabase/migrations/*.sql` in order — including
  `0003_grants.sql`, which grants the API roles (the SQL Editor does this automatically; a
  raw connection does not, or the API 42501s "permission denied"). Pooler passwords can
  contain unescaped `@ # $ \` — split on the LAST `@`, pass host/user/password/dbname as
  psycopg kwargs (not a URL).

## PubChem gotchas (fixed in code — watch at 10k / on API drift)
- Property fields renamed: read `SMILES` (isomeric) + `ConnectivitySMILES` (canonical).
- Batched POSTs need ONE comma-separated `cid=1,2,3`; repeated `cid=1&cid=2` returns only
  the first CID.

## Next
- **Ship the Scope B rebuild** (when Garrett approves the push): push ETL then WEB, then **reconcile
  Supabase** — `mfetl load` was skipped on a stale-125 UNIQUE(slug) collision; wipe the `molecule`
  table + `mfetl load` fresh, or teach `supabase_loader.load_all` to delete stale rows + reassign
  slugs across CIDs. Only affects `/dashboard` + `/api/e`, not the static site. (Task chip filed.)
- Scale to `--target 10000` — **gated** until the marquee template earns engagement.
- Turn on weekly `.github/workflows/etl.yml` (needs the Supabase secrets + a Vercel deploy
  hook in the repo's Actions secrets).
