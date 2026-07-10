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

## What is REAL vs. STUB
- **Real (building blocks):** `config`, `sources/registry` (+ guard), `sources/pubchem`
  (`properties`, `pug_view`), `sources/wikidata`, `sources/pageviews`,
  `transform/` (canon, slugs, confidence, similarity, toxicity, ghs, hooks,
  categories, leaderboards, names, structures), `load/supabase_loader`,
  `load/snapshot_export`. Offline tests pass.
- **Stub (your M1 work):** `pipeline.py` — `stage_fetch`, `stage_transform`,
  `stage_load`, `stage_export` are log-only placeholders. **M1 = wire the real
  functions into these stages** and define the assembled per-molecule record that
  flows fetch → transform → load → export.

## M1 build order (this repo)
1. `stage_fetch`: for the seed canon CIDs, call `pubchem.properties` (batched) and,
   where relevant, `pubchem.pug_view` for `Toxicity` + `GHS Classification`. Cache.
2. `stage_transform`: assemble molecule dicts — preferred name (`names`), unique
   `slugs`, Morgan fingerprints → top-30 `similarity` edges, parse `toxicity`/`ghs`,
   `categories.functional_groups`, `hooks.hooks_for` (see plan §7.1), `structures.svg_for`.
   Merge `sources/curated/*.yaml` overlays. Apply filter-4 (drop hookless/edgeless orphans).
3. `stage_load`: upsert every table via `supabase_loader`; `record_run` each stage.
4. `stage_export` already delegates to `snapshot_export.export`; just call it.
5. Add pytest coverage for new parsers (assert caffeine t½≈5h behavior, an LD50 parse,
   a GHS parse). Keep the suite green.

## Definition of done for M1 (etl)
`mfetl all --target 200` produces `data/snapshots/molecules/*.json` + `index.json`
+ leaderboards, every value labeled, no BLOCKED source touched, tests green.
