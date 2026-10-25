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
6. **THE SOURCE-LICENCE RULE (2026-10-23).** Every source has a licence class in
   `sources/registry.py`, and whether its values may be displayed is DERIVED from the class.
   A value reaches the snapshot only from a displayable source, and the export refuses
   (`transform/licence_gate.py`) if any value cites a source with no entry or one that may
   not be displayed. A new source, a new field or a new parser registers its source first.
   See "The source-licence rule and the registry" below.

## Commands
**STANDING ORDER (Garrett, 2026-10-21): local servers and local runs use BLANKED database keys** unless the
step genuinely needs the live database (a migration, a deploy check). Blank them on the command itself:
`SUPABASE_URL= SUPABASE_SERVICE_KEY= SUPABASE_DB_URL= <command>` (the `.env`/`.env.local` files hold the live
keys). **Every session stops its own servers and checks for leftovers before it closes:**
`lsof -nP -iTCP -sTCP:LISTEN | grep -E 'node|python'` must show nothing the session started. A leftover server
holding live keys was found on port 3000 on 2026-10-21.

**A build on this Mac is PINNED (2026-10-20): run `mfetl sync-inputs` first.** It downloads the exact
inputs main was built from (the weekly run's artifact); `mfetl all` then reproduces main, fetching only
what is genuinely new (a tranche's molecules). Without the sync, a pinned export refuses. See "Run A,
part 1" below. `MFETL_INPUTS=refresh` is a one-off local data refresh, never a code build.
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
mfetl seed --target 200      # small canon for a fast smoke test (scale to 10000 later)
mfetl all
pytest                       # offline tests must stay green
ruff check .
```
**On Garrett's machine `source .venv/bin/activate` silently gives you the WRONG python.**
The venv predates the Dropbox -> `~/137` move (2026-07-28) and its `activate` still exports
`VIRTUAL_ENV=/Users/garrettpoe/Dropbox/137/...`, a path that no longer exists, so the PATH it
prepends resolves to nothing and `python3` falls through to the system framework build, where
`rdkit` is not installed. The venv itself is fine. Call its binaries directly:
`./.venv/bin/python3 -m moleculefinder_etl.cli all`, `./.venv/bin/python3 -m pytest`. (The
`mfetl` console script has the same stale path baked into its shebang.) Recreating the venv
would also fix it; nothing in the repo depends on the old one.

## Status: LIVE on moleculefinder.com — canon is **498** (domain pointed 2026-07-14)
> The site is launched on its own domain and serves **498** molecules (489 Scope B core + 9 added for
> the boards). Since the original 489 rebuild (`scope-b-rebuild-STATUS.md`, historical): Everyday Worlds
> + Trails (`sources/seeds/{worlds.yaml,relationships.csv,why_it_matters.yaml}` compiled by
> `transform/relationships.py` → `trails` + `worlds.json`), curated brand names + odor thresholds
> (`sources/seeds/{brands.yaml,odor_thresholds.yaml}`), `has_3d`, greek-letter title normalization
> (`assemble._normalize_greek`), and the split `spiciest`/`pungent` boards. Supabase reconciled.

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
labels, transparent bg; since trust run 6, 2026-10-25, the palette covers every element, see that
section). `transform/families.py` maps type-slug → family key (the web mirrors it in
`lib/families.ts`); `assemble.py` bakes `family` per molecule + `neighbor_family` per edge.
`transform/roam_layout.py` bakes a deterministic family-clustered constellation → `roam.json`
(emitted by `snapshot_export`). Regenerate all of it with `mfetl transform && mfetl export`.

**Design principle (Garrett's call):** leaderboards rank **molecules by intrinsic properties**
(sweetness, LD50, weight, pure-compound pungency). Food-shaped rankings (hottest sauces, most
caffeinated drinks) are a **separate future content type**, not a board metric. The food angle
already lives in `foods:` categories + the new type tags.

**SHIPPED — the 125 -> 489 Scope B rebuild is LIVE.** Read `../scope-b-rebuild-STATUS.md` first.
All four steps done, pushed, and deployed; Supabase reconciled to the 489. How it was built:
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
  edges, 1124 hooks)→export; snapshot regenerated (489, `data/` committed). Supabase reconciled to
  the 489 post-deploy (targeted delete of the 37 stale cids + `load_all`) after fixing a
  `molecule_category` dup-key bug (`b882a07`; sweetener carries a bucket + a type slug `sweetener`).
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
- `stage_export` → `data/snapshots/` — per-molecule JSON + index + leaderboards + `featured.json`
  (molecule of the week, compiled from `sources/seeds/featured.yaml`; see its section below).
- `mfetl featured` (offline, not part of `all`) rebuilds only `featured.json` from the snapshot
  already on disk, keyed to its `meta.json` date, for previewing a seed edit. It never moves meta.json.

## Supabase / DB
- Creds in `.env` (gitignored): `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (= the `sb_secret_…`
  key). `mfetl load` uses supabase-py (REST). Refresh the web repo's snapshot copy with
  `npm run sync-data` there.
- **DDL/migrations: `mfetl migrate` (2026-10-19). NEVER ask Garrett to paste SQL into the
  Supabase dashboard** (his words: he wants a long-term fix where he does not log in each time).
  The REST keys cannot GRANT/REVOKE/CREATE, so migrations use `SUPABASE_DB_URL` in `.env` (the
  dashboard's Connect -> Session pooler string, password filled in; gitignored). `mfetl migrate`
  lists pending files; `mfetl migrate --apply` runs each in its own transaction with its row in
  `mfetl.migration_log` (a schema the Data API does not expose), then prints what the anon key may
  read. The first run records 0001-0003 as applied by hand (`migrate.PRE_LOG`) instead of re-running
  them. Needs `uv pip install --python .venv/bin/python3 "psycopg[binary]>=3.2"` (the `db` extra;
  the weekly run does not). The env has no pip: use uv. Proven end to end on a local Postgres in
  the live pre-deploy state: dry run changes nothing, apply leaves anon reading `molecule` and not
  `event`/`ingest_run`, a second apply is a no-op. A new migration still grants explicitly
  (`0003_grants.sql` and the raw-connection 42501 trap; `tests/test_migration_grants.py`).
  Pooler passwords can contain unescaped `@ # $ \` — `migrate.connect_kwargs` splits on the
  LAST `@` and passes kwargs, not a URL.
- **Rotating the database password (done 2026-10-21, after it was echoed into a session transcript by
  a shell `source .env` error).** The `postgres` login cannot change its own password (`ALTER ROLE`
  answers InsufficientPrivilege), so a rotation is Garrett's one dashboard step: Project Settings ->
  Database -> Reset database password -> Generate -> Copy; then
  `./.venv/bin/python3 scripts/set_db_password_from_clipboard.py` reads the clipboard, checks the new
  password connects before touching `.env`, swaps it in and clears the clipboard, printing no secret.
  Only `mfetl migrate` uses this password. **Never `source` or `.` the `.env` in a shell:** its unquoted
  password breaks shell parsing and the error prints the line. Read it with python-dotenv instead.

## PubChem gotchas (fixed in code — watch at 10k / on API drift)
- Property fields renamed: read `SMILES` (isomeric) + `ConnectivitySMILES` (canonical).
- Batched POSTs need ONE comma-separated `cid=1,2,3`; repeated `cid=1&cid=2` returns only
  the first CID.

## Traffic build plan 2026-09-05 — phases 0-3 DEPLOYED 2026-09-06 (`cd8eea1`, then `094d8e1`)
Phases 0-3 are live. What follows describes what they changed; the phase 4 + 7 section below
is the NEXT thing, built on `traffic-2026-09-tranche1` and NOT pushed.
Full spec: `../BUILD-PLAN-traffic-2026-09-05.md`. What changed in THIS repo:
- **Phase 0 — the refresh now reaches the site.** `etl.yml` no longer curls a Vercel deploy
  hook (that rebuilt the web app from its own July snapshot copy while this repo drifted 77
  molecule files ahead). A `sync-web` job checks out `moleculefinder-web` with a repo-scoped
  PAT, copies `data/snapshots/`, and opens a PR titled `data: weekly snapshot YYYY-MM-DD`.
  Merging is the deploy. A heartbeat-only week opens no PR.
  **⚠ Needs a `WEB_REPO_TOKEN` Actions secret on THIS repo before the workflow can run.**
- **Phase 1 — `assemble.build_description`** composes a unique 100-200 char description for
  every record from `sources/seeds/description_phrases.yaml`; a curated `why_it_matters` line
  leads it and stands alone when it already clears the floor. `why_it_matters.yaml` went from
  59 entries to **498**. `attach_descriptions` raises on a duplicate, a short one, or an
  em-dash.
- **Phase 2 — `toxicity.best_oral`** is the single LD50 selector (oral rat > oral mouse > oral
  any; sub-1 mg/kg dropped unless the slug is a named potent toxin). It feeds the Deadliest
  board AND the dose lens, so neither can rank an intravenous value under an oral heading
  again. `assemble_record` now carries `is_otc`/`dual_use`. `otc_allowlist.yaml` moved INTO
  this repo (Actions checks out one repo) and drives 7 `kind:"use"` hubs.
  `food_hubs.yaml` curates 13 food hubs by hand.
- **Phase 3 — 52 new hubs** (family / element / GHS-hazard / size-band / 8 more SMARTS) and
  **3 new boards** (lightest, safest, most-searched). `unify_category_kinds` forces one slug
  onto one kind corpus-wide; `prune_thin_categories` drops derived hubs under 3 members.

## Traffic build plan phase 4 + the automatic loop — DEPLOYED 2026-09-06 (`e937ca2`)
The weekly loop closed itself end to end on 2026-09-06: run 34064809022 opened
moleculefinder-web PR #2 (222 files), waited for its `ci` run on that exact sha, saw
`verify` succeed, squash-merged, and Vercel deployed `4a4e1ee`, which then triggered the
web repo's IndexNow workflow (222 URLs submitted, 222 accepted). Nobody clicked anything.
Three defects were found and fixed getting there; see the three commits after `9f6c934`.
- **Catalog tranche 2026-09-A: 498 -> 788 molecules** (`27b3a12`, minus the 5-row hold below). 295 rows appended to
  `scope_b_core.csv` under a new **`batch` column** (provenance: a tranche can be identified
  and lifted back out). 184 pharmaceuticals from `../drugs-wing-deferred.csv` at >=10k
  Wikipedia views/month (the plan says "the 206 pharmaceuticals at >=10k"; **206 is ALL rows
  at >=10k, of which 184 are pharmaceutical and 22 recreational**), plus 111 elements,
  materials and household chemicals from the top-500 remainder. The 89 recreational-drug rows
  stay deferred, gated on Garrett.
- **Two new buckets**, `prescription-medicine` and `element-material`, mirrored in the web's
  `lib/buckets.ts` + `--bucket-rx` / `--bucket-element`. The eight original buckets could not
  hold these honestly: OTC-vs-Rx is hand-decided per `otc_allowlist.yaml`, and 70 elements in
  `everyday-chemistry` (17 members) would be the periodic table wearing a household label.
- **`family` is now also the drug class** (ssri, benzodiazepine, beta-blocker...), so 39 new
  `/in/` hubs come free through the existing family-hub emission. 141 hubs, was 102.
  Every new family slug needs an entry in `description_phrases.yaml` or the description
  falls back to the word "compound", which is what phase 1 existed to remove.
- **290 new `why_it_matters` lines** (788 total), written from the structured record only.
- **Five rows HELD back before deploy** (Garrett, 2026-09-06) on the rule *not approved for
  human use in the US, UK or EU, or veterinary-only*: trenbolone, metandienone, ibutamoren,
  semax, xylazine. They live in `sources/seeds/deferred_rows.csv` with a reason each, and
  `tests/test_deferred_rows.py` fails the build if any reappears in `scope_b_core.csv` (they
  are high in `../drugs-wing-deferred.csv`, so the next tranche would otherwise re-add them).
  The rule is narrower than "controlled substance": fentanyl, amphetamine and the
  benzodiazepines are approved medicines and stayed. Oxandrolone stayed for the same reason.
  Side effect worth knowing: it also removed TWO `/in/` hubs, `anabolic-steroid` (3 -> 1) and
  `alpha-2-agonist` (3 -> 2), both auto-pruned under the 3-member floor. So the sitemap went
  964 -> **957**, not 959: five molecule pages and two hubs.
- `assemble_record` flags a fetched record with **no SMILES** as `macromolecule` (the
  no-figure page variant) while leaving `hand_model` false: pembrolizumab is an antibody with
  a real PubChem CID, and only a hand-modeled record may say "no single PubChem compound".
- **`sync-web` checks out the sha the `run` job pushed**, not the one that triggered the
  workflow. A bare `actions/checkout` gets the triggering sha, i.e. the tree BEFORE this run
  refreshed anything, so every weekly PR would have carried the previous week's data: the
  phase 0 failure again, one layer up. Caught on the 2026-09-06 dispatch, where the stale
  tree happened to equal the web repo's copy and the job said "already identical, no PR".
- **The weekly loop is now automatic** (`00e91de`). `sync-web` waits for the web repo's
  `verify` check on the PR it opened and **squash-merges when it is green**; the merge is the
  deploy. A red check leaves the PR open and fails the job (issue + email). It keeps exactly
  ONE open data PR: it pushes onto the open one's branch and closes any other as superseded,
  which is safe only because the snapshot is copied whole and never diffed.
  **Green is decided from the ACTIONS API by `head_sha`**, not from `gh pr checks`: *Checks is
  not a permission a fine-grained PAT can hold at all*, so the check-runs route was never open
  to this token. It requires the newest `ci` workflow run for the PR's exact head commit to be
  `completed`/`success` AND its `verify` job to be `success` (a run can conclude success with
  its only job skipped). `WEB_REPO_TOKEN` needs **Actions: Read** for this, plus **Issues: RW**
  for the superseded-PR comment; both were granted 2026-09-06 alongside Contents + Pull requests.
- Counts: 793 molecules, 793 distinct descriptions (100-209 chars, mean 137), 0 orphans,
  141 hubs, deadliest 232 entries, 97 tests, ruff clean.

### DEPLOYED 2026-09-08 — and the local raw_cache shipped a regression the loop caught
ETL `1b38269..aa0967b` (no deploy), then web `380c2e2..11c8bbb` (the deploy, live 13:26 UTC).
- **The determinism work holds on Linux CI.** The proving dispatch (run 34232247646) produced
  **zero synonym changes and zero `structure_svg` changes** against the snapshot built on macOS.
  `/m/omeprazole`'s served SVG is byte-identical before and after the deploy (11,509 bytes,
  sha256 `028384ff…`), which is the carry-forward doing its job across a platform change.
- **But my LOCAL `data/raw_cache` was stale, and it regressed 26 molecules.** The Wikidata
  cache on this machine held bulk-batch QIDs where the live source has the real items, and a
  PUG-View miss for omeprazole. `mfetl all` read that stale cache and wrote WORSE values into
  the snapshot I shipped: 22 `wikidata_qid` (alanine `Q218642` -> `Q106345485`, glycine
  `Q620730` -> `Q106345678`, taurine `Q207051` -> `Q106345481`), 11 `summary` back to "chemical
  compound" (taurine, hesperidin...), and omeprazole's oral LD50 to null. **I misread these in
  the run-3 report as an upstream refresh; they were the opposite.**
- **The weekly loop caught it unattended**, which is exactly what part B of run 2 was built for:
  CI fetched fresh, corrected all 26, pushed `c01ce71`, opened web PR #3, waited for CI, and
  squash-merged at 13:33 UTC. Live within four minutes of the regression being detected.
- **Lesson, and why `data/raw_cache` was wiped in the cleanup:** a stale local cache silently
  overwrites good data, and nothing in the pipeline notices, because a cache hit looks exactly
  like a fetch. Worth an expiry on the Wikidata and PUG-View entries. The PubChem property and
  synonym caches are safe (their content genuinely does not change); the derived ones are not.

## Run 4 (2026-09-08) — the raw_cache can no longer ship a regression. DEPLOYED 2026-09-09
ETL `main` at `be1e92e`, web at `e40eb22` (its own deploy; nothing deploys from this repo).
Answers the lesson at the end of the run 3 section: "a stale local cache silently overwrites
good data, and nothing in the pipeline notices, because a cache hit looks exactly like a
fetch." **Verified after deploy:** dispatch 34341534405 ran 11m12s against the previous
4m52s (+6m20s, the one-time PUG-View re-warm of 770 CIDs whose restored cache entries were
undated), the guard logged no refusal, the snapshot came out byte-identical, and sync-web
reported "web repo snapshot already identical — no PR needed".

- **`sources/cache.py`** — every cached entry now carries the UTC instant it was fetched
  and whether THIS run fetched it. An entry written before the envelope existed reads back
  as *unknown age*, and unknown age is never fresh, so the very entries that caused the
  incident cannot be reused even once more.
- **Only the DERIVED sources expire.** Wikidata items get merged and split and PUG-View
  annotations get added to, so a stale copy of either is a claim about the past presented
  as the present: `descriptions.json`, `notable.json` and the per-CID PUG-View files now
  have a TTL (`MFETL_WIKIDATA_TTL_DAYS`, default **6**; `MFETL_PUGVIEW_TTL_DAYS`, default
  **30**). **The PubChem property and synonym caches are unchanged, on purpose** — a CID's
  formula, weight and name list are what that CID *is*, and a test pins that they keep no
  date. 6 and not 7 because the cron is weekly and CI carries `data/raw_cache` forward
  (`actions/cache` save+restore, so a stale entry can persist in CI too): a 7-day window
  would sit on the boundary and scheduler jitter would decide whether Wikidata got re-read.
- **`load/snapshot_guard.py`, the backstop.** `snapshot_export.export()` writes nothing
  until it has compared the records against the snapshot already on disk. The rule is not
  "these fields may never change", it is: **a protected field may only regress if the input
  behind the new value was fetched live in this run.** Three protected shapes, which are
  the three the incident had: a `summary` reverting to "chemical compound", an existing
  `ld50_mg_per_kg` going null, an existing `wikidata_qid` changing to a different one
  (filling a null is not a regression). A live fetch is by definition fresher than anything
  on disk, so **the weekly CI run that corrected all 26 passes untouched**; a cache hit is
  not, so the run that caused them stops. `MFETL_ALLOW_REGRESSION=1` overrides and logs
  every molecule it let through, because a deliberate rule change (tightening
  `toxicity.best_oral`) legitimately drops values and must stay shippable.
- **Freshness is NOT stored on the records or in `canon.parquet`.** Both are committed, and
  a timestamp that moves every run would put all 788 molecule files (or the parquet, which
  gates the workflow's heartbeat) into every weekly diff: exactly the churn run 3 removed.
  It goes in gitignored `data/seed/freshness.json` beside `fetched.json`, merged across
  stages so `seed` records Wikidata and `transform` records PUG-View without either
  erasing the other. An input a run never touched counts as not-live, so a partial re-run
  cannot launder a stale value in.
- **`tests/test_cache_safety.py` replays 2026-09-08 with the real values** (alanine
  `Q218642` -> `Q106345485`, taurine's summary back to "chemical compound", omeprazole's
  4000 mg/kg nulled) and asserts the export is refused *and* that the good snapshot is
  still whole on disk afterwards. Verified the test is load-bearing: remove the one
  `snapshot_guard.check` line and it fails. 24 tests here, 151 in the repo, ruff clean.
- **Not run at the time:** a live `mfetl all`. `data/raw_cache` was empty after the run-3
  cleanup, so a full run would have been a fresh fetch of the whole catalog and therefore a
  data refresh riding on a code deploy. The wiring was proven by offline tests against
  mocked WDQS/PUG-View. **That gap hid a real bug for a full deploy cycle — see run 5.**

## Run 5 (2026-09-09) — the Wikidata refresh was dead, and had been since run 2
Branch `fix-wikidata-post`. Run 4's TTL work exposed a latent bug and then a second one
behind it. Neither was caused by run 4; run 4 is what made them visible.

- **HTTP 414: the refresh had silently stopped happening.** `descriptions_for_cids` inlines
  one `VALUES` entry per CID, so the query LENGTH is the size of the catalog, and it was
  sent as a GET, i.e. in the URL. Measured: **the GET form breaks between 612 and 613 real
  CIDs** (~4,757 chars of query; the ceiling is characters, not CIDs, since real CIDs run 4
  to 8 digits). The catalog reached 770 in run 2's tranche. Before run 4 this never fired
  because the cache only ever queried the *missing* CIDs, which was 0 on a warm cache; the
  6-day TTL expires all 770 at once, and every run since had been failing with a warning
  nobody read, producing an identical snapshot and reporting success.
  **Fixed by POSTing** the query (`sparql(..., method="POST")`), where there is no URL
  ceiling and which stays correct as the catalog grows. Live: 770 fetched in one request,
  1.5 s.
- **A failed Wikidata query is now a FAILED RUN**, not a warning, and the message carries
  the exception class and text. The fallback is safe (values kept, marked not-live, so
  `snapshot_guard` refuses any regression built on them) and *that safety is exactly what
  let this hide*. `MFETL_ALLOW_STALE_WIKIDATA=1` restores the warning for a deliberately
  offline run.
- **One PubChem CID is not one Wikidata item, and "first binding wins" was arbitrary.**
  With the POST working, the first live run wanted to change **15 QIDs and 13 summaries**
  and three of those summaries were `"chemical compound"` written over good prose
  (fluorine, mercury, vasopressin), plus carbon, phosphorus and lead swapped off their
  element items onto allotropes. Cause: **70 of the 769 CIDs have two Wikidata items sharing
  the same P662** (element vs allotrope, hormone vs compound), and the code took whatever
  order WDQS returned. That order is stable between back-to-back queries but had already
  moved for 15 CIDs since the snapshot was built. **The export guard would have allowed all
  of it**, correctly by its own rule: it asks whether a value came from a live fetch, and
  these did. Fresh is not the same as right.
  `wikidata._choose_item` now decides: **never a placeholder description over a real one,
  then the lowest Q-number** (the oldest item, a good proxy for canonical: Q623 carbon,
  Q650 fluorine, Q674 phosphorus, Q708 lead, Q925 mercury all predate the items shadowing
  them, and the `Q1063456xx` bulk-import items behind the 2026-09-08 regression sort last by
  construction). Result against the committed snapshot: **759 of 769 CIDs keep the QID they
  had; 10 change; 7 of the 8 summary changes remove a `"chemical compound"`; none add one.**
  Repeating the query picks the same item for all 769.
- Live proof from the Mac (`mfetl seed`, the Wikidata stage alone): 770 queried, **769
  returned a QID** (1 CID has no Wikidata item), **770/770 recorded live** so the guard
  accepts them as fresh fetches. `canon.parquet` was restored afterwards so the branch is
  code-only and CI produces the data change through the normal loop.
- 163 tests (was 155), ruff clean. New tests pin: a 900-CID query is built as a POST with
  the query in the body and the bare endpoint as the URL; a failed query raises with the
  exception class and message; the override downgrades it; and item selection is stable
  under row reordering, prefers a real description, sorts Q-numbers numerically, and never
  lets a bulk-batch item displace a real one.
- **Worth knowing:** the guard cannot tell "fresh and correct" from "fresh and arbitrary".
  Making the placeholder-summary check freshness-independent (a `"chemical compound"`
  summary is never an improvement, however fresh) would have caught this class directly.
  Not done here; done in run 6 (next section).

## Run 6 (2026-09-12) — feedback triage: the classifier, the placeholder, the date. DEPLOYED 2026-09-12
Branch `traffic-2026-09-feedback` from `56d3342`. Scope: the MF 6 items of
`../network/FEEDBACK-TRIAGE-2026-09-12.md` that live in this repo (the web half is in the web
CLAUDE.md). Four commits:
- **MF-3, `d00bcf3`: a carboxylic acid needs a carbon or a hydrogen on the carboxyl carbon.**
  `[CX3](=O)[OX2H1]` matched a carbonyl carbon bonded only to oxygen, so bicarbonate and its
  sodium, potassium and ammonium salts sat in `/in/carboxylic-acids` (carbonic and carbamic
  acid would have too). Now `[CX3;$([CX3H1]),$([CX3][#6])](=O)[OX2H1]`.
  `tests/test_categories.py` pins all 13 functional groups (107 cases, at least two positives
  and two negatives each), plus a test that the OLD pattern really matched the carbonates, so
  the negatives are load-bearing. A group added to `FUNCTIONAL_GROUPS` without cases fails.
- **MF-6, `12b857b`: the placeholder summary is refused even when fetched live** (run 5's
  open item; tranche 2 no longer carries it). The LD50 and QID keep the live-fetch rule. A
  summary reverting to "chemical compound" never passes, whatever its provenance, because
  fresh is not the same as right. `MFETL_ALLOW_REGRESSION=1` still overrides.
- **`0fc0080`: `data/snapshots/meta.json` = `{"refreshed": "YYYY-MM-DD"}`,** which the web
  prints as "Data refreshed" (MF-9). Not in the prompt's ETL list: the web item needed a
  snapshot field and none existed. `export()` renders every output first, compares it with
  disk, and moves the date only when a file differs or is pruned, so a quiet week stays
  byte-identical (tested). No per-record timestamp, for the run-3 churn reason.
- **Data, `8798ebb`: exactly four molecule files, plus meta.json.** The prompt said "from the
  cache", but `data/raw_cache` was empty (the run-3 cleanup wiped it), so:
  1. **Pass 1** at origin/main code, live: seed, fetch, transform, export called directly (no
     Supabase load). 18 minutes, most of it PubChem backing off at the start. Upstream drift
     since the 2026-09-09 snapshot: the synonym lists of 12 molecules. No summary, QID, LD50 or
     category moved; the guard was silent.
  2. **Pass 2** at the new code from that cache: 1.9 s, no network. Pass 1 to pass 2 changes
     `ammonium-bicarbonate`, `bicarbonate`, `potassium-bicarbonate` and `sodium-bicarbonate`,
     each losing `carboxylic-acids` and nothing else (descriptions included). 165 of 166 hubs
     unchanged; `/in/carboxylic-acids` 150 to 146; nothing joins any hub.
  3. The 12 drifted files, `index.json` and `canon.parquet` (content-identical, re-encoded)
     restored from HEAD, so the commit carries the classifier's effect and nothing upstream.
     Monday's scheduled run publishes the synonym refresh through the normal loop.
- **Second pass before the deploy (Garrett, same day): `display_synonyms` on every record.**
  `assemble.display_synonyms`: Wikidata's English label, then its aliases in Wikidata's order,
  then the stored PubChem synonyms; a name is kept only if it starts with a letter, holds only
  letters, spaces, hyphens and apostrophes, is 25 characters or fewer, is not all capitals
  beyond 5 characters, and is not the title in any case; case-insensitive de-dup, first four.
  756 of 788 records get at least one (652 get four). The web prints them under the H1 and
  takes the first, capitalised, as the title's parenthetical.
  - **The names come from the Wikidata API (`wbgetentities`), not GROUP_CONCAT in the POST
    query**, which is what the prompt named. Measured: WDQS returns an item's aliases in a
    server-dependent order (the same query three times, a minute apart, three backend servers:
    13 of 136 items came back reordered, same sets), so it cannot be both "Wikidata order" and
    deterministic. `sources/wikidata.py::names_for_qids` reads each item's stored order, 50 ids a
    request, for the QID the unchanged run-5 selection chose. Cached in the same descriptions
    entry (an entry with no `aliases` key is a miss), carried through `canon.parquet` as
    `wikidata_label` and `wikidata_aliases` with pinned types.
  - **The label leads the aliases** because for acetaminophen "paracetamol" is Wikidata's English
    label and "acetaminophen" only an alias; from aliases alone, Paracetamol never appears.
  - Data: the cache had been wiped at the last cleanup, so this fetched live again (7 min).
    Against the same inputs the only change is `display_synonyms` on all 788 files plus the two
    parquet columns. The 12-molecule PubChem synonym refresh rides along this time: restoring
    those files from HEAD would have dropped the new field from them.
- 322 tests, ruff clean. **Deploy order unchanged: ETL main first (no deploy), then web main.**
  The first CI run after the merge keeps `refreshed: 2026-09-12` unless the data moves.
- **Round two before the deploy (Garrett, same day): near duplicates, the parenthetical, one
  LD50.** Code `8e8dd8c`, data `3a80ffb`, regenerated from the kept `data/raw_cache` in seconds
  (fetch, transform, export; no seed, so `canon.parquet` did not move). Against the previous
  snapshot only molecule files changed; index, roam, worlds, comparisons, meta and all eight
  boards are byte-identical.
  - **`display_synonyms` drops a near duplicate of the title**, case-insensitively: a name that
    contains the title, sits inside it, or is within two letters of it (Levenshtein), also
    compared with the title's Greek letters spelled out ("beta-alanine" under β-Alanine). The
    four are counted after the filter. 996 names left 526 lines; 708 records keep a line (was
    756). The rule is literal and takes some real names with it: "Cipro" (inside
    Ciprofloxacin), "Naprosyn" and "chlorpheniramine" (two letters from Naproxen and
    Chlorphenamine), "sodium citrate" (inside Trisodium citrate).
  - **`title_synonym`, the title's parenthetical, is chosen here** (`assemble.title_synonym`,
    stamped by `attach_title_synonyms` after the descriptions), because its first rule needs the
    Wikidata label and the web never sees it: never when the title has a parenthesis; the label
    when it survived the display filters; else the first display synonym the description or
    why_it_matters text uses as a whole word; else none. 135 chosen (34 label, 101 text); the web
    renders 111 (24 would pass 65 characters). **44 of the 111 are drug brand names** (Fluoxetine
    (Prozac), Ibuprofen (Advil)), and a few name something other than the molecule because
    PubChem lists it as a synonym: Apigenin (Chamomile), Ephedrine (Ephedra), Estradiol
    (Estrogen). Both are Garrett's call and not decided.
  - **`toxicity.primary_ld50` is the one LD50**: oral rat, then oral mouse, then any oral
    (`best_oral`; a sub-floor oral value is dropped, not demoted), then the lowest value by any
    other route, ties broken on route then species. `_apply_primary_ld50` stamps `ld50_*` and
    moves that row to the front of `toxicity`, so the Safety panel's first row is the value the
    dose hook, the boards and the /vs tables read. **The dose hook and the Deadliest and Safest
    boards take it only when it is oral** (`leaderboards.ORAL_ONLY`): the boards' copy says oral,
    and the lens must never scale an injected dose. Effect: `toxicity` order on 56 records,
    `ld50_*` filled on 42 whose values are all by another route (oxymetazoline's 0.8 mg/kg oral
    is a sub-floor artifact, so its 1.1 by another route leads). No LD50 value, hook, description
    or board entry changed. A curated `dose_poison` overlay still pins the value (caffeine,
    capsaicin), each the row the rule picks anyway.
  - 354 tests (was 322): `tests/test_one_ld50.py` pins the selector and that the panel row, the
    hook and the boards read one row; `tests/test_display_synonyms.py` pins the near-duplicate
    rule and the parenthetical. Ruff clean.
  - **Found here, fixed in round three: the Iodine record was hydroiodic acid.** `scope_b_core.csv`
    row 475 mapped Iodine to CID 24841, hydrogen iodide (formula HI, CAS 10034-85-2, Wikidata
    Q908093). The page had shown HI's formula and CAS since the Scope B rebuild, and the label rule
    printed "Iodine (Hydroiodic acid)" in its title.
- **Round three before the deploy (Garrett, same day): a do-not-use list, and Iodine as I2.**
  Code `f62a953`, seeds `6574ccd`, data `daabe56`.
  - **`seeds/title_synonym_do_not_use.yaml`** lists names the parenthetical never uses, each with a
    reason, passed over by both rules (`assemble.title_synonym_do_not_use`, casefolded): the four
    Garrett named (chamomile, ephedra, estrogen, cochineal) and two found re-reading every
    remaining parenthetical, vitamin A (a group of compounds, under Retinol) and fused quartz (one
    glass made of silicon dioxide). Brand names stay, and so do everyday product names on the same
    reasoning (Bleach, Mothballs). The listed names still show on the synonym line under the H1.
    A test fails if any committed snapshot title uses a listed name. 357 tests, ruff clean.
  - **Iodine is CID 807 (I2)** in both `scope_b_core.csv` and `household_must_include.yaml`. Only
    CID 807 was fetched live (Wikidata Q2064483 "diiodine" and its PubChem properties, synonyms,
    Toxicity and GHS); the rest came from the cache. The swap changed iodine's own file, its
    search-index entry, the six leaderboard files its row moved in (its oral rat LD50 of 14,000
    mg/kg puts it on Deadliest at #222 and Safest at #13) and its canon.parquet row, and nothing
    else: no hub gained or lost a member other than iodine, and roam, worlds, comparisons and meta
    are byte-identical. Iodine leaves the compressed-gas and corrosive hubs and joins irritant and
    environmental-hazard; it gains the dose hook, so the web shows its Relative acute toxicity
    block. Its synonym line reads "Jod · Eranol · Iosan superdip · Jood", and it has no
    parenthetical ("diiodine" contains the title).
- **DEPLOYED 2026-09-12 on Garrett's word.** This repo's `main` fast-forwarded to `6ea1d68` (no
  deploy), then web `main` to `ee090a5`, Vercel Production ready at 22:34:51 UTC. Live checks,
  IndexNow and Lighthouse are recorded in the web CLAUDE.md. **The ETL dispatch was not run**, for the
  reason below.
  - **Resolved the same evening: the Supabase iodine row.** Supabase still keyed slug `iodine` to CID
    24841 (molecule id 809), and `load_all` upserts on `cid` with `molecule.slug` unique, so the next
    load would have failed inserting CID 807. Garrett authorized the one-row fix, sent as exactly
    `update molecule set cid = 807 where id = 809 and cid = 24841` through the REST API with the
    service key (no direct database password is kept locally): 1 row changed, and row 809 is the only
    row carrying CID 807 or 24841.
- **After the deploy, same evening: the loop, the loader, and the synonym line.**
  - **ETL dispatch 34724364616:** the load succeeded (788 molecules; `toxicity_value` 831 with iodine's
    three rows). Its snapshot differed from `main` in 12 molecules' PubChem synonym lists plus
    index.json (`90cdb69`), so sync-web opened web PR #5, which the loop verified and merged; Vercel
    deployed it and IndexNow accepted its 17 URLs. Two of those changes show on pages: doxycycline's
    line has Vibramycin where Doxychel was, and pantoprazole's gains Protonix and with it the title
    "Pantoprazole (Protonix)". **Why they moved:** the local raw_cache was wiped and re-fetched live
    on 2026-09-12, while CI's `syn60` entries are older and never expire, so the two caches disagree
    for those 12 molecules (cannabigerol, coenzyme-q10, doxycycline, erythromycin, etomidate,
    lisdexamfetamine, methadone, montelukast, naproxen, natamycin, pantoprazole,
    sodium-lauryl-sulfate). Any local regeneration flips them back: restore those files and
    index.json from `main` before committing local data, or the next weekly run opens a PR to undo it.
    (Since `5031441` the synonym entries expire, so this split should close with the first weekly
    run after it; see the last follow-up below.)
  - **`supabase_loader.rekey_moved_slugs`** (`0a83290`): before the molecule upsert, a slug whose
    existing row carries a different CID is re-keyed, `update molecule set cid = <new> where id = <id>
    and cid = <old>`, checked to change exactly one row, so a catalog correction like Iodine no longer
    stops the loop. A new CID another row already holds fails loudly instead of guessing. Counted as
    `rekeyed` in the ingest_run notes; `tests/test_load_rekey.py`.
  - **The do-not-use names leave the synonym line too** (`2b42778`): `display_synonyms` drops them
    and the next name moves up; the list is now `seeds/synonym_do_not_use.yaml`
    (`synonym_do_not_use()`). Data `20d4c23`: apigenin, carmine, ephedrine, estradiol, retinol and
    silicon-dioxide change that line and nothing else, and the snapshot differs from `90cdb69` only
    there. 363 tests, ruff clean.
  - **Two slips on `main`, both corrected forward; nothing ran or deployed in between.** `0a83290`
    also carried the staged seed rename, so for a few minutes the code read a missing file (an empty
    list) until `2b42778`. `bcafea3` meant to carry only the six lines but also carried the 12
    local-cache synonym lists and index.json (a restore step failed on zsh word splitting and its exit
    code went unchecked); `20d4c23` put those back exactly as `90cdb69` has them.
- **Last follow-up (2026-09-13 UTC, Garrett): the siblings, garbled names, and a synonym expiry.**
  Code `5a67549` (names and rule) and `5031441` (expiry), data `b50cc75`.
  - **Eight more do-not-use names**, the ones that moved up once the first six left their lines:
    oestrogen (estradiol); Mormon Tea and Mahuang (ephedrine); C ochineal and red food coloring
    (carmine); quartz glass, vitreous silica and fused silica (silicon dioxide).
  - **A one-letter word followed by a space marks a garbled name** (`assemble._GARBLED_NAME`, checked
    in `_readable_name`, so it governs the synonym line and the parenthetical; the search list is
    untouched). Words split on spaces, so "E-Z Prep", "baker's ammonia" and "vitamin A" stay. On the
    committed lines it took C ochineal, L Thyrox, L Thyroxin beta and L Thyroxin Henning
    (levothyroxine), E Mulsin and E Vicotrat (tocopherol), L Valylacyclovir (valaciclovir), and,
    being literal, two real names: neovitamin A acid (isotretinoin) and K citrate (potassium
    citrate). Isotretinoin's next name is Accutane, which its description uses, so its title is now
    "Isotretinoin (Accutane)". Data: nine molecule files (display_synonyms, plus isotretinoin's
    title_synonym) and meta.json (refreshed 2026-09-13, the UTC date). No other field or file moved.
  - **The PubChem synonym cache expires after 30 days** (`SYNONYMS_CACHE_TTL_DAYS`, env
    `MFETL_SYNONYMS_TTL_DAYS`), the same as PUG-View. `pipeline._fetch_cached(..., max_age_days)`
    writes syn60 entries in the `sources.cache` envelope; the props cache stays undated and permanent.
    The prefix is still syn60: an existing entry is a bare list, unknown age, never fresh, so the first
    run after this re-fetches every list once. Synonyms record no freshness; the export guard does not
    protect them.
  - **The cold case, measured at full size before relying on it** (the run-4 lesson): every syn60
    entry undated, all 770 PubChem CIDs (788 minus the 18 hand-modeled), through `mfetl fetch` against
    live PubChem: 6 batched POSTs (150 CIDs each, then 20), all HTTP 200, 6.1 MB of responses, 7.1 s
    for the whole stage. PubChem's X-Throttling-Control read Green on every response (request count
    and request time at most 1%). The warm re-run made 0 requests in 0.6 s. The weekly `run` job has
    no `timeout-minutes` (GitHub's 360-minute default); its `mfetl all` step took 94 s on 2026-09-12
    and 625 s on the 2026-09-09 PUG-View re-warm, so a synonym re-warm adds seconds. Locally the one
    undated syn60 file left is CID 24841, iodine's old record, which nothing fetches now.
  - **The 12-file split, restored once more.** The regeneration flipped the same 12 files and
    index.json; they were put back from `main` and checked identical before `b50cc75`.
    **Monday's scheduled run (2026-09-14) is the one that closes it:** CI's syn60 entries are all
    undated, so it re-fetches every list and should open and merge a data PR carrying those 12 as
    PubChem has them now. On pages that means doxycycline's line has Doxychel again where Vibramycin
    is, and pantoprazole's line has Zovanta where Protonix is, which takes "(Protonix)" off its title.
    That PR is the loop working, not a regression. Afterwards a local and a CI fetch can still disagree
    if upstream moves between them, but for at most one expiry window instead of forever; keep diffing
    synonym-only files against `main` before committing local data.
  - 380 tests (was 363), ruff clean. New tests pin both sides of the rule, replay levothyroxine's and
    carmine's lines, check that no committed page shows a name the filters drop, and pin the expiry:
    a dated entry, a hit at 29 days and a re-fetch at 31, an undated list re-fetched once in one pass,
    a CID with no synonyms kept as a dated miss, and `stage_fetch` passing the TTL for syn60 and none
    for props (that test caught the call site missing its argument before the commit).
- **The first weekly runs after it, recorded 2026-09-23: Sep 14 failed in the load, Sep 21 went
  green cold.** Code `6548a72`.
  - **Why Sep 14 failed (run 34838019124, issue #2):** stage 3, the Supabase load. The per-molecule
    synonym DELETE for molecule 3 (the child-table replace in `load_all`) came back **504 Gateway
    Timeout** from the proxy in front of PostgREST, 5 s after the DELETE before it succeeded, and
    nothing retried it: the loader called `.execute()` once, and postgrest's own `send_with_retry`
    covers only a GET answered 503 or 520. Stages 1 and 2 had finished, including the predicted
    re-fetch of all 770 synonym lists.
  - **Decision: a bounded retry on that call**, `supabase_loader._execute_idempotent`: 3 attempts,
    5 s and 10 s apart, on a dropped connection or a 429/500/502/503/504 from the gateway (the set
    `pubchem` retries). Each retry logs a warning and the third failure raises the gateway's own
    error, so the run still fails loudly. A database error is never retried. The DELETE is 1,085 of
    the load's 1,099 requests. The other 14 are not wrapped: the 9 upserts and the one read are
    idempotent and could take the same wrapper if one ever times out; **the 4 inserts must not** (a
    timeout does not say whether the rows landed, and a second insert could store them twice).
    `tests/test_load_retry.py` replays the 504 through the real postgrest client; with the old call
    site its load test fails on the exact Sep 14 error. 386 tests, ruff clean.
  - **Sep 21 (run 35595148008) was a full cold run, not a restore of Sep 14's cache.** GitHub
    deletes an Actions cache nobody has read for 7 days: Sep 14's was saved at 11:25 UTC, the Sep 21
    restore ran at 11:38 UTC and found nothing. So everything was fetched live: Wikidata (770),
    PubChem properties and synonyms (6 batched POSTs each, 150 CIDs a POST; synonyms took 9.4 s)
    and PUG-View (770 CIDs, 6 minutes); 8m23s in all, green. The PubChem client logs neither the
    X-Throttling-Control header nor its own retries, so the CI log cannot say what the throttle read
    or prove that no POST was repeated. **The cron sits on that 7-day boundary:** it is set for 06:00
    UTC, but GitHub started it at 11:24 and 11:38 these two Mondays, so whether a weekly run starts
    warm is decided by scheduler delay. Cold costs about 6 minutes and ~1,550 PubChem requests,
    inside the limits.
  - **The prediction above was half right.** The Sep 21 data PR (web #6; Production deployment of
    `a4939ba` succeeded; IndexNow 50 submitted, 50 accepted, audit exact at 1107) took the local
    Sep 12 lists for 5 of the 12 split files (cannabigerol, etomidate, montelukast, naproxen,
    natamycin), a third version for sodium-lauryl-sulfate (a stored name only; its page line did not
    change), and **kept CI's lists for the other 6** (coenzyme-q10, doxycycline, erythromycin,
    lisdexamfetamine, methadone, pantoprazole). Doxycycline still shows Vibramycin, and pantoprazole
    keeps Protonix and "(Protonix)" in its title. A live PubChem request from the Mac on 2026-09-23
    selects CI's version for both, so it was the local Sep 12 fetch that caught a state PubChem no
    longer serves. Either way the split is closed: CI and a local fetch agree today. The PR also
    carried the cold PUG-View refresh: LD50s for chlordiazepoxide (537 mg/kg, oral rat) and
    ketoconazole (702, oral mouse), both gaining the dose block; more GHS for carfentanil (joins
    health-hazard and irritant) and formic acid (joins environmental-hazard); and four synonym lines
    (clindamycin gains Cleocin, daraxonrasib Rasonque, oxytocin Pitocin, galactose's "cerebrose" is
    capitalised).
- **Sep 28 failed in the EXPORT, not the load: the guard refused an upstream Wikidata edit.**
  Run 36422607328 (schedule, started 12:33 UTC, warm cache `pubchem-raw-35912517716`), issue #3,
  failure heartbeat `be338df`. Stage 4, `snapshot_guard.check`, raised `SnapshotRegression`:
  `dicalcium-phosphate (summary): 'chemical compound CaHPO₄' -> 'chemical compound'`, fetched live.
  **Not the Sep 14 DELETE and not transient:** all 1,099 Supabase requests answered 2xx, the load
  finished (788 molecules), and the retry logged no warning. Zero PubChem POSTs (warm cache), so no
  throttle lines; the throttle log is still unexercised. **Cause, upstream and legitimate:** on
  2026-09-25 08:19 UTC a Wikidata editor reset Q414619's English description to "chemical compound"
  (the formula became a `mul` alias; ~20 languages in one sweep). Same item, same QID, one item for
  CID 24441, so `_choose_item` had nothing to choose. The guard's placeholder rule (run 6, MF-6)
  refuses that however fresh, and nothing a later run does changes the answer, so **every Monday
  would have failed the same way** until a person stepped in, over a field no page shows (the page
  reads `description` first; all 788 have one). The retry stays at 3 attempts: this was not the DELETE.
  - **Fix, `assemble._carried_summary`** (beside `_carried_svg`, fed by the same prior snapshot): when
    the canon row carries the SAME QID as the shipped record and only the placeholder, the shipped
    summary is kept and the run logs `summary: kept <slug>'s shipped ...`. A real new description
    still replaces the old one; a record that shipped the placeholder keeps getting it; a placeholder
    arriving with a DIFFERENT item (the 2026-09-09 shape) is left to the guard and still stops the
    run. It happens at assembly, so Supabase and `worlds.json` get the kept text too (on Sep 28 the
    load had already written the placeholder to Supabase before the export refused).
    `wikidata.is_placeholder` is now the one predicate that item selection, assembly and the guard
    share. `tests/test_summary_carry.py` (11) replays the day with the real values end to end through
    the export; with the carry disabled 3 of them fail, including the Sep 28 export. 453 tests, ruff
    clean.
  - **Local full-size check before the push:** `seed` (Wikidata live, 770), `fetch`, `transform`, then
    the guard read-only against the committed snapshot. The carry fired for dicalcium phosphate only;
    no summary or QID regression. The guard did flag chlordiazepoxide's and ketoconazole's LD50s: this
    Mac's PUG-View cache is from Sep 12 and predates the Sep 21 CI refresh that found them (the guard
    catching a stale local cache, as built; CI's cache has both). One real upstream summary edit rides
    in the next data PR (folic acid, `vitamin B9; nutrient essential for DNA synthesis` ->
    `compound, a vitamer of "vitamin B9"`, not displayed). `data/` restored from HEAD afterwards.
  - **Worth knowing:** 29 shipped summaries read "chemical compound" plus a qualifier, and phenol's
    (`chemical compound C6H5OH`) has exactly the shape that editor cleaned up. If it goes the same way,
    the carry keeps it and the run stays green.
  - **The week redelivered the same evening** (fix `aeda8bf`, pushed; no workflow ran on the push).
    Dispatch run 36492622117 (22:28 to 22:33 UTC), all green. `run` 2m43s: restored the failed run's
    cache (`pubchem-raw-36422607328`, so Wikidata still fresh from 12:34 and not re-read), zero PubChem
    POSTs so still no throttle lines, the carry line for dicalcium phosphate and no other, load 788
    with every request 2xx and no retry warning (Supabase's summary for it is back to the shipped
    text), week 40 compiled, refresh commit `ae951d8` (canon.parquet, featured.json, meta.json
    `2026-09-28`, folic-acid, tocopherol), cache saved `pubchem-raw-36492622117`. `sync-web` opened web
    PR #7 (4 files), waited for `ci` run 36492928295 (`verify` success on `70a988ba`), squash-merged as
    web `55ca81b`. `all-clear` closed issue #3 with its comment; `alarm` skipped. Production deployment
    6722084901 succeeded; IndexNow run 36493134081: base `4e3a187`, 1108 -> 1108, 4 changed, 4
    submitted and 4 accepted (HTTP 200), audit exact, tag moved to `55ca81b`. **Live:** `/` shows
    "Week 40, 2026 · from September 28, 2026" Quinine; `/molecule-of-the-week` lists weeks 40 and 39;
    the feed (200, `application/rss+xml`) has two items, W40 Quinine and W39 Cinnamaldehyde. What moved
    on pages besides the week: folic acid's synonym line (vitamin Bc leaves, PteGlu joins) and
    tocopherol's (Wikidata's alias "methyltocols" leads); folic acid's new Wikidata summary is stored
    but not displayed. The Oct 5 cron re-reads Wikidata (the 6-day TTL lapses Oct 4 about 12:34) and
    should restore this cache warm.

## Molecule of the week (2026-09-23) — DEPLOYED 2026-09-23 (`e09a853`, then heartbeat `5cc2a62`)
A weekly pick for the home page, `/molecule-of-the-week` and its RSS feed (the web half is in the
web CLAUDE.md). A reason to come back and a thing to share.
- **Seed: `sources/seeds/featured.yaml`**, a `weeks:` list, one entry per ISO week 1 to 53: `slug`
  plus an optional one-line `hook`. All 53 are filled and all 53 have a hook; the seasonal ones are
  anchored to the 2026-27 calendar (pumpkin spice W39, Halloween candy W44, Thanksgiving W48,
  Christmas tree scent W52, Valentine's chocolate W06, spring pollen W15, sunscreen W22, chili
  W30, back-to-school coffee W35), each entry's comment giving its first Monday. The same week
  number repeats every year; W53 exists only in some ISO years (2026, 2032, 2037) and is skipped
  in the rest.
- **The compiler, `transform/featured.py::compile_queue`**, runs in `stage_export` against the
  catalog being exported and fails the run listing every problem, like `why_it_matters`: all 53
  weeks exactly once; an unknown slug; a slug twice; **a molecule that appears twice in the
  catalog**, meaning two records sharing an InChIKey skeleton (17 such pairs today: estradiol and
  estradiol-medication, vitamin-b12 and cyanocobalamin, omeprazole and esomeprazole, but also
  real stereoisomer pairs like glucose and galactose, which the rule also keeps out); a
  hand-modeled macromolecule or no structure; no why_it_matters line; a row held in
  `deferred_rows.csv` (by CID or name); a hook outside 40 to 170 characters, not one line, not
  ending in a full stop, with an em or en dash, or matching the /vs advice-and-dosing patterns
  (`relationships._ADVICE_PATTERNS`). A failed compile writes nothing. No held or recreational
  (drugs-wing, gated) row is in the catalog, so none can be picked.
- **Selection is deterministic and stateless.** The featured molecule is the entry for the ISO
  week of the snapshot's own `refreshed` date, never a clock: `export()` renders featured.json for
  the candidate date and compares it like every other file, so featured.json always names the
  week of the date meta.json ends up with (tested across a sequence of runs). The history is
  rebuilt from the seed every run, from `START_WEEK` = 2026-W39 (Monday 2026-09-21, the launch
  week) to the current week, so **editing a week that has already run rewrites the archive and
  re-issues its RSS item**; the seed's header says so.
- **`data/snapshots/featured.json`**: `{start, current, weeks}`, `weeks` newest first with
  `weeks[0] == current`; each item `week` ("2026-W39"), `iso_year`, `iso_week`, `monday`
  (YYYY-MM-DD), `slug`, `title`, `formula`, `line` (the hook, else the why_it_matters text),
  `line_source` ("hook" or "why_it_matters"), `confidence` from_source, `source` "MoleculeFinder
  curated". 819 bytes today, about 370 more per week (about 20 KB after the first year).
- **Every Monday run now changes the snapshot and opens a data PR.** A new ISO week always
  changes featured.json, so meta.json's `refreshed` moves every week too (the "Data refreshed" line
  on every molecule page now advances weekly, since the weekly run re-reads Wikidata anyway), the
  weekly PR is never empty, and every Monday is a Vercel deploy plus an IndexNow ping for `/` and
  `/molecule-of-the-week`. **The heartbeat still exists, twice.** The no-change branch of `commit
  snapshot` now fires only for a second run in the same ISO week (a dispatch), and is not dead
  code. And a new `heartbeat after a failed run` step (`if: failure()`) resets to `$GITHUB_SHA`,
  throws away whatever the failed run half-wrote, and commits only `data/LAST_CHECK`, because a
  seed error nobody fixes would otherwise fail, and commit nothing, every week until GitHub
  disabled the public repo's cron and the watchdog with it. The job still fails, so the alarm
  still fires.
- `mfetl featured` built today's file offline from the committed snapshot: 2026-W39,
  cinnamaldehyde, archive of one week, meta.json untouched (still 2026-09-21, the same week).
- Tests: `tests/test_featured.py` (42: every rule, the committed seed against the committed
  snapshot, the week arithmetic across 2026-W53 and a year without one, the clock never read, a
  same-week re-run byte-identical, a new week moving exactly featured.json and meta.json) and
  `tests/test_etl_workflow.py` (the workflow's own shell run against a throwaway repo and a bare
  origin: the refresh path, the no-change heartbeat, the failed-run heartbeat publishing only
  LAST_CHECK, and the step wiring). 433 tests, ruff clean. Mutation-checked: disabling the twin
  rule, or leaving featured.json out of the change decision, fails the matching tests.
- **Three small things from the Sep 23 review, same branch:**
  - **`all-clear` job in etl.yml** (`3aae86e`), the mirror of `alarm`: `needs: [run, sync-web]`,
    runs only when both succeed, `issues: write`, and closes every open `refresh-failure` issue
    with a comment naming the run ("Run <url> (schedule, date) went green..."). Issue #2, the Sep 14
    failure, stayed open through the green Sep 21 run until it was closed by hand on 2026-09-23.
    It cannot fail a green run: no open issue is a clean exit, and a list or close failure is a
    `::warning::`. Tested with a stub `gh` on PATH running the step's own script.
  - **PubChem logs its throttle** (`939ffd4`). Each batched properties or synonyms POST logs one
    line, `pubchem POST synonyms: 150 CIDs from 2244, HTTP 200 in 1.3 s, X-Throttling-Control:
    Request Count status: Green (0%), ...` (logger `mfetl.pubchem`), and the retry decorator logs a
    warning before every retry. Never per PUG-View GET. A cold run's log now says what the throttle
    read and whether any POST was sent twice (a repeated batch prints a second line with the same
    first CID). Tested through the real decorator with real `requests.Response` objects.
  - The web CLAUDE.md's prediction that pantoprazole's title would lose "(Protonix)" is corrected in
    place there: it keeps it.
  - 442 tests after these (433 + 5 PubChem log + 4 all-clear), ruff clean.
- **Deploy order (for the separate deploy prompt):** push this repo's `main` before or together
  with web `main`, and before the next Monday cron (06:00 UTC scheduled, in practice about 11:30).
  Pushing here deploys nothing by itself. `sync-web` copies the snapshot WHOLE, so a Monday run on
  the old code would ship a snapshot without featured.json and its data PR would remove the web's
  copy (the block, the archive and the feed would then render nothing until this code is merged).
  With both merged, the first Monday run moves to week 40 and opens the data PR on its own.
- **Deployed 2026-09-23, on Garrett's word, with one seed fix first** (`e09a853`): week 46's hook
  (aspirin) now says willow bark carries salicin, which the body turns into salicylic acid, the
  compound aspirin is made from. Week 46 is outside the exported window, so `mfetl featured` rebuilt
  featured.json byte-identical (`cmp` against HEAD); 42 featured tests, then all 442, pass; ruff
  clean. `main` fast-forwarded `2f29561` -> `e09a853` and was pushed before web `main`; no workflow
  runs on push. **The pre-Monday dispatch** (run 35912517716, 19:55 UTC) was green in about 90 s: the
  Sep 21 cold run's cache restored (`pubchem-raw-35595148008`), nothing fetched, so **zero PubChem
  POSTs and zero X-Throttling-Control lines** (the throttle log is still unexercised; the first run
  that POSTs is the first cold one, or the first after about Oct 21); Supabase load 788 molecules, 0
  re-keyed; CI compiled the corrected seed (53 weeks, 53 with a hook); export identical, so heartbeat
  `5cc2a62` touching only `data/LAST_CHECK`; `sync-web` "web repo snapshot already identical — no PR
  needed"; `all-clear` "no open refresh-failure issue, nothing to close"; `alarm` skipped. A fresh
  cache was saved as `pubchem-raw-35912517716`, so the Sep 28 cron should restore it warm.

## Trust run 2 (2026-10-24): a label's other ingredients, named. DEPLOYED 2026-10-24 with trust run 3 (ETL `b7b034d`)
Item 2 of the agreed trust list (company CLAUDE.md, "Trust run 1"). Branch `trust-2026-10` from `main` `5e5c379`:
code `4a6e478`, data `e33f26e`, plus this notes commit. Never pushed.
- `products.compile_products` stored `not_in_catalog = len(unmatched)`. It now stores the names it already had
  (`products._not_in_catalog`): `{"name", "role"}` in label order, actives first, one per name, as the label prints
  them; a name a listed molecule already carries is left out (none does today). `actives_not_in_catalog` unchanged;
  the list's actives are exactly it. The gate, the matching and every other field are untouched. Display only.
- Tests: 735 (733; `test_products.py` 46: the list's order, actives first, dedupe, the left-out name, a world
  product carries no list). Ruff 130, the same as `main`; the two changed files clean.
- Pinned build (`sync-inputs` 17122735c9f95167, all three keys blanked), exit 0: the ONLY change under `data/` is
  `not_in_catalog` in `products.json`, on the 351 DailyMed products: **339 list 2,482 names** (102 active, 753
  distinct), 12 an empty list. Every other field, `products_gate.json`, the queue and every molecule file identical.
- **Found, not fixed (needs Garrett):** 23 of the listed names are the exact title of an MF molecule, 153 rows on 118
  pages (polysorbate 80 on 45, xanthan gum 33, shellac 17, gelatin 10, maltodextrin 9, acesulfame potassium 7,
  tirzepatide 2, ...). The code match missed them: hand-modelled molecules have no UNII (xanthan gum, gelatin,
  carrageenan, pectin, agar, guar gum), a label's form has its own UNII (polysorbate 80, lactic acid, the salts), and
  PubChem lists tirzepatide's UNII bare (`OYN3CCI6QE`), not as `UNII-OYN3CCI6QE`, so `pubchem.uniis` never reads it.
  So the live Mounjaro page already says "tirzepatide, is not yet in MoleculeFinder" beside an existing
  `/m/tirzepatide`. The fix belongs here (read bare UNII synonyms; give the hand-modelled records their UNIIs or hand
  aliases, each checked), and it changes product pages and possibly the gate, so it is a run of its own.
- **Deploy: ETL `main` FIRST, then web `main`, both before Monday 2026-10-26's weekly run** (it would otherwise
  rebuild products.json with the count, and the web would show no names until the next deploy). Nothing deploys from
  this repo.

## Trust run 4 (2026-10-25): the Deadliest board says first what it is not. DEPLOYED 2026-10-25 (`e400a54`)
**DEPLOYED about 17:20 UTC on Garrett's word**: ETL `main` fcb4aa9 -> `e400a54` first (with `80f52e3`; deploys nothing),
then web `main` -> `619508b`; IndexNow 0 new, 3 changed, 3 accepted, audit exact; the sentence verbatim live on
`/best/deadliest` and `/best` (company CLAUDE.md "Trust run 4"). Monday 2026-10-26's weekly run is the first on this
code. Note: the page's meta description puts the web's leader line ("Colchicine leads the Deadliest board at ...")
before this sentence (web `lib/seo.ts`), so a search snippet may cut it. **Fixed the same day in the web only**
(`0a2a7b7`): the meta description is Garrett's shorter sentence plus the leader, 140 characters; this board text unchanged.
The agreed trust list's item 4 (item 3, the home news block, is web only; company CLAUDE.md "Trust run 4"). Commits
`fad4696` (code), `3a1bb49` (data). `transform/leaderboards.py`: the deadliest board's description now leads with "A
ranking of pure substances by one animal measurement, not of how dangerous any food, drink, medicine or product is to a
person." Pinned build (keys blanked): exactly `leaderboards/deadliest.json` and `leaderboards/index.json` change; 756
tests; ruff 131. Deploy: ETL `main` first, then web `main`, before Monday 2026-10-26.

## Trust run 6 (2026-10-25): every atom in every drawing has its CPK colour. DEPLOYED 2026-10-25 (`5eda549`)
**DEPLOYED 2026-10-25 about 21:04 UTC on Garrett's word**: ETL `main` e400a54 -> `5eda549` first (with the notes
commits `7e558e1`, `d621886`; deploys nothing, no workflow ran), then web `main` -> `03c1ab2`, GitHub deployment
`7319142561` Production success. IndexNow 169 changed (160 /m, 7 /vs, /, /classroom), 169 accepted, audit exact; live
checks and Lighthouse in the company CLAUDE.md, "Trust run 6". **Monday 2026-10-26's weekly run is the first on this
code:** every key is current, so it carries all 896 drawings forward on Linux (the snapshot sweep test fails the run if
a drawing ships black or a key is stale); a NEW molecule is drawn fresh with the full palette. Its Supabase load also
carries the new SVGs into the `molecule` table (this Mac's build skipped the load, keys blanked).
**The finding** (trust run 5): `structures.CPK_HEX` listed ten elements and RDKit drew every other atom label black,
nearly invisible on the navy panel: 160 of 896 drawings, 66 entirely black (the element pages, `/m/aluminium` a faint
"Al"), 94 in part (88 with a black label, calcium carbonate's Ca, acesulfame potassium's K, the dyes' Na; and 6 whose
only black was RDKit's **radical electron dots**: carbon, fluorine, nitric oxide, phosphorus, sulfur, PMMA). 67
elements outside the ten occur in the catalog (Na 36 molecules, K 13, Ca 12, Mg 11...). **Garrett's ruling:** the full
standard CPK table, so each element's colour keeps meaning something (Color-as-Information), one light fallback only
for an element outside it. Branch `rdkit-cpk-2026-10`: code `35d4457`, data `5eda549`.
- **`CPK_HEX`**: the ten brief hues kept exactly (the 736 drawings that use only them do not change), plus Jmol's CPK
  colour for every other element 1 to 109 (parsed from `jmol.sourceforge.net/jscolors/jmol_constants.js`, Jmol 12.1.15
  rev 14469, not typed from memory). **Contrast** (WCAG, graphical objects, 3:1 on `PANEL_HEX` #0e2233, the lightest
  surface a drawing sits on; the stage is #09161e): 15 Jmol colours fall short and are lightened by HSL lightness only,
  the minimum to reach 3:1, hue within 0.3 degrees and saturation kept, each noted beside its entry: K #8f40d4 -> #9041d4
  (2.97 -> 3.01), Rb #702eb0 -> #8c46cf (2.09 -> 3.00), Pd #006985 -> #007493 (2.59 -> 3.03), Cs #57178f -> #923adf
  (1.49 -> 3.01), Os #266696 -> #296fa3 (2.64 -> 3.01), Ir #175487 -> #1e6eb0 (2.05 -> 3.02), Pb #575961 -> #686a72
  (2.32 -> 3.01; the plain lightness search rounded to a hue 3 degrees off on this near grey, so the nearest hex at hue
  228.0 was taken), At #754f45 -> #8d5f53 (2.29 -> 3.01), Fr #420066 -> #a200fa (1.10 -> 3.02), Fm #b31fba -> #b51fbc
  (2.95 -> 3.00), Md #b30da6 -> #be0eb1 (2.72 -> 3.00), No #bd0d87 -> #c80e8f (2.76 -> 3.02), Lr #c70066 -> #d0006a
  (2.79 -> 3.00), Rf #cc0059 -> #d2005b (2.87 -> 3.00), Db #d1004f -> #d40050 (2.95 -> 3.02). Iodine is one of the kept
  ten (#c79af0, 7.19:1), so it needed nothing. In the catalog the adjusted ones are K, Cs, Fr, Ir, Os, Pb, Pd, At.
- **`FALLBACK_HEX` #ffffff** for 110 to 118 (past Jmol's table) and a dummy atom: RDKit palette keys -1 (default black)
  and 0 (near black). No catalog molecule uses it today.
- **Radical dots:** RDKit draws them black whatever the options say (checked every colour option it has). `svg_for` now
  ends with `_paint`: any black left on an atom (`class='atom-N'`, never a bond) takes that atom's colour.
- **`RECIPE_VERSION` 2026-10-25.1, and a repaint instead of a redraw.** rdkit on this Mac is now **2026.09.1**, and it
  lays out **406 of the 896 shipped drawings differently** from the release that drew them (benzene mirrored top to
  bottom; caffeine happens to match). A literal redraw would have flipped or rearranged about 400 structures for a
  colour fix. So `assemble._carried_svg` repaints a drawing whose key is a `structures.RECOLOURABLE` recipe's
  (2026-09-07.1) with `structures.recolour` (black atom elements only), and stores the new key. **Proven on all 896:**
  repainting a 2026-09-07.1 drawing made here equals a fresh 2026-10-25.1 draw made here, byte for byte (896 equal, 0
  differ). A palette-only change in future: add the outgoing version to `RECOLOURABLE`. A layout change (draw options,
  canvas): bump without it, and expect every drawing to redraw on whatever machine runs it.
- `tests/test_structure_palette.py` (36): the ten kept, every element 0 to 118 at 3:1 or more, each lightened entry
  needed it and kept its hue, the comments name exactly the lightened Jmol colours; aluminium, calcium carbonate,
  acesulfame potassium, potassium iodide, caffeine and nitric oxide carried from their SHIPPED drawings
  (`tests/fixtures/structures-2026-09-07.1/`) and drawn fresh: no black, each element in its table colour; repaint
  equals a fresh draw; caffeine byte-identical with only its key moved; a repainted drawing keeps every coordinate; and
  a sweep of the committed snapshot (no black, every atom colour 3:1 or more, every key current, so the Linux weekly run
  carries the drawings forward instead of redrawing them). **792 passed, 1 skipped** (756 before); ruff 131 (unchanged;
  the new files clean).
- **Pinned build** (`mfetl sync-inputs` 17122735c9f95167, then `mfetl all`, all three keys blanked), exit 0: **896
  molecule files change, `structure_svg_key` on all 896, `structure_svg` on exactly 160** (all 66 and all 94); no other
  field, no other file (meta.json, products, boards, seed files identical). Version not embedded in the SVG itself.

## The forms ruling (2026-10-25). DEPLOYED 2026-10-25 (ETL `fcb4aa9`, web `96b2786`), built as `94a4122` code, `81bbb59` data
**DEPLOYED about 01:03 UTC on Garrett's word**; IndexNow 11 new, 203 changed, 214 accepted, audit exact; live 19 of 19
checks (company CLAUDE.md). Monday 2026-10-26's weekly run is the first on this code.
Garrett, 2026-10-25: "yes on linking cellulose, starch, and lecithin and other chemically identical materials". This
answers the open question at the end of trust run 3. Thirteen codes join `unii_aliases.yaml` `aliases`, under a comment
quoting the ruling: microcrystalline cellulose (OP1R32D61U, and the 101 and 102 grades) and powdered cellulose ->
cellulose; corn, potato, rice starch -> starch; soybean lecithin -> lecithin; sorbitol solution (the FDA's specified
substance) -> sorbitol; dibasic calcium phosphate dihydrate, disodium phosphate dihydrate and heptahydrate, sodium
carbonate monohydrate -> their salts. **How they were found:** every `not_in_catalog` code whose FDA display name (or
label name) is a catalog molecule's title or Wikidata name plus only form, grade, source, purity or hydration words; then
a looser pass listing every label name containing a molecule's name, read by hand. **Left out on purpose** (chemically
altered, a different chemical): croscarmellose sodium, hydroxypropyl cellulose (all grades), low-substituted HPC,
cellulose acetate, sodium starch glycolate, aluminum starch octenylsuccinate, alpha-tocopherol acetate, sucrose stearate,
titanium dioxide (not titanium), "sodium phosphate" unspecified (mono, di or tri). `tests/test_unii_index.py` pins both
sides. Pinned build: 255 rows gained on 182 pages, 0 lost; 424 product pages (413; 11 new); 18 molecule files by
`products` alone; `unii_index.json` 1,131 codes. 756 tests, ruff 131. **A new form found later is one more line here,
under the same rule; a chemically altered material never is.** Deploy: ETL `main` first, then web `main`, before Monday.

## Trust run 3 (2026-10-24): the label join reads the FDA's own UNII table. DEPLOYED 2026-10-24 (ETL `b7b034d`, web `9f8bc4a`)
**DEPLOYED 2026-10-24 about 23:30 UTC on Garrett's word**, with trust runs 1 and 2 and web `indexnow-dataset-2026-10`.
ETL `main` f4fac9f -> `b7b034d` (with `5e5c379`; deploys nothing, no workflow ran); web `main` 45808d9 -> `9f8bc4a`,
GitHub deployment `7305985915` Production success; IndexNow run 40143070998: 1,678 -> 1,686, 8 new, 417 changed, 425
accepted, audit exact. Live: 34 of 34 checks (the company CLAUDE.md lists them). **Monday 2026-10-26 is the first
weekly run on this code**: it downloads the FDA table (`data/raw_cache/fda/`), re-reads the 897 synonym lists as
`unii2` (6 POSTs) and asks about 790 parents by CID (`pubchem/parent-<cid>.json`, about 3 minutes); after that it is
warm. If its data PR goes red on `tests/test_unii_index.py` or the web sweep, a refreshed label is showing a molecule
as "not yet": add the code to `unii_aliases.yaml` (a form) or `substances` (the molecule's own code), never a name rule.
Closes the gap trust run 2 found: 23 label ingredients shown as "not yet MoleculeFinder molecules" that ARE
MoleculeFinder molecules (153 entries on 118 pages; Mounjaro's live "tirzepatide is not yet in MoleculeFinder"
beside `/m/tirzepatide`). Garrett's ruling: fix the matching, never soften the line; a label ingredient is matched by
CODE only. Commits `e9e7ba3` (code), `fcb572e` (data), plus this notes commit, on top of trust runs 1 and 2.
Never pushed.
- **Why they missed (diagnosis, all 23).** (a) PubChem lists the molecule's UNII bare or under another CID, 5:
  acesulfame potassium and potassium (bare), sodium metabisulfite and sodium bisulfite (PubChem lists no synonyms;
  the FDA links the code to another CID with the same InChIKey), tirzepatide (bare; the FDA registers the protein
  with no PubChem CID). (b) A hydrate or unspecified form PubChem has no parent for, 5: magnesium carbonate
  (0E53J927NA is the hydrate, CID 71376; the record is magnesite), calcium chloride (the dihydrate), sodium acetate
  (the trihydrate), zinc sulfate and lactic acid ("UNSPECIFIED FORM", no PubChem CID at all); PubChem's parent
  lookup answers "no CIDs for the given type" for an inorganic hydrate. (c) Neither PubChem nor the FDA links the
  code to a compound, 13: the six hand-modelled polymers and mixtures (xanthan gum, gelatin, carrageenan, agar, guar
  gum, pectin: no PubChem compound), five the FDA registers as a polymer or mixture without a PubChem CID whose
  PubChem page lists no UNII (polysorbate 80, shellac, maltodextrin, hyaluronic acid, butylated hydroxyanisole),
  pembrolizumab (CID 254741536 lists no synonyms) and minoxidil (the FDA draws the other tautomer, InChIKey
  ZFMITUMMTDLWHR vs PubChem's ZIMGGGWCDYVHOY, no CID; PubChem's 261 synonyms hold no UNII). The same reading also
  explained 102 label codes whose parent lookup (`compound/name/UNII-<code>`) had come back empty: PubChem had no
  such synonym, not no parent. The table, one row per name (label code; the record; cause; how it is reached now):

  | Label name (code) | Record | Cause | Why the code match missed it | Reached now by |
  |---|---|---|---|---|
  | acesulfame potassium (23OV73Q5G9) | acesulfame-potassium, CID 11074431 | a | PubChem lists the code bare; the parent lookup reached the acid, CID 36573 | FDA table, CID |
  | potassium (RWP5GA015D) | potassium, CID 5462222 | a | PubChem lists the code bare | FDA table, CID |
  | sodium metabisulfite (4VON5FNS3C) | sodium-metabisulfite, CID 51000477 | a | PubChem lists no synonyms; the FDA links the code to CID 656671, same InChIKey | FDA table, InChIKey |
  | sodium bisulfite (TZX5469Z6I) | sodium-bisulfite, CID 656672 | a | PubChem lists no synonyms; the FDA links the code to CID 18000336, same InChIKey | FDA table, InChIKey |
  | tirzepatide (OYN3CCI6QE) | tirzepatide, CID 156588324 | a | PubChem lists the code bare; the FDA registers the protein with no CID | PubChem's bare code, listed by the FDA table |
  | magnesium carbonate (0E53J927NA) | magnesium-carbonate, CID 11029 | b | the code is the hydrate (CID 71376); no PubChem parent; the record is magnesite | alias |
  | calcium chloride (M4I0D6VV5M) | calcium-chloride, CID 24854 | b | the dihydrate (CID 24844); no PubChem parent; the record is the anhydrous salt | alias |
  | sodium acetate (4550K0SC9B) | sodium-acetate, CID 517045 | b | the trihydrate (CID 23665404); no PubChem parent; the record is the anhydrous salt | alias |
  | zinc sulfate (89DS0H96TB) | zinc-sulfate, CID 24424 | b | "UNSPECIFIED FORM", no PubChem CID at all | alias |
  | lactic acid (33X04XA5AT) | lactic-acid, CID 612 | b | "UNSPECIFIED FORM", no PubChem CID; the record is DL-lactic acid | alias |
  | polysorbate 80 (6OZP39ZG8H) | polysorbate-80, CID 5281955 | c | the FDA registers a polymer with no PubChem link; PubChem's CID lists no UNII | substance |
  | shellac (46N107B71O) | shellac, CID 6850749 | c | structurally diverse, no PubChem link; PubChem's CID lists no UNII | substance |
  | maltodextrin (7CVR7L4A2D) | maltodextrin, CID 62698 | c | polymer, no PubChem link; PubChem's CID lists no UNII | substance |
  | hyaluronic acid (S270N0TRQY) | hyaluronic-acid, CID 24759 | c | polymer, no PubChem link; PubChem's CID lists no UNII | substance |
  | butylated hydroxyanisole (REK4960K2U) | butylated-hydroxyanisole, CID 24667 | c | the FDA registers the two-isomer mixture with no PubChem link; PubChem's CID lists no UNII | substance |
  | pembrolizumab (DPT0O3T46P) | pembrolizumab, CID 254741536 | c | protein, no PubChem link; PubChem lists no synonyms at all | substance |
  | minoxidil (5965120SH1) | minoxidil, CID 4201 | c | the FDA draws the other tautomer (InChIKey ZFMITUMMTDLWHR), no CID; PubChem's 261 synonyms hold no UNII | substance |
  | xanthan gum (TTV12P4NEE) | xanthan-gum, hand-modelled | c | no PubChem compound; the FDA registers it with no PubChem link | substance |
  | gelatin (2G86QN327L) | gelatin, hand-modelled | c | as xanthan gum ("GELATIN, UNSPECIFIED") | substance |
  | carrageenan (5C69YCD2YJ) | carrageenan, hand-modelled | c | as xanthan gum | substance |
  | agar (89T13OHQ2B) | agar, hand-modelled | c | as xanthan gum ("AGAR, UNSPECIFIED") | substance |
  | guar gum (E89I1637KE) | guar-gum, hand-modelled | c | no PubChem compound on the record (the FDA links CID 44134661, which the record does not carry) | substance |
  | pectin (89NA02M4RX) | pectin, hand-modelled | c | as xanthan gum | substance |
- **`sources/fda_unii.py`, the FDA's UNII table** (`precision.fda.gov/uniisearch/archive/latest/UNII_Data.zip`,
  14.5 MB, redirects to the newest edition; checked 2026-10-24: `UNII_Records_4Aug2026.txt`, tab-separated,
  171,912 rows, no UNII twice, 126,672 with a PubChem CID, 129,398 with an InChIKey; the enclosed README documents
  the columns). Parsed BY COLUMN NAME (UNII, DISPLAY_NAME, PUBCHEM, INCHIKEY, SUBSTANCE_TYPE; a renamed column or
  a missing records file fails the run) into `data/raw_cache/fda/unii-records-v2.json` (13.7 MB, a dated envelope
  like the labels; the prefix is bumped when the kept columns change), so it travels with the snapshot through the
  inputs artifact; re-read weekly (`FDA_UNII_CACHE_TTL_DAYS`, 6). Registered `fda_unii`, `public_domain` (FDA website
  policies: "in the public domain and may be republished, reprinted and otherwise used freely"); `sources.json`
  carries it. A pipeline `compile_products` with a label seeded and no table in the cache REFUSES.
- **The molecule side of the join (`products.unii_index`, `_record_codes`)** is now a UNION of the FDA's table and
  PubChem's lists, each with codes the other lacks: a code names a record when the FDA's PubChem CID for it is the
  record's (`cid`, 788 codes), when the FDA's InChIKey is the record's exactly (`inchikey`, 22; the FDA links some
  substances to another CID of the same structure), when PubChem's synonym list for the CID carries it (`pubchem`,
  160: a `UNII-` entry, or a BARE code the table lists, never a bare code it does not, which is a screening-library
  id of the same shape), or when the hand list's new `substances` section says so (`substance`, 16; see below). A
  code two records claim goes to the one holding it by the FDA's own link or the hand list when exactly one does,
  else to neither. `pubchem.uniis` now keeps bare codes (cache prefix `unii` -> `unii2`, re-read once, 6 POSTs).
  864 of 915 molecules hold a code (was 789 with any PubChem `UNII-` entry). `data/seed/unii_index.json`
  (committed, one line per code: slug, how, the FDA's display name) is the index, 1,118 codes.
- **A code the FDA registers as a source-defined substance (ISO 11238 `structurallyDiverse`: cochineal, corn syrup)
  joins no record by any automatic route**, only by the hand list. Found while measuring: the FDA links COCHINEAL
  to carminic acid's CID (it would have put carmine on Hysingla's page, and Garrett ruled in run 6 that cochineal
  is not a name for carmine) and CORN SYRUP to a glucose whose parent is glucose (6 pages would have listed
  glucose). Every other non-chemical link checked is right and kept: semaglutide on Ozempic and Wegovy (protein),
  carboxymethylcellulose (polymer), permethrin and doxepin (isomer mixtures), the 19 "MENTHOL, UNSPECIFIED FORM"
  rows (mixture) that run C1 designed the skeleton rule for.
- **The by-rule route (`parent_index`)** asks PubChem for a label code's parent BY THE FDA'S CID
  (`pubchem.cid_parents`, cached `pubchem/parent-<cid>.json`) when the table has one, else by the `UNII-` synonym
  as before; the FDA's InChIKey skeleton counts beside the parents' (L-lactic acid reaches DL-lactic acid with no
  parent at all); a hand alias is FINAL (it was a gap-filler): without that, potassium citrate monohydrate on
  Halls would list citric acid. An alias on an ACTIVE's own code applies after its moiety reached nothing; the two
  rules never do (zinc acetate stays zinc acetate, not acetic acid).
- **The hand list (`sources/seeds/unii_aliases.yaml`)** has two sections now. `substances` (the molecule's OWN
  code; the FDA display name IS the molecule): the 13 of cause (c) above plus casein, fibrin and hemoglobin (hand-
  modelled, exact FDA names) and ivermectin (the FDA registers the B1a/B1b mixture with no PubChem link; the code
  came up on Stromectol, a page that now passes the gate). `aliases` gains eight forms: calcium chloride dihydrate,
  magnesium carbonate hydrate, sodium acetate trihydrate, potassium citrate monohydrate, sodium borate (the
  decahydrate, for borax), carboxymethylcellulose sodium ("cellulose gum", the salt of the polymer), and zinc
  sulfate and lactic acid unspecified forms; the last two of those surfaced through the web's name sweep, which is
  what it is for. Every code is checked at build time (a slug must be a molecule; a code must be in the table) and
  `tests/test_unii_index.py` checks each substance's FDA display name against its molecule's title.
- **A label that gives no UNII for an ingredient is not matched at all** (gate reason "the label gives no UNII code
  for N ingredient(s) (...)"). Keflex's label names Cellulose, D&C Yellow No. 10, FD&C Blue No. 1, FD&C Yellow No. 6
  and silicone with no codes, three of them molecules here under other titles; nothing can match a code-less row,
  and the page would have called them not MoleculeFinder molecules on no evidence. Keflex is the only such label.
- **Every matched row and every `not_in_catalog` entry carries `unii`**, the code it was decided on (a row: the
  ingredient's own or its moiety's; an entry: the label's code, None when the label gives none). Display only.
- **Pinned rebuild** (`sync-inputs` 17122735c9f95167, all three keys blanked, exit 0; the artifact predates run C1,
  so the 790 parent lookups were fetched once, plus the table and the 6 `unii2` POSTs): **all 153 entries moved
  into the linked lists; 268 label rows gained on 164 pages (231 direct, 4 parent, 30 alias, 3 moiety), 0 lost**;
  one label name moved molecule (Halls' potassium citrate: citric acid -> potassium citrate, the alias); 18 rows
  keep their molecule and are now direct. **413 product pages (405): flagyl, flonase-allergy-relief, foundayo,
  pamelor, strattera, stromectol, supergoop-unseen-sunscreen-spf-50 and zomig pass the gate** (62 fail, was 70;
  keflex held as above); none gone. Molecules with "Found in these products" 424 -> 446 (22 gain it: tirzepatide,
  pembrolizumab, polysorbate-80, xanthan gum, borax... and metronidazole, fluticasone propionate, nortriptyline,
  orforglipron, ivermectin through the new pages). **47 molecule files change, by `products` alone**; the other
  changes are products.json, products_gate.json (new `matched_by_code` and `unii_index` counts), the queue,
  sources.json and the new unii_index.json; meta.json unchanged (2026-10-21). Mounjaro: 7 molecules, tirzepatide
  its active, no "not yet" sentence, two names left (sodium phosphate dibasic heptahydrate, hydrochloric acid).
  Advil 12 molecules and 14 names (shellac and gelatin moved); CeraVe 13 and 35 (titanium dioxide active first);
  Sun Bum 8 and 55. The two directions are one fact (2,635 pairs each way). Gate totals: 1,861 rows by the
  ingredient's code, 155 by its moiety, 127 parent, 32 skeleton, 116 alias.
- **Tests: 755 (735)**: `test_fda_unii.py` (7: the parser by column name, the refusals, the Table, the dated cache,
  the registry, PubChem's bare codes), `test_unii_matching.py` (10: the union and the authority rule, bare codes,
  substances, the source-defined guard, the FDA skeleton, alias wins, an alias on an active's own code, parents by
  the FDA's CID, rows carry codes, the code-less gate, the refusal without a table, the index file) and
  `test_unii_index.py` (5, over the committed snapshot and index: no name shown as not in the catalog carries a
  code that reaches a molecule, with ONE exemption by design, an active whose own code resolves only by rule;
  every matched row's code reaches its molecule; no such name is a molecule's title; the hand list is in the
  index with its names). `test_products.py` fixtures now hold codes as PubChem writes them (`UNII-...`). Ruff 131
  = main's 130 + one C408 for the registry entry, in that file's established `dict(...)` style.
- **The weekly run from the first Monday after deploy:** downloads the FDA table (14.5 MB) each week, re-reads
  the 897 synonym lists once (6 POSTs) and asks about 790 parents by CID once (3 minutes), then is warm. The
  artifact grows by about 7 MB (the table compresses to 6 MB).
- **Open, for Garrett (one question):** the hand-modelled polymers' FORMS are the biggest names still shown as
  "not yet MoleculeFinder molecules": MICROCRYSTALLINE CELLULOSE (122 labels) and POWDERED CELLULOSE (7) beside
  `/m/cellulose`, STARCH, CORN (80) and STARCH, POTATO beside `/m/starch`, SOYBEAN LECITHIN (9) beside `/m/lecithin`.
  Each is the same substance in a named physical form or from a named source; each is one `aliases` line if he
  rules they are forms of the molecule. Not done here: it changes about 200 pages and is his call.
- **Deploy: ETL `main` FIRST, then web `main`, trust runs 1 to 3 together, before Monday 2026-10-26's weekly run.**
  Nothing deploys from this repo.

## The source-licence rule and the registry (2026-10-23). DEPLOYED 2026-10-24 (ETL `41a688d`, web `f164fba`)
**DEPLOYED 2026-10-24 about 01:24 UTC on Garrett's word** (2026-10-23 his time), as built (NITE and CAS out). ETL `main` 0b9d3c9 -> `41a688d` (with `cbfe63f`; no workflow ran); web `main` 7585f9e -> `f164fba` (with `e936096`), GitHub deployment `7292228245` Production success. No other branch was waiting; pushed at 01:23, clear of the news cron. IndexNow run 40049651456: 1,678 -> 1,678, 0 new, 1,404 changed, 0 removed, 1,404 submitted and 1,404 accepted, audit exact, `indexnow-last` -> `f164fba`. Live, 14 of 14 checks: /m/caffeine (LD50 "HSDB via PubChem", the Hazard label row with ECHA's attribution, signal word Warning, no CAS), /m/ethanol (no LD50, Danger), /m/acetaminophen 2,400 (rat, oral), /m/capsaicin 47.2 (mouse, oral), /best/deadliest without ethanol or methotrexate, /about/methodology (citation, both DOIs, the not-used list), /classroom (the dataset block, Kaggle link), /embed ("Download the dataset"), /embed/caffeine.json (source "HSDB via PubChem"), /vs/acetaminophen-vs-ibuprofen (2400, no 1944), sitemap 1,678. Live Lighthouse (mobile, median of 3, Brave): /m/caffeine perf 98, SEO 100, LCP 2.29 s, CLS 0, 382 KB; /classroom 99, 100, 2.18 s, 0, 289 KB; /m/ethanol 98, 100, 2.32 s, 0, 375 KB. **Next, Garrett (optional, not urgent):** upload dataset 2026.10.1 as a New version on Zenodo and replace the Kaggle files, then send the new version DOI.
Run D found 41 live LD50s whose only source, T3DB, restricts commercial reuse. Fixed at the root, not by deleting
values: commits `4e73e8f` (code), `2b32acf` (data and dataset 2026.10.1), `5491468` (short names), plus notes.
- **The registry** (`sources/registry.py::SOURCES`): every source has `licence_class`, one of `LICENCE_CLASSES`:
  `public_domain`, `cc0`, `own` (MoleculeFinder curated, CC0 in the dataset), `computed` (RDKit) and `cc_by`, `ogl`,
  `acknowledged` (these three may be displayed WITH their `attribution` line, which the entry must carry), and
  `restricted`, `non_commercial`, `share_alike` (never displayed). `may_display(key)` reads the class; an unknown key is
  False. BLOCKED (the firewall) is unchanged and sits beside it.
- **PubChem's annotations are their depositors' content**, so each depositor is its own source, matched by its exact
  PUG-View `SourceName` (`pugview_names`; `PUGVIEW_NAMES`, `pugview_key`). Registered 2026-10-23, with the terms read
  that day: **HSDB, ChemIDplus and 16 more US government toxicology sources** (`public_domain`); **ECHA** (legal
  notice: reproduction authorised, source acknowledged; `acknowledged`); **EUR-Lex, the CLP Regulation**
  (Decision 2011/833/EU; `acknowledged`); **Safe Work Australia HCIS** (site-wide CC BY 4.0, "© Commonwealth of
  Australia"; `cc_by`); **T3DB** (downloads page: commercial reuse "requires explicit permission of the authors";
  `restricted`); **NITE-CMC** (site terms: "All information and materials appearing on this site are copyright
  protected", publication needs permission; its GHS pages allow copying only for a label or SDS; `restricted`);
  **the CAS Registry** (CAS: a licence is required to publish CAS RNs or use them to power a public platform;
  `restricted`). An unregistered depositor fails closed (its values are dropped) until it is registered.
- **Where the rule bites:** `toxicity.parse_ld50` and `ghs.parse_ghs` read each Information item with its reference
  and keep only displayable sources; every LD50 row carries `sources` (registry keys) and so does `ghs`
  (`withheld=` lists what was left out). `parse_ld50(..., gate=False)` is for tracing only (the dataset's
  `ld50_sources`). `assemble`: `cas` only if `may_display("cas_registry")` (so none); a curated `dose_poison` pin must
  equal a row a displayable source reports, or the build raises `LicenceRuleError` (capsaicin's pin said rat; HSDB
  reports 47.2 in the MOUSE, fixed); the hazard hubs (`kind: poison`) cite the classification's sources
  (`"echa+hcis"`). The loader's `_source: "pubchem"` columns are unchanged (the DB is not displayed).
- **The gate** (`transform/licence_gate.py`): walks every displayed value of every record (explicit `source` fields,
  implied ones in `IMPLIED`: a CAS number cites `cas_registry`, a drawing `rdkit`; licence records by register,
  products by source type) and every mg/kg figure in the curated /vs prose (it must be a row a displayable source
  reports for one of the pair). `snapshot_export.export` calls `enforce` after the snapshot guard and writes nothing
  on a failure; `tests/test_licence_gate.py` (39) runs the same check on the committed snapshot. Hand-transcribed
  single facts cited in seed files (half-lives, sweetness, Scoville, odor thresholds) are `curated`.
- **`data/snapshots/sources.json`** = `registry.public_registry()` (name, short name, licence, class, may_display,
  attribution, links). The web names sources and prints attribution from it (`scripts/source-names.mjs`).
- **What the rule caught (pinned rebuild, inputs 17122735c9f95167, keys blanked, `MFETL_ALLOW_REGRESSION=1` for the
  deliberate drop; a second rebuild without it: exit 0, `git status` clean):** the 41 LD50s (31 molecules lose their
  LD50, 10 show another value a displayable source reports); 124 secondary LD50 rows on 73 Safety panels; NITE's
  classifications (5 molecules lose their hazard label, 173 change, 26 of them Danger -> Warning); all 842 CAS numbers;
  six /vs paragraphs that quoted T3DB figures (rewritten in `comparisons.yaml`). Boards 265 -> 235 each, no entrant;
  dose hooks 265 -> 235. Full list: `../source-licence-rule-2026-10-23-changes.md`.
- **The dataset:** `PUBLIC_DOMAIN_TOX_SOURCES` is now READ from the registry (the public-domain and CC0 classes). The
  published record lives in `sources/seeds/dataset_published.yaml` (concept DOI 10.5281/zenodo.23605767, version
  2026.10 = 10.5281/zenodo.23605768, the Zenodo record, Kaggle `trommsdorff/moleculefinder-molecules-in-everyday-products`;
  the old `KAGGLE_ID` was wrong) and goes into README.md (citation and links), CITATION.cff (`doi`, `identifiers`),
  zenodo.json (`doi` for a published version, `isNewVersionOf` otherwise, the concept DOI in `notes`) and the Kaggle
  metadata. **`mfetl dataset` refuses (exit 1, nothing written) when any of those fields is empty** (`Unpublished`).
  **Since 2026-10-24 (`ba23f1c`, DEPLOYED 2026-10-24 with ETL `main` `f4fac9f`, web `45808d9`): the citation is the concept DOI alone, with "This
  version <v>, <its DOI>" beside it (README, CITATION.cff `doi`, zenodo.json `notes`).** Versions are listed oldest
  first; the last is the latest and `zenodo_record` must be its page. **A new version's DOI is recorded by `mfetl
  dataset --version V --doi D`** (never by hand); it refuses a non-Zenodo or reused DOI, a version already recorded
  with another, or `--doi` without `--version`. Then add the same line to the web's `lib/dataset.ts`. Version
  **2026.10.1** = 10.5281/zenodo.23620892 (uploaded 2026-10-24, Kaggle Version 2), recorded that way.
- Checks: 724 ETL tests (677), ruff 129 = main's 120 + 9 C408 in the registry's established `dict(...)` style.
  `.github`, snapshot_guard.py, news.py, inputs.py, cache.py, pipeline.py: git diff empty.

## Run D (2026-10-22): the CC0 dataset for Zenodo and Kaggle. DEPLOYED 2026-10-23 (ETL `0b9d3c9`, web `7585f9e`)
**DEPLOYED 2026-10-23 about 01:18 UTC on Garrett's word** (2026-10-22 his time), with his two rulings: the Terms gain one sentence ("MoleculeFinder's descriptions and curated data are also released under CC0 1.0 in the MoleculeFinder dataset.", Terms dated October 2026; web `7585f9e`) and CAS numbers stay out of the dataset. ETL `main` 7703167 -> `0b9d3c9` (with `1d4b7f9`; no workflow ran); web `main` 2b67549 -> `7585f9e` (with `ab3068f`), GitHub deployment `7267757391` Production success. No other branch was waiting. Live: `/`, `/classroom`, `/embed`, `/legal/terms` 200 (the sentence and the date on the page; the home "For the classroom" card); `/embed.js`, `/embed/caffeine.json`, `/embed/caffeine.svg` 200 with ACAO `*`, an unknown card 404 with ACAO `*`; sitemap 1,678; `BASE=https://moleculefinder.com node scripts/check-embed.mjs` all checks passed (plain and hostile-CSS pages from disk). IndexNow run 39883365865: 1,676 -> 1,678, 2 new, 5 changed (`/` and the four legal pages, which share one source file), 7 submitted and 7 accepted, audit exact, `indexnow-last` -> `7585f9e`. Live Lighthouse (mobile, median of 3, Brave): `/classroom` perf 99, SEO 100, LCP 2.14 s, CLS 0, 294 KB; `/embed` 98, 100, 2.18 s, 0, 281 KB. **Next, Garrett:** upload to Zenodo then Kaggle, send the DOI. **Outreach HQ:** `/classroom` and `/embed` may now join MF's good pages.
Branch `teacher-kit-2026-10` (code `e680f79`, data `71b01e8`, plus notes), never pushed. Full record: the plan's DONE block.
- **`mfetl dataset [--version X]`** (`moleculefinder_etl/dataset.py`, texts in `dataset_docs.py`, CC0 legal code in
  `dataset_cc0.txt`): rebuilds `data/dataset/` from the committed snapshot, offline. Refuses unless `data/raw_cache` is
  main's pinned inputs (`inputs.verify`; run `mfetl sync-inputs` first), checks every table's rows against the snapshot
  before writing (`check_counts`), writes atomically, MANIFEST.json with checksums. Version defaults to the snapshot's
  YYYY.MM. **Not in the weekly run** (etl.yml untouched): a tranche republishes by running it and committing the folder.
- **Field rule:** public domain or CC0 only. PubChem's computed identity and descriptors; Wikidata (CC0); page views;
  MF's curated lines, groups, hubs, products, worlds, relationships (CC0 by Garrett's instruction); DailyMed; Drugs@FDA.
  **An LD50 is kept only when a US government source in the pinned PUG-View record reports that exact value, species
  and route** (`ld50_sources`, per Information item with `toxicity.parse_ld50`; allowlist `PUBLIC_DOMAIN_TOX_SOURCES`).
  272 kept (all HSDB; ChemIDplus's PUG-View rows carry no parseable value), **41 withheld: their only source is T3DB's
  "LD50: x mg/kg (Oral, Rat)" text, the DrugBank-style form `parse_ld50` accepts** (acetaminophen, ethanol, capsaicin...).
  That is also what the live pages show; see "needs Garrett" in the plan. Left out: GHS and the `poison` hubs, MHRA/EMA/
  national licence rows, CAS, PubChem synonyms, `serving_mg`, prose. `iupac_name` is null on every record, so no column.
- `tests/test_dataset.py` (13): the committed package (files, checksums, headers, types, joins, LD50 sources, licences,
  the README's exclusions, counts against the snapshot when it is the one built from; skipped with a reason otherwise) and
  the builder offline (the trace on a PUG-View-shaped record, withholding, licences, counts refused, the inputs refusal).
- **Upload steps (Garrett; nothing here uploads).** Zenodo first, so Kaggle can carry the DOI.
  *Zenodo* (zenodo.org, signed in as for PolitiFinder's record): New upload; drag in every file in
  `moleculefinder-etl/data/dataset/` (18); "Do you already have a DOI?" No; Resource type Dataset; Title
  `MoleculeFinder: the molecules in everyday foods, drinks and products`; Publication date today; Creators: Add
  organization, `MoleculeFinder (137 Finder LLC)`; Description: paste `description` from `zenodo.json`; Licenses: Creative
  Commons Zero v1.0 Universal; Keywords: the 12 in `zenodo.json`; Version `2026.10`; Related works (optional): Is documented
  by, `https://moleculefinder.com`, URL; Publish; copy the DOI.
  *Kaggle* (kaggle.com as Trommsdorff): Datasets, New Dataset; drag in the ten CSVs, `moleculefinder.json` and
  `README.md`; Title `MoleculeFinder: Molecules in Everyday Products`; URL `moleculefinder`; Create. Then on the dataset
  page: Settings, License CC0: Public Domain; Subtitle `915 molecules, 405 foods, drinks and products, CC0`; About:
  paste `description` from `dataset-metadata.json` and add the Zenodo DOI line; Tags chemistry, food, education, biology;
  Settings, Sharing: Public.

## Run C2 (2026-10-22): the front door's ETL half. DEPLOYED 2026-10-22 (web `2b67549`)
**DEPLOYED 2026-10-22 about 19:17 UTC on Garrett's word.** ETL `main` 7cabb07 -> `7703167` (deploys nothing); web `main` c9fc016 -> `2b67549`, GitHub deployment `7261339955` Production success. No other branch was waiting; pushed at 19:16, clear of the news cron. Live: `/`, `/whats-in`, `/whats-in/pfas`, `/whats-in/energy-drinks`, `/in/energy-drinks`, both new /m pages, `/about` and the PFAS card 200; an unknown product 404; the home title, description, stamp "915 molecules · 405 products" and all eight cards; no index in the page; `/search-index.json` 1,320 entries (405 products); sitemap 1,676. Live search (headless Brave): coffee -> Coffee; zoloft -> Zoloft; caffeine -> Caffeine; sertraline -> Sertraline, Zoloft; pfas -> PFAS. IndexNow run 39838830285: 1,671 -> 1,676, 5 new, 60 changed, 0 removed, 65 submitted and 65 accepted, audit exact, `indexnow-last` -> `2b67549`. Live Lighthouse (mobile, median of 3, Brave): `/` perf 99, SEO 100, LCP 2.15 s, CLS 0, 312 KB; `/whats-in/pfas` 99, 100, 2.20 s, 0, 283 KB; `/whats-in/energy-drinks` 99, 100, 2.17 s, 0, 284 KB; `/m/caffeine` 98, 100, 2.29 s, 0, 392 KB. Next, Garrett's step: the Product Hunt launch.
Branch `front-door-2026-10` (code `8bc6916`, data `e5d39f6`, plus notes), never pushed. Full record: the plan's DONE block.
- **PFNA (67821) and PFHxS (67734)**, a two-row addition `2026-10-runC2` (tests/test_scope_b_canon.py ADDITIONS). 915.
- **Class pages** (`transform/products.py`): `sources/seeds/product_classes.yaml` (PFAS: four slugs, `rule:
  perfluorinated`), seed row `class: pfas`, kind `chemistry` (KINDS order: ... household, chemistry, moment). A class
  stands alone; only a class is kind chemistry. Every member must be a catalog molecule whose formula passes the rule (at
  most one H, at least 2C - 1 F) or the build stops; entries carry `role: "class"`, `carbons`, `fluorines`.
- **Energy drinks:** `food_hubs.yaml` `energy-drinks` (22) + caffeine overlay note; seed row `curated: energy-drinks`.
- **news.py:** aliases PFNA/PFHxS; `CLASS_TERMS = {"pfas": ["PFAS"]}`, used only when `data/snapshots/products.json` has
  that class page (`load_classes`); `page_path` links /whats-in/pfas; `class_queries` asked every run before the
  rotated batches. Feed rows keep the five fields. Tests use `JOB_INDEX` (molecules + classes); the fixture's PFAS line
  expects `pfas`. Run the job locally with `./.venv/bin/python3` (system python3 is 3.9; the job needs 3.11+).
- Pinned build exit 0, 2 POSTs, no drift; 664 tests, ruff 120 (= main). Workflows, guard, inputs, cache untouched.

## Run C1 (2026-10-22): What's in it, the product pages. DEPLOYED 2026-10-22 (ETL `7ad50aa`, web `6448ab6`)
**DEPLOYED 2026-10-22 about 13:23 UTC on Garrett's word.** ETL `main` 105ce67 -> `7ad50aa` (deploys nothing; no workflow ran); web `main` 86c8671 -> `6448ab6` (with the waiting notes commit `94449a2`), GitHub deployment `7253388927` Production success. No other branch was waiting. Live: `/whats-in`, coffee, wine, chocolate, Zoloft, Mounjaro (its tirzepatide line), Ritalin (methylphenidate hydrochloride), Listerine Cool Mint and `/m/caffeine` ("Found in these products") 200; the coffee card 200 image/png; an unknown product 404; sitemap 1,671 (404 `/whats-in`). IndexNow run 39786319341: 1,267 -> 1,671, 404 new, 540 changed, 0 removed, 944 submitted and 944 accepted, audit exact, `indexnow-last` -> `6448ab6`. Live Lighthouse (mobile, median of 3, Brave): `/whats-in` perf 99, SEO 100, LCP 2.14 s, CLS 0, 291 KB; `/whats-in/coffee` 99, 100, 2.16 s, 0, 279 KB; `/whats-in/zoloft` 99, 100, 2.17 s, 0, 278 KB; `/m/caffeine` 98, 100, 2.29 s, 0, 390 KB. The first Monday run after this re-reads 418 labels and asks PubChem for about 840 parent compounds (about 3 more minutes).
**Amendments (Garrett, same day), commits `a11246a` (code) and `d3d4b7c` (data): 403 pages (was 346).**
- **Curated foods and drinks.** A seed row `curated: <hub>` reads the records' curated `kind: food` memberships
  (`products.curated_hubs`: food_hubs.yaml plus the curated overlays, the list `/in/<hub>` shows; order of
  food_hubs.yaml, then slug). A food or drink row may name curated, world and wikidata together (never with
  dailymed): one page, their union, curated first, one entry per molecule; a source that adds no molecule is not
  cited (`also`). Molecule entries `role: "curated"` carry `hub` and the hub's `note`. 33 curated rows; 30 new pages;
  chocolate, citrus and milk combined; `tabletop-sweetener` left out (alternatives, not ingredients); no energy drink
  hub exists. `warm` now fetches a combined row's Wikidata item too (it had read only a row's first source).
- **Salts, hydrates and stereo forms by rule** (`products.parent_index`, `_resolve`). A label UNII no molecule
  claims goes to PubChem (`pubchem.unii_parents`: `compound/name/UNII-<code>/cids?cids_type=parent`, one GET a UNII,
  400/404 = none; cached as `pubchem/uniiparent-<UNII>.json`, UNII TTL; parents' properties through the permanent
  `props` cache for the InChIKey). An ACTIVE is looked up by its active moiety (zinc acetate's moiety is zinc, so a
  lozenge never lists acetic acid; PubChem files methylphenidate's own UNII under the dex form), an excipient by its
  own UNII. Accepted when the parent CID is a catalog CID (`parent`), else exactly one catalog molecule shares the
  parent's InChIKey first block (`skeleton`), and that molecule has 2+ carbons (`carbon_count`; an inorganic salt's
  parent is its acid). Hand list `sources/seeds/unii_aliases.yaml` (`alias`), 5 entries, only for forms the rule cannot
  reach: three lactose forms (lactose and maltose share a skeleton), methylphenidate, oseltamivir. Matches: 125
  parent, 46 skeleton, 88 alias (`products_gate.json` `matched_by_rule`). 839 label UNIIs looked up; the first run
  without them in the cache costs about 840 GETs (3 minutes).
- **`data/seed/next_tranche_queue.csv`** (committed, written by `stage_transform`, `products.write_queue`): every label
  ingredient MF lacks, by UNII (or name), actives first (an ingredient active on ANY seeded label), each section by
  label count: rank, section, name, unii, labels, labels_as_active, pubchem_parent_cid, example_products. 656 rows (76
  active, 580 inactive). The gate report keeps its top 60.
- Results: medicine 280, cosmetic 59, household 12, food 35, drink 13, moment 4; 70 fail (34 with 2, 23 with 1, 12 with
  0, 1 animal label); inactive-only label pages 55 -> 49; 415 molecules carry `products` (320). Pinned build
  (`sync-inputs` 17122735c9f95167, keys blanked), exit 0; molecule files differ from main by `products` alone.
  650 tests (641; `test_products.py` 38), ruff 120 (the branch baseline). Protected files untouched (git diff
  empty; their suites, 203 tests, pass).

Branch `whats-in-2026-10` (from `main` `47d6515`, the waiting Run B2 notes commit): code `5f190d7`, data
`03b2927`, helper `d429710`, plus its notes commit. Never pushed. Plan: `../BUILD-PLAN-growth-2026-10-18.md`
run C, first half (C2 changes the front door). Decisions (Garrett, 2026-10-22): URL `/whats-in/<product>`
(never `/in/`); a product page exists only when MF already holds THREE OR MORE of its molecules (a gate,
not a quota); the ten worlds are the first ten products.
- **Seed `sources/seeds/products.yaml` (HAND-MAINTAINED, 447 candidates):** slug, name, kind (food, drink,
  medicine, cosmetic, household, moment) and ONE source item: `dailymed: <set id>` (418), `wikidata: <QID>`
  (19), `world: <slug>` (10). `scripts/draft_products.py` drafts rows (brand owner's label, newest, never a
  repackager's: the Drugs@FDA holder for the 155 NDA brands in licences.yaml, a labeler stop list
  otherwise) and never writes the seed. `transform/products.load_seed` refuses a bad row, naming all.
- **Fetch (stage 1, `products.warm`), into raw_cache so the inputs artifact carries them:** each label
  (`sources/dailymed.py`: ingredients with class, UNII and active moiety; the OTC active and purpose lines;
  labeler, document type, version; `dailymed/spl1-<setid>.json`, 6-day expiry like Wikidata; a 404 is
  cached as `{"missing": true}`; a transient failure after 3 tries FAILS the run), the Wikidata items'
  P527/P186 via `wbgetentities` (stored order; `wikidata/product_parts.json`), and every molecule's UNII
  codes (`pubchem.uniis`, the full synonym list's `UNII-` entries, `pubchem/unii-<cid>.json`, 30-day
  expiry; 6 batched POSTs). A never-cached item is a miss even in a pinned build.
- **Match by code only (`compile_products`):** a label ingredient's UNII, else its active moiety's UNII,
  against PubChem's UNIIs for the molecule's CID; a UNII two molecules share matches neither. A Wikidata
  part's QID against `wikidata_qid`. No name matching, no Wikipedia prose; Open Food Facts is BLOCKED in
  the registry. An active's purpose is read off the label (a table row naming it, else the active and
  purpose lines paired by position, else a single purpose for all); 173 of 325 active lines carry one.
- **The gate:** 3+ distinct molecules, and a DailyMed label must be a label for people (Betadine's set id
  was an animal label). **346 of 447 pass:** medicine 258 (153 prescription, 105 OTC), cosmetic 54,
  household 12, food 13 (4 worlds, 9 Wikidata), drink 5 (2 worlds, 3 Wikidata), moment 4 (the after-rain,
  sleep, workout and sunscreen worlds). 101 fail, every one in `data/seed/products_gate.json` (committed,
  rewritten weekly) with its reason; 58 had 2 molecules, 23 had 1, 19 had 0, 1 was the animal label. The
  report also ranks the label ingredients MF lacks (titanium dioxide 132 labels, microcrystalline cellulose
  86, corn starch 71, talc 54, lactose monohydrate 51, iron oxides 48/43): the tranche queue's product
  order. Coffee, tea, wine, beer, chocolate, Coca-Cola and Red Bull fail: Wikidata gives them 0 to 2
  molecule parts.
- **Both directions are one fact:** `attach_products` writes `products` (slug, name, kind, role) on each of
  the 320 molecules in a product, the exact reverse of `products.json`; a molecule in none gets no field.
  55 label products have no ACTIVE ingredient that is an MF molecule (racemic menthol, tirzepatide's UNII,
  titanium dioxide...); they pass on inactives and carry `actives_not_in_catalog` (the label's names).
  Every DailyMed product also carries `not_in_catalog`: since Trust run 2 (2026-10-24) the LIST of its label
  ingredients that are not MF molecules, `{"name": <the label's name>, "role": "active" | "inactive"}`, label
  order, actives first, one entry per name, a name a listed molecule carries left out (it was a bare count). Its
  actives are exactly `actives_not_in_catalog`, which stays as it was. Display only: the web prints the names as
  plain text; nothing is matched or linked by name.
- **Export:** `snapshot_export.export(products=...)` writes `products.json`; None removes it. `stage_export`
  refuses records listing products with no staged `data/seed/products.json` (gitignored, written by transform).
- **Build:** `mfetl sync-inputs` (17122735c9f95167), `mfetl all` with all three database keys blanked: exit 0,
  0 property/synonym POSTs, pinned. Against main: 320 molecule files differ by `products` alone;
  `products.json` and `products_gate.json` new; index, boards, roam, worlds, comparisons, featured and meta
  byte-identical. **Untouched:** `.github/` (etl.yml, news.yml), `snapshot_guard.py`, `news.py`, `inputs.py`,
  `cache.py` (git diff empty). One existing test edited: the props/syn60 wiring test in
  `test_cache_safety.py` now stubs the product seed (it would otherwise reach DailyMed); the products wiring
  has its own test. 641 tests (612), ruff 120 against main's 119 (registry.py's own `dict()` idiom).
- **Weekly run, from the first Monday after deploy:** about 418 DailyMed requests (4 a second, about 2
  minutes), 6 UNII POSTs, the artifact about 2 MB bigger. A withdrawn label drops its page through the gate.
- **Deploy:** push ETL `main` BEFORE or WITH web `main` (sync-web copies the snapshot whole: a Monday run on
  the old ETL would remove products.json from the web). Nothing deploys from this repo.

## Run B2 (2026-10-21): the two fields run B waits for. DEPLOYED 2026-10-22 (ETL `105ce67`, web `86c8671`)
**DEPLOYED 2026-10-22 about 00:34 UTC on Garrett's word.** ETL `main` be00c11 -> `105ce67` (deploys nothing; no workflow ran); web `main` 6d36028 -> `86c8671` (with the Run E notes commit `f9b633b`), GitHub deployment `7240665097` Production success. No other branch was waiting. Live: `/m/sertraline` (Zoloft, NDA 019839), `/m/agomelatine` (European Commission, Valdoxan), `/m/zopiclone` (MHRA, Zimovane) each one FAQPage of 4 questions and a License row with its register's attribution; `/m/caffeine` 5 questions with its Wikidata names; `/m/lorazepam` no Lormetazepam; titles "Modafinil (Provigil)"; `/about/methodology` lists the three registers; sitemap 1,267. IndexNow run 39700502442: 1,267 -> 1,267, 0 new, 1,058 changed, 1,058 accepted, audit exact, `indexnow-last` -> `86c8671`. Live Lighthouse (mobile, median of 3, Brave): `/m/caffeine` perf 98, SEO 100, LCP 2.29 s, CLS 0, 389 KB; `/m/orforglipron` 98, 100, 2.33 s, CLS 0, 424 KB.
Commit `02e928f` (code, seeds, data). Web `2457707` carries the sync. Waiting for "deploy".
- **`wikidata_names` on every record** (`assemble.wikidata_display_names`): up to four names from the
  Wikidata label then aliases, through exactly the synonym line's filters (readable, not near the title,
  not on the do-not-use list) with NO PubChem synonym. 582 of 913 carry at least one. The web's
  "What else is X called?" reads it with the curated brands.
- **Fourteen do-not-use names added** (each with a reason in `synonym_do_not_use.yaml`): Wikidata aliases
  that are slang (Effies, Herbal Ecstasy, NOS) or name a different substance (Lormetazepam under lorazepam,
  retinoic acid under isotretinoin, acylcarnitine under SAMe, alpha-type CGRP, CGRP, CALCA and katacalcin
  under calcitonin, flue gas, root bark oil, Moderateafinil, Silymarin). They were already on the live
  synonym line under the H1; they leave it too (10 lines change). Two titles gain a parenthetical:
  "Modafinil (Provigil)" and "S-adenosyl methionine (SAMe)".
- **A licence record for every medicine** (`moleculefinder_etl/licences.py`, `mfetl licences`). Reads the
  Drugs@FDA data files (zip, public domain) and the EMA's medicines JSON (centrally authorised; the
  regulator named is the European Commission, which grants the authorisation on the EMA's assessment),
  matches each of the 336 medicines (`prescription-medicine` + `otc-medicine`) by active ingredient, and
  writes `sources/seeds/licences.yaml` (GENERATED, committed, sorted) with `regulator`, `register`,
  `application`, `product`, `authorised`, `holder`, `combination`, `basis`, `source`, `read`.
  - FDA: only products marketed today (Prescription or OTC; Discontinued and tentative do not count);
    a single-ingredient product first, then NDA/BLA before ANDA, then the oldest original approval.
    Source = the application's Drugs@FDA overview page. EMA: Human + Authorised; originator before generic.
  - Matching: the ingredient is one of the molecule's names, alone or followed only by salt/ester/hydrate
    words (`SALT_WORDS`). Names: title, preferred name, Wikipedia title, Wikidata label and aliases, EXCEPT
    an alias sitting inside the title (the racemate or parent: "citalopram" under escitalopram, "ofloxacin"
    under levofloxacin) or another catalog molecule's own name ("omeprazole" under esomeprazole). Only a
    TRAILING parenthesis is stripped ("(S)-citalopram" stays escitalopram). Every alias-driven match was
    audited: all 15 are INN/USAN spellings (aciclovir/acyclovir, pethidine/meperidine, rifampicin/rifampin).
  - **MHRA was read BY HAND** into `sources/seeds/licences_mhra.yaml` (substance as the index spells it,
    one product, date read; source = the public substance page). The site's GraphQL API answered 503 to
    every request on 2026-10-21; its fallback is an Azure search index behind a key shipped in the site's
    script, which was NOT used; product pages (with PL numbers) sit behind a disclaimer that was not
    accepted on anyone's behalf, so MHRA records carry no licence number. Used only where FDA and EMA have
    nothing. `mfetl licences` re-merges the file on every run.
  - **Counts: 295 Drugs@FDA, 1 EMA (agomelatine), 23 MHRA, 6 hand rulings unchanged = 325 of 336.**
    11 in no register, listed in the seed header, no record, no licence answer: amobarbital, bromazepam,
    cortisone, levomethamphetamine, metamizole, oxymetholone, phenazopyridine, rilmenidine, secobarbital,
    tianeptine, trimetazidine. 6 records are combination-only (`combination: true`; 5 FDA, 1 MHRA).
  - `relationships.attach_licences` runs after `attach_approvals` (the hand rulings win) and refuses an
    unknown slug, a non-medicine, a missing or unknown field, or a source that is not `https` on fda.gov,
    ema.europa.eu, mhra.gov.uk or aifa.gov.it (`is_regulator_url`). **A build only reads the committed
    file: `mfetl all` and the weekly run make no register request.** Refresh = run `mfetl licences` by
    hand and review the diff; it deletes its downloads (`data/regulators/`, gitignored) when done.
  - Registry: `drugs_at_fda`, `ema`, `mhra` sources (terms checked: EMA allows commercial reuse with EMA
    acknowledged as the source; MHRA content is Crown copyright under OGL v3).
- **Build:** `mfetl sync-inputs` (17122735c9f95167), then `mfetl all` with all three database keys blanked:
  exit 0, 0 PubChem POSTs, inputs pinned. The diff is exactly `wikidata_names` (913 files), `approval`
  (319), and the do-not-use list's 10 lines and 2 titles; index, boards, roam, worlds, meta untouched.
  Snapshot guard, `inputs.py` and `.github/` untouched. 612 tests (588), ruff 119 against main's 118 (the
  file idiom in `registry.py`/`assemble.py`). `tests/test_licences.py` (21) includes the order's test:
  every medicine's record names its regulator and a regulator source, none cites anything else (the four
  sourceless hand rulings, meldonium, phenibut, clenbuterol, clostebol, are named exceptions).
- **Deploy:** push ETL `main` (fast-forward to `names-licences-2026-10`; nothing deploys), then web `main`.
  The next Monday run rebuilds from these seeds with no change.

## Run A (2026-10-20) — inputs travel with the snapshot; molecules in the news. DEPLOYED 2026-10-20
**DEPLOYED 2026-10-20 about 19:00 UTC on Garrett's word.** (1) `mfetl migrate --apply` applied 0006 to the live database; the public key over REST: `molecule_news` five name columns 200, `select=*` 401, `updated_at` 401, `molecule_news_match` 401, an insert 401 (`molecule` 200, `event` 401 as before). (2) ETL `main` 4ae9022 -> `ef418fe` (the migrations check green). `news.yml` dry run 39479474794: 60 requests, 0 failed, 3,064 headlines, 70 molecules. Real run 39479816293: 3,036 headlines, 74 molecules, 314 rows in `molecule_news_match` (counted with the service key, nothing printed), 74 in `molecule_news`, the feed 200 with exactly five keys per molecule and `"ranked_by": "count"` (served `public, max-age=300`), IndexNow 75 URLs HTTP 200. Home eight: Ammonia, Ethanol, Uranium, Fentanyl, Magnesium, Creatine, Caffeine, Arsenic. PFOA and PFOS were not reached in that run (their batch past the budget); the rotated runs reach it. (3) Web `main` 4f15bbb -> `d3fe15c` (with `b5f9c40`), GitHub deployment `7208573405` Production success; IndexNow run 39480305068: 1,262 -> 1,265, 3 new, 21 changed, 24 submitted and 24 accepted, audit exact, `indexnow-last` moved to `d3fe15c`. Live: sitemap 1,265; the two PFAS pages and `/in/organohalogen` 200; the home cards render and the badge shows on `/m/ammonia` (53 headlines) and `/m/sucrose`. Live Lighthouse (mobile, median of 3, Brave): `/` perf 99, SEO 100, LCP 2.15 s, CLS 0, 298 KB; `/m/caffeine` 99, 100, 2.16 s, CLS 0, 376 KB; `/m/ammonia` (badge) 99, 100, 2.24 s, CLS 0, 366 KB. Spike ranking from about 2026-11-17.

**THE INPUTS FIX IS ACCEPTED (2026-10-21, five days early, on Garrett's word).** `etl.yml` dispatched by hand
(run 39691617286 on `0e25612`): run, sync-web, all-clear green, alarm skipped; it uploaded the first inputs
artifact `inputs-17122735c9f95167` (15.9 MB, 3,593 files, expires 2027-01-19) and committed `6e90bef`
(`data/seed/inputs.json` new, meta 2026-10-21, 100 molecule files). Web PR #11 self-merged as `dd1a5f0`,
Production deployment 7239649800 success; IndexNow run 39692873956: 1,265 -> 1,265, 0 new, 134 changed, 134
accepted, audit exact, `indexnow-last` -> `dd1a5f0`. Then on this Mac, `main` fast-forwarded to `6e90bef`:
`mfetl sync-inputs` (installed 17122735c9f95167, 3,593 files) and `mfetl all` **with SUPABASE_URL and
SUPABASE_SERVICE_KEY blanked for that one command** (stage 3 skipped, so the test never wrote to the live
database; the acceptance is the snapshot, which the load does not touch): exit 0, 0 PubChem POSTs, 913
molecules exported, **`git status --short` empty (0 lines)**. A Mac build now reproduces main exactly.
What the refresh itself moved (live since `dd1a5f0`; the same upstream drift tranche 2 reverted by hand,
now shipped as the weekly loop is meant to): `synonyms` on 95 molecules, `display_synonyms` 29, `ghs` 4
(disodium inosinate gains GHS08; water loses its label), `cas` 2 (carbon re-keyed, magnesium hydroxide none),
`categories` 3, `title_synonym` 2: **flunitrazepam's title gained "(Rohypnol)"** (its brand; no slang on the
record) and pantoprazole's lost "(Protonix)". The zinc oxide and dicalcium phosphate placeholder guards held.

Branch `news-2026-10` in both repos, from `origin/main` here and from local `main` on the web (which
carries tranche 2's notes-only commit `b5f9c40`, going out with this deploy).

### Part 1: the snapshot comes out the same whichever machine builds it (`moleculefinder_etl/inputs.py`)
**The cause.** The snapshot is a pure function of the code and `data/raw_cache` (PubChem properties,
synonyms, PUG-View; Wikidata descriptions). That cache is in no commit: GitHub keeps one copy in its
Actions cache, this Mac another, each refreshed on its own clock. Twice in tranche 2 a Mac rebuild
carried upstream drift the weekly run had not shipped (96 files the second time) and it was reverted by
hand. **An expiry cannot fix that** (it decides when a machine refreshes, not what it gets), and "refuse a
cache older than the last data PR" alone would not have either: the Mac's copy was NEWER both times.
**The design: the inputs travel with the snapshot.**
- The weekly run (GitHub, mode `refresh`, chosen by the CLI because `GITHUB_ACTIONS=true`) fetches as it
  always has, then records a fingerprint of every cache entry it built from: `data/seed/inputs.json`
  (committed by the existing `git add data/seed`), `data/raw_cache/INPUTS.json` (per-entry hashes), and
  one new step in `etl.yml` uploads `data/raw_cache` as the artifact `inputs-<fingerprint16>` (90 days,
  success only; public repo, free). Nothing else in the loop changed.
- Every other run is `pinned` (the CLI's default off GitHub). `mfetl sync-inputs` downloads that artifact
  with `gh`, verifies it hashes to the committed fingerprint before touching anything, and swaps it in
  (one cache, never a second copy). A pinned run never expires a cache entry (`cache.is_fresh`), so
  nothing main was built from is fetched again; a pinned export **refuses** unless every input main was
  built from is present and unchanged (`inputs.verify`; new molecules' files and new map entries are
  allowed), and keeps main's `refreshed` date so the molecule of the week does not move.
- Library code and the tests leave `MFETL_INPUTS` unset: neither mode, every expiry rule as before.
- **Proof on this Mac (2026-10-20, real 911-molecule data):** a pinned export from the Mac's own cache
  refused and wrote nothing; a simulated Monday (refresh mode, 0 PubChem POSTs) recorded fingerprint
  `d5338f69…` over 3,585 files; the cache was then drifted the tranche-2 way (flunitrazepam's synonyms,
  a deleted GHS file, a Wikidata description) and `mfetl all` refused before fetching anything, naming
  all three; after `sync` from the 15 MB artifact zip, a pinned `mfetl all` produced **0 changes** against
  the simulated Monday snapshot, with 0 PubChem and 0 Wikidata requests. The simulation commit was dropped.
  **The real acceptance is the first Monday after deploy:** that run uploads the first artifact; then
  `mfetl sync-inputs && mfetl all` here must show `git status` clean against main.
- `tests/test_inputs.py` (16): the record, the refusal (a foreign cache, a changed/missing file, a changed
  map entry, nothing to pin to), the stage refusing before `snapshot_export.export` is called, the sync
  (exact install, a corrupted download leaves the cache alone), pinned reads ignore expiry, the kept date,
  the CLI's mode choice, and the workflow step's place (after the commit, success only).

### Part 2: molecules in the news (`moleculefinder_etl/news.py`, `.github/workflows/news.yml`)
PolitiFinder's pattern (`politifinder/repo/scripts/news-politicians.mjs`), with these differences, each
deliberate:
- **Standard library only (Python 3.11+),** run as `python3 -m moleculefinder_etl.news` after
  `setup-python` with NO pip install, so the six-hourly cron never pays for rdkit. Cron `50 */6 * * *`.
- **Names only in public; the audit trail private (amended the same day, see "Amendments" below).**
  PF's `trending_politician` keeps the latest headline, outlet and link "for auditing". Here the public
  face (`molecule_news`'s five name columns, the feed, the site) carries none of it; every match's
  headline, outlet, link and query go to the private `molecule_news_match`. The job never PRINTS a
  headline (this repo's logs are public); `--show-headlines` is for a LOCAL dry run only and refuses on GitHub.
- **Same source as PF: Google News RSS (en-US).** Different queries: PF's eleven title queries find
  "Sen. X"; a molecule has no title, so the catalogue's own names are the queries (titles + brands +
  curated aliases + qualified phrases, ~40 per OR batch, ordered by page views) plus six topic queries.
  **A query returns at most 100 items** (measured), so a full batch is split in two and re-asked until a
  name stands alone, under a 60-request budget (caffeine matched 0 headlines inside a batch fentanyl
  filled, and 48 when asked alone). The day's four runs start from four rotation points, and a row stays
  listed from whichever run found it.
- **Matching is exact on names, a miss before a wrong match.** Terms: title, preferred name, the title's
  parenthetical, Wikipedia title, curated brands, `ALIASES` (Red 40, Red Dye No. 3, Ozempic, Mounjaro,
  Foundayo, BPA, CBD, THC), and display synonyms only when chemical-shaped and (one word) 7+ letters.
  Never the raw PubChem synonyms (lead's has "Glover", MSG's "Accent"). A term two molecules share
  matches neither (DHA names three). `STOP`: iron, lead, salt, water, gold, the commodity metals,
  mercury, chrome, carbon, silicon, plus names that are people or products (Allegra, Bayer, Endorphin,
  Tungsten). `QUALIFIED`: the only forms a stop word matches in (lead poisoning, iron deficiency, salt
  intake...). Dye numbers need a dye word nearby. A name followed by a compound word is a different
  compound (ethylene oxide, sodium alginate). Market/mining headlines are skipped (tickers, % moves,
  drilling, private placements, "market to reach USD..."). Quoted titles and `EXCLUDE` phrases
  ("Dopamine Chamber", "Arsenic and Old Lace") do not count.
- **Output:** upsert per match (keeps first_seen, never moves last_seen back), prune 21 days after the
  last headline, then `public-data/news/in-the-news.json` rebuilt from the table: every molecule whose
  last headline is inside 7 days (slug, name, first_seen, last_seen as dates, hits), max-age 300.
  **IndexNow:** only entrants (new to the list) plus `/`, as PF does: the page itself does not change
  while its molecule stays in the news. Key is the public one the site serves.
- **The dry run (2026-10-20 03:10 UTC, last 7 days):** 29 queries, 60 requests, 0 failed, 3,451
  distinct headlines, **82 molecules matched**. Top eight: fentanyl 152, ammonia 102, lead 65 (all
  "lead poisoning/exposure/levels"), ethanol 59, uranium 39, caffeine 26, creatine 24, sulfur 22. Also
  the Aleve/Claritin recall (naproxen, loratadine), the acetaminophen bottle recall, sertraline/
  fluoxetine/citalopram leaflet warnings, semaglutide/tirzepatide, the FSSAI sucrose/fructose proposal,
  daraxonrasib's CHMP opinion. Audit of every match: about 2 wrong of ~600 matched headlines (an
  "Ozone Communications Group", a tokenized-stock page). The first two dry runs found and fixed: Allegra
  (people), Endorphin (a shoe), Dopamine Chamber (an album), ethylene oxide, mining tickers.
- **PFAS:** the catalogue had no PFAS molecule; PFOA and PFOS were added the same day (Amendments, 2).
- **Tests:** `tests/test_news.py` (68 with the fixture): `tests/fixtures/news-headlines.txt` is 54
  SYNTHETIC headlines (never copied coverage) each stating its match; the job run end to end on it with
  the network off (no headline or outlet in its output, the feed's keys exactly the five); plan_write,
  build_feed, the split, the rotation, stdlib-only import, the workflow's shape (no pip, no push, no
  `--show-headlines`), and that `etl.yml` does not mention the news job. `test_migration_grants.py`:
  18 tables; molecule_news read-only to anon. **575 tests here (480 at tranche 2), ruff 113 = main's baseline.**
- **0006 verified on a local Postgres via `mfetl migrate --apply`** at the live state (0001-0005 logged):
  applied, a second run "up to date", raw SQL applied twice more; anon SELECT yes / INSERT no, RLS on.
  The Storage bucket insert is guarded (`to_regclass('storage.buckets')`), so it is a no-op off Supabase.

### Amendments (Garrett, 2026-10-20, the same day; commits `0c1f927`, `89ccbd2`)
1. **The home block is ordered by spike, not count.** `news.spikes`: a molecule's distinct headlines this
   week over its own average week across the four before, floored at `SPIKE_FLOOR` = 2 headlines a week
   (one stray headline is not a baseline of zero, and a molecule with no history divides by 2). Ties go to
   the count, then recency. The history is `molecule_news_match`; until it holds four weeks (its oldest
   match found 28 or more days ago, `has_history`) the order is the raw count, and the feed says which in
   a new top-level `"ranked_by": "spike" | "count"`. The web keeps the feed's order. **hits is now counted
   over every run's matches** (distinct stories in the last seven days), so the day's four rotated runs add
   up instead of each overwriting the last. The badge shows hits as before. Tests on a fixed five-week
   history: acetaminophen 5 a week then 40 (spike 8.0) outranks fentanyl 150 then 152 (1.01), a brand-new
   molecule with 3 sits between them (1.5), and without four weeks the order is the count.
   **The two top eights.** Today's dry run (2026-10-20 ~11:30 UTC, 60 requests, 0 failed, 3,033 headlines,
   91 molecules) has no history, so it ranks by count, as the live feed will for its first four weeks:
   ammonia 48, propane 37, ozone 36, ethanol 31, uranium 27, fentanyl 26, retinol 19, creatine 15. To show the
   spike order now, a LOCAL simulation fetched five weeks the same way each week (Google News `after:`/`before:`,
   120 requests a week, 0 failed, about 6,500 headlines a week; names and counts only, nothing written):
   **by count** fentanyl 88, ammonia 85, ethanol 81, insulin 73, aluminium 68, THC 68, uranium 64, lead 64;
   **by spike** sucrose 34 (usual 4.5 a week, x7.6), phenol 15 (1.2, x7.5), fructose 37 (5.2, x7.0), acetone 11
   (0.8, x5.5), citalopram 8 (2.0, x4.0), daraxonrasib 8 (2.0, x4.0), testosterone 54 (14.8, x3.7), sertraline 18
   (5.0, x3.6). The spike list is this week's actual stories: India's FSSAI infant-food sugar proposal, a new
   phenol and acetone plant, the UK antidepressant leaflet warnings, daraxonrasib's CHMP opinion. Fentanyl drops
   out of the eight (x1.0). Numbers are after the wire-copy fix below (before it, today's dry run had fentanyl 91).
   PFOA and PFOS show 0 in both runs because their batch was past the request budget in those passes; asked
   directly, `PFOA OR PFOS` matched 4 headlines to each, and the day's four rotated runs reach that batch.
2. **PFOA and PFOS joined the catalogue** (`2026-10-runA`, a two-row addition, not a tranche: bucket
   everyday-chemistry, family organohalogen, which reaches 3 and gets `/in/organohalogen`). 911 -> 913,
   sitemap 1,262 -> 1,265. Built pinned from this Mac's cache with a TEMPORARY local `inputs.json` (no
   artifact exists before the first Monday), fetching only the two CIDs (2 PubChem POSTs, Green); the
   cache's 97-file drift against main was kept out by a three-way merge against a no-change build of the
   same cache, so the commit carries only the two rows' effects. Aliases `PFOA`, `PFOS`,
   `perfluorooctanoate`, `perfluorooctane sulfonate`. **"PFAS" alone matches nothing:** it names a class
   of thousands of chemicals. Measured 2026-10-20: a `PFAS` query returned 86 PFAS headlines, of which 1
   named PFOA or PFOS; a `PFOA OR PFOS` query matched 4 headlines to each (EPA production data, a PFOS
   exposure study, an HPLC method note).
3. **The audit trail, private.** `molecule_news_match` (0006): one row per (molecule, story) with the
   headline (outlet suffix cut, its normalised text is the story key), outlet, Google News link of the first copy found, the query that found it, its date and when a run
   first found it; inserted with `resolution=ignore-duplicates`, so a story keeps its first query. Pruned 42
   days after the headline's date. Service role only: `revoke all ... from anon, authenticated`, RLS on,
   NO policy. `molecule_news` is revoked too and anon then gets `select (slug, name, first_seen,
   last_seen, hits)` only: **0003's default privileges grant SELECT on every new table to anon and
   authenticated, so without the revoke the column grant would mean nothing** (a test proves it).
   PostgREST echoes a failing row in its error, so every request to the private table is `quiet` and
   reports the status only. Tests: write() against a fake PostgREST (coverage reaches only the private
   table, never the names-only rows, the Storage JSON or the log), the quiet error, and the grants replay
   now models column grants and revoke-all. Web `lib/news-build.test.ts` reads the built site.
   **0006 checked on a throwaway local Postgres at the live state (0001-0005 logged):** `mfetl migrate
   --apply` applied it, a second run "up to date", raw re-applies twice more clean; anon: table-level
   SELECT on molecule_news false, columns slug/hits true and updated_at false, `select *` "permission
   denied", INSERT false, nothing at all on molecule_news_match ("permission denied"); authenticated:
   nothing on either; RLS on both; 0 policies on the match table; service_role reads the match row.
   Database and the scratch Postgres deleted.
4. **Found auditing the spike leaders (commit after `89ccbd2`):** a story's identity is its normalised
   headline text, not its Google News link (one local mercury story ran under six links and counted six
   times); and the market filter skips "mine", "stock options", "options expiring" ("...vanadium mine
   plans" had got through). Phenol and acetone's spike was real: an Indian phenol and acetone plant opened.
- **Tests:** 588 here (575 before the amendments); ruff adds nothing to main's baseline. Web 94 (92).

### Deploy sequence (on Garrett's word)
1. `mfetl migrate --apply` (0006: both tables and the `public-data` bucket); then, with the anon key over
   REST, `molecule_news?select=slug,name,hits` answers 200, `select=*` and any read of
   `molecule_news_match` answer 401/permission denied, and an insert is refused.
2. Push ETL `news-2026-10` to main. This arms the news cron and adds the inputs upload to the Monday run.
   Dispatch `news.yml` once with `dry_run: true` (names and counts in the log), then once for real: the
   table has rows, `molecule_news_match` has rows (read with the service key, locally, never printed),
   `.../storage/v1/object/public/public-data/news/in-the-news.json` answers 200 with five keys per
   molecule and `"ranked_by": "count"` (it reads "spike" from about 2026-11-17, four weeks after the first
   run), IndexNow accepted.
3. Push web `news-2026-10` to main (with `b5f9c40`), Vercel to Ready; the home block shows cards and a
   matched page shows its badge; Lighthouse `/` and `/m/caffeine` live. The deploy's own IndexNow delta,
   dry-run against production `4f15bbb`: URL set 1,262 -> 1,265, **24 URLs** (3 new: the two pages and
   `/in/organohalogen`; 21 changed: dichloromethane and 1,1-difluoroethane, the 12 hubs PFOA/PFOS join,
   `/best` and the boards they enter). The news code itself moves no fingerprint.
4. The Monday after: `mfetl sync-inputs && mfetl all` on this Mac must leave `git status` clean. **DONE 2026-10-21 by a hand dispatch: clean (see "THE INPUTS FIX IS ACCEPTED" above).**

## Tranche 2 (2026-10-18) — 788 -> 911, guard before load, grants. DEPLOYED 2026-10-19/20
**DEPLOYED 2026-10-19/20 on Garrett's word** (ETL `main` `9f10994`; web `main` `4f15bbb`, GitHub deployment `7188401307` Production, Ready about 00:33 UTC). Monday's green refresh (`cb86769`, web PR #10) was merged in first; the warm-cache rebuild re-surfaced the upstream synonym/CAS/GHS drift on 96 files and they were restored to the approved branch versions (the refresh's own changes kept: week 43 Adrenaline, meta 2026-10-19, fluconazole's brand order). This morning's PR had put "roofies"/"floonies" on flunitrazepam live for about 13 hours; the deploy removed them. Migrations 0004 and 0005 were applied to the live database with the new `mfetl migrate --apply` (SUPABASE_DB_URL in the ETL `.env`; 0001-0003 recorded as pre-log). Four checks: anon 401 on `event` and `ingest_run` (200 before), 200 on `molecule`; one `/api/e` POST (page_type `deploy-check`) shows on `/dashboard` as `deploy-check 1`. Live: 1,262 sitemap URLs, all 200; the three removed pages 410 with noindex; /in/anabolic-steroid 404. IndexNow run `39348330572`: 1108 -> 1262, 157 new, 260 changed, 3 removed, 420 submitted and 420 accepted, audit exact, `indexnow-last` moved to `4f15bbb`. Live Lighthouse (mobile, median of 3, Brave): perf 98-99, SEO 100, LCP 2.13-2.28 s, CLS 0, TBT 0 on /roam, /m/caffeine, /in/vitamin, /vs/caffeine-vs-theobromine, /best/deadliest.

Branch `traffic-2026-10-tranche2` from `origin/main` `b7b9217`. The "recurring tranche" of
`../BUILD-PLAN-growth-2026-10-18.md`. Review page (every assignment, every ruling, every pair):
https://claude.ai/artifact/TU7jpGmY3M9aq4TynVmCr1

### THE APPROVED-MEDICINE RULE, clarified (Garrett, 2026-10-18). Read before any tranche.
A molecule qualifies as an approved medicine when it holds a **CURRENT marketing authorisation for
human use** from the **FDA, the MHRA, the EMA, or the national regulator of any single EU member
state. One national licence is enough.** It applies the same way to new rows and to pages already
live. Rows that fail go to `sources/seeds/deferred_rows.csv` (held for good, test-enforced); rows let
in under a ruling carry their licence basis in `sources/seeds/approvals.yaml`, which
`relationships.attach_approvals` puts on the record as `approval` (orforglipron's cites Drugs@FDA NDA
220934 and its DailyMed label). **Phenibut stays: Latvia licenses it, exactly as meldonium qualifies.
Do not raise it again.** No recreational-drug row, ever (Garrett, 2026-10-18).

### What the branch carries
- **Catalog tranche `2026-10-A`: 126 rows.** `../drugs-wing-deferred.csv` read in view order from where
  tranche 1 stopped (9,945 views a month) down to 5,530: 148 rows read. 120 kept on the first pass,
  21 held, 7 queued; Garrett's rulings on the 7: **IN** meldonium (Latvian licence), clenbuterol (EU
  national licences), clostebol (Italian licence), orforglipron (FDA NDA 220934, Foundayo, approved
  2026-04-01, confirmed from Drugs@FDA and DailyMed), artemisinin (as a **plant compound**, bucket
  `plant-compound`, family terpenoid, beside quinine), thiomersal (as a **preservative**, bucket
  `everyday-chemistry` beside triclosan and formaldehyde, no medical claims); **HELD** nandrolone (no
  current licence confirmable; Ireland and the UK withdrew Deca-Durabolin). Its esters nandrolone
  decanoate and nandrolone phenylpropionate are lower in the queue and not yet read: the next tranche
  must rule on them under the same reasoning.
  Totals: 118 `prescription-medicine`, 6 `otc-medicine`, 1 `plant-compound`, 1 `everyday-chemistry`;
  12 `is_otc` (all in `otc_allowlist.yaml`; new unmapped group `urinary_otc`), 9 `dual_use`. One new
  family, `addiction-medicine`. 126 `why_it_matters` lines (90 to 170 chars).
- **Three live pages removed under the rule (Garrett, 2026-10-18): fenbendazole and carfentanil**, both
  veterinary only, **and oxandrolone** (second ruling, same day; see below). Out of `scope_b_core.csv`
  (tranche `2026-09-A` is now 287), into `deferred_rows.csv`,
  their `why_it_matters` lines deleted. What referenced them, and what happened: **worlds, trails
  (`relationships.csv`), comparisons, featured weeks, brands, food and product hubs: nothing** (checked
  by grep and by the web test `lib/gone.test.ts`); **boards** lightest, biggest and most-searched
  re-rank without them (carfentanil had no oral LD50, so it was never on Deadliest or Safest);
  **hubs** they belonged to (opioid, antiparasitic, health-hazard, irritant, the element and
  functional-group hubs) all stay at 3 or more, antiparasitic exactly 3 because albendazole joins;
  **similarity edges** of fentanyl, pethidine and 9 other molecules recompute. `carfentanil` stays in
  `toxicity.POTENT_TOXIN_SLUGS`, a list of names allowed a sub-floor LD50, where it does nothing
  without a row. The web answers **410** for both URLs (web CLAUDE.md).
- **22 comparisons** (`comparisons.yaml`, 122 -> 144); every formula and weight checked against both records.
- **The export's refusals run BEFORE the Supabase load** (`pipeline._preflight`, the Sep 28 lesson).
  `tests/test_guard_before_load.py` (5): the Sep 28 run sends 0 requests and leaves the snapshot
  byte-identical; on the old `pipeline.py` it sent 10 before the export refused.
- **Throttle log exercised and summarised** (`pubchem.throttle_summary`, a `::notice` on Actions). First
  cold run: 12 POSTs, all 200, none repeated, our Request Count and Time Green, PubChem's own Service
  status Black (220 to 240%) on 3 POSTs: PubChem's load, not ours.
- **Supabase (standing order 17).** 17 tables, none granted by name before. `0004_explicit_grants.sql`
  grants each by name. **`0005_private_tables.sql` revokes everything on `event` and `ingest_run` (and
  their sequences) from anon and authenticated**: 0003's blanket grant had let anyone with the public
  key read both. `tests/test_migration_grants.py` (12) replays every migration in order (named grants,
  revokes, blanket "all tables" grants, default privileges) and fails if either table becomes readable
  by anon or authenticated again, or a new table lacks its grants. `.github/workflows/migrations.yml`
  runs it on any push or PR touching a migration (public repo: no minutes billed).
  **Verified end to end against a throwaway local database, not production:** Postgres 16 plus
  PostgREST 16.3 with Supabase's roles (anon, authenticated, service_role, authenticator), migrations
  0001-0005 from this repo (the local copy of 0001 dropped `pg_trgm`, `vector` and the trigram index,
  which that build lacks and which touch no grant). With 0001-0004 the anon key read `event` and
  `ingest_run` (HTTP 200); after 0005 it gets 401 "permission denied for table event" on read and
  insert, while `molecule` stays readable. The web build pointed at it: 4 POSTs to `/api/e` all 204
  and 4 rows written; `/dashboard` 200 showing them (2 organic pageviews, 1 share, 1 hook
  interaction); `supabase_loader.record_run` wrote `ingest_run` with the service key. Stack deleted.
  **0004 and 0005 are approved for the live database and are applied AS A STEP OF THE DEPLOY, not before.**
- **Data, drift kept out.** Fresh fetch (`data/raw_cache` emptied first), Supabase blanked. Upstream
  moves on existing molecules (about 90 synonym lists, two CAS, two GHS sets, pantoprazole losing
  "(Protonix)", flunitrazepam gaining "(Rohypnol)") were reverted to the shipped values, so the
  commit carries the tranche only. "roofies" and "floonies" (flunitrazepam's new PubChem head) are on
  `synonym_do_not_use.yaml`.
- 480 tests. Ruff 0.17.0 reports 113 findings on `main` already; this branch adds none.

### Second rulings (Garrett, 2026-10-18)
- **Oxandrolone: HELD and removed**, exactly like fenbendazole and carfentanil. The FDA withdrew approval
  of Oxandrin and every generic on 2023-06-28 (88 FR 41970); no UK or EU licence. What referenced it:
  six live hubs (alcohols, esters, prescription-medicine, irritant, health-hazard, ghs-danger), all still
  far over the floor; the anabolic-steroid hub, which clostebol had just brought to 3 (not live: pruned
  2026-09-06), back to 2 and not emitted; the biggest, lightest and most-searched boards (no oral LD50,
  so never on Deadliest or Safest); the similarity edges of androstenone, dihydrotestosterone and
  oxymetholone, recomputed; the search index and the /roam map. No comparison, world, trail, featured
  week, brand or curated hub named it. `/m/oxandrolone` answers 410.
- **Flunitrazepam: STAYS**, confirmed from the regulator's own register: AIFA (Italy) lists ROIPNOL
  1 mg film-coated tablets, holder Cheplapharm Arzneimittel GmbH, AIC 023328 (pack 023328077),
  administrative status A (authorised), marketed, not revoked or suspended, special prescription (RMR),
  pack authorised 2000-12-11. Queried 2026-10-18 through AIFA's public medicines-database API; recorded
  in `approvals.yaml` and on the record. Spain's AEMPS register (CIMA REST API) lists no flunitrazepam
  product (checked against diazepam, 44 products, so the zero is real); one national licence is enough.
- Checked and fine: daraxonrasib (FDA approved 2026-08-26, Rasonque), suzetrigine, methoxyflurane,
  metamizole, tianeptine, secobarbital.

### Deploy sequence (on Garrett's word, after Monday 2026-10-19's scheduled run is green)
1. **Merge Monday's data refresh into the branch, rebuild, retest, publish pipeline main.** Merge ETL
   `origin/main` into `traffic-2026-10-tranche2`; `mfetl transform` + `mfetl export` from the warm cache
   with Supabase blanked (re-apply the drift revert only if a fresh fetch was made); all 480 tests;
   fast-forward ETL `main` and push. Nothing deploys from this repo.
2. **Apply 0004 then 0005 to the live database** with `mfetl migrate --apply` (both idempotent),
   then the four checks: the public (anon) key gets 401 on `event`; 401 on `ingest_run`;
   200 on `molecule`; one POST to `https://moleculefinder.com/api/e` lands a row that `/dashboard` shows.
3. **Push web `main` and watch the Vercel build to Ready**: merge web `origin/main`, `npm run sync-data`,
   build and page sweep first, then push. Re-measure Lighthouse on the five archetypes against production.
4. **Confirm IndexNow ran** from `deployment_status`: the batch includes the three removed URLs
   (`/m/fenbendazole`, `/m/carfentanil`, `/m/oxandrolone`), all three answer 410 live, and the audit count
   matches the new sitemap (1,262 plus whatever Monday's refresh moves).

## Run 3 (2026-09-07) — determinism + phases 5 and 6, DEPLOYED 2026-09-08
- **The snapshot is deterministic now.** The 2026-09-06 weekly PR changed 217 molecule files
  and roughly 190 of them carried nothing a reader could see. Two causes, both fixed:
  - **Synonyms.** Selection still follows PubChem's order (the only signal for which names a
    reader recognises, and its head is stable for months); STORAGE no longer does, the chosen
    twelve are sorted with the title first. The fetch window went 20 -> 60, which costs
    nothing at the API and drops starved lists (fewer than 12 display names, so the tail sat
    on the truncation boundary) from 209 to 73. Cache prefix is `syn60`, so the old 20-name
    entries are not reused. Measured on the real lists under a realistic perturbation:
    671 of 751 changed under the old rule, 95 under the new one, and every survivor is a real
    membership change. Side effect: 20 CAS numbers the 20-name window had been hiding.
  - **`structure_svg`.** **The rdkit VERSION is not the variable, the PLATFORM is.** rdkit
    2026.03.3 and 2026.03.6 on macOS agree on all 769 structures and both disagree with the
    Linux CI output on the same 53, the fused and bridged polycyclics whose layout goes
    through a numerical minimiser. **Pinning the version would fix nothing.** So the drawing is
    now a stored artifact: `structures.svg_key()` fingerprints the SMILES plus
    `RECIPE_VERSION`, and `assemble._carried_svg` reuses the previously exported SVG when the
    fingerprint matches. Records from before the key are adopted by their SMILES, so the
    migration did NOT redraw the catalog: all 53 Linux drawings carried across byte-for-byte.
    **Bump `RECIPE_VERSION` to force a redraw on purpose.**
  - Proof: `mfetl all` twice from the same `fetched.json` leaves the snapshot, `canon.parquet`
    and `fetched.json` byte-identical. `tests/test_determinism.py` pins both rules.
  - One-time cost: every one of the 788 files changed once (each gains `structure_svg_key`
    and its synonyms settle into the stored order). Real content moving with it: 20 CAS,
    22 `wikidata_qid`, 11 `summary`, 3 GHS, omeprazole's LD50, eugenol's categories.
- **Phase 5, the written half.** `sources/seeds/comparisons.yaml`, 122 pairs, compiled to
  `data/snapshots/comparisons.json` keyed `a-vs-b`. The pair LIST lives in the web repo
  (`lib/compare-pairs.ts`); the web build fails if the two disagree. Fenced like every other
  curated seed: unknown slug, self-comparison and the same pair in both orders all fail the
  run. Prose rules are enforced (`_comparison_prose_errors`): 4 to 6 sentences, 320+ chars, no
  em-dash, no dosing, no "which one to take". Half these pairs are medicines. The dosing
  pattern has a negative lookahead so "636 mg/kg" reads as the LD50 it is and "500 mg" trips.
  Every numeric claim was audited against the two records; four were wrong and are fixed.
- **Phase 6, everyday sources.** The plan asked for foods on the 60 highest-demand molecules
  still saying "Not yet mapped". After tranche 1 that list is 47 prescription medicines,
  elements and body molecules, so taken literally it would have meant inventing foods. Three
  parts instead: 18 new **food** hubs where a food genuinely exists (including several of
  those elements as the dietary minerals they are), 9 new **product** hubs under a new
  `kind:"product"` (`sources/seeds/product_hubs.yaml`, sharing the food hubs' validated
  additive machinery), and a web-side honest answer for the four buckets where neither is ever
  coming. 83 -> 191 molecules name a curated food or product; pages saying "Not yet mapped"
  705 -> 217 (plan target: under 420). All 60 of the top 60 stop saying it, 13 by curation and
  47 by the honest answer. `/in/coffee` 10 -> 14, `/in/wine` 15 -> 21, `/in/chocolate` 12 -> 17.
- Counts: 788 molecules, 788 distinct descriptions (100-209, mean 137), 168 hubs, 8 boards,
  122 comparisons, 127 tests, ruff clean, `mfetl all` idempotent.
- **Deploy order (unchanged): ETL main first (no deploy), then web main (the deploy).**

## Next
- **Launched on moleculefinder.com (498 live; 793 built and waiting on the branch above).** The `load_all` slug *reassignment* edge (moving a slug
  from one CID to another when the canon changes) is handled since 2026-09-12:
  `supabase_loader.rekey_moved_slugs` re-keys the existing row before the upsert. It still fails
  loudly, and needs a person, when the new CID already belongs to another row. The dup-key crash
  itself is fixed (`b882a07`).
- **Catalog growth is ON and tranche 1 is BUILT** (see the section above). The next tranche
  appends the next block of `../drugs-wing-deferred.csv` (the 566 pharmaceuticals under 10k
  views) with a new `batch` value. The 89 recreational-drug rows are a separate tranche that
  needs Garrett's explicit yes.
- Scale to `--target 10000` — still gated on engagement.
- Weekly `.github/workflows/etl.yml` is live (Supabase secrets are set; the Vercel deploy hook
  is gone, replaced by the phase 0 PR job).
