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
labels, transparent bg). `transform/families.py` maps type-slug → family key (the web mirrors it in
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
  Not done here; it is a real hardening option.

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
  from one CID to another when the canon changes) is still not auto-handled — it needs a manual
  stale-row delete first, as the 489 reconcile did. Only bites a future canon change; the dup-key
  crash itself is fixed (`b882a07`).
- **Catalog growth is ON and tranche 1 is BUILT** (see the section above). The next tranche
  appends the next block of `../drugs-wing-deferred.csv` (the 566 pharmaceuticals under 10k
  views) with a new `batch` value. The 89 recreational-drug rows are a separate tranche that
  needs Garrett's explicit yes.
- Scale to `--target 10000` — still gated on engagement.
- Weekly `.github/workflows/etl.yml` is live (Supabase secrets are set; the Vercel deploy hook
  is gone, replaced by the phase 0 PR job).
