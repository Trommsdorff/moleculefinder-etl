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

## Status: M1 + M3-leaderboards DONE (2026-07-10)
`pipeline.py`'s five stages flow fetch → transform → load → export; `transform/assemble.py`
builds the per-molecule record. `mfetl all --target 200` produces a 125-molecule snapshot AND
(with Supabase creds) loads it. **M3:** `transform/leaderboards.py` now emits self-describing
boards (metadata + enriched entries + a `leaderboards/index.json`) that the web `/best` pages
render. Recent: an em-dash sweep of board descriptions + curated editorial (house rule). 41
offline tests pass; ruff clean. **Ahead 1, unpushed** (the em-dash commit); origin has M3.

**Next — the ETL curation pass** (agreed for after the web design install): hand-curate the marquee
YAML (`sources/curated/*.yaml`) to add (a) molecule **type tags** (stimulant, methylxanthine, roam
role pills; only `food` + `functional_group` categories exist today), (b) **board coverage**
(caffeine-per-serving so `most-caffeinated` populates; more sweetness/Scoville for `sweetest`/`hottest`),
and (c) more **half-lives** so the web `StillInSystem` hook fires beyond caffeine. Regenerate with
`mfetl transform && mfetl export`, then `npm run sync-data` in the web repo.

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
- Scale to `--target 10000` — **gated** until the marquee template earns engagement.
- Turn on weekly `.github/workflows/etl.yml` (needs the Supabase secrets + a Vercel deploy
  hook in the repo's Actions secrets).
- Curate more marquee overlays (`sources/curated/*.yaml`; ~5 today, plan envisions ~500).
