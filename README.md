# moleculefinder-etl

Public ETL for **MoleculeFinder**: pulls from PubChem + Wikidata (+ Wikipedia
pageviews), transforms, and loads Supabase **and** a static JSON snapshot the
web app builds from. Public repo → free GitHub Actions. See the build plan
(`MoleculeFinder_Technical_Build_Plan.md`, sections 4–6) for the full design.

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env            # add Supabase creds
mfetl seed --target 10000       # stage 0: build the canon
mfetl all                       # run every stage
pytest                          # offline unit tests
```

## Stages (`mfetl <stage>`)
`seed` → canon selection · `fetch` → PubChem · `transform` → names/fingerprints/
similarity/tox/hooks · `load` → Supabase upserts · `export` → static snapshot · `all`.

## The license firewall
`sources/registry.py` marks non-commercial / share-alike sources as BLOCKED and
`assert_not_blocked()` raises if any code tries to ingest them. Do not remove it.

## Layout
```
moleculefinder_etl/  sources/ (wikidata, pubchem, pageviews, registry, curated/)
                     transform/ (canon, slugs, similarity, toxicity, ghs, hooks, ...)
                     load/ (supabase_loader, snapshot_export)
                     cli.py  pipeline.py  config.py
supabase/migrations/ 0001_init.sql (schema)  0002_events.sql (measurement sink)
.github/workflows/   etl.yml (weekly + manual)
```

## Status
M0 foundation: schema, canon selection, rate-limited source clients, the license
firewall, confidence labeling, similarity, and offline tests are real. Stage
fetch/transform/load bodies fill in during M1.
