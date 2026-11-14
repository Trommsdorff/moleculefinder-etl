# CLAUDE.md — moleculefinder-etl

**Keep this file short.** It is loaded into every session, and Claude Code stops loading instruction files past
150,000 characters in total. It holds the standing rules and the current state only. **Run records do not go here:**
add them at the top of `HISTORY.md` (this repo), and keep this file under 20,000 characters. Everything this file
said before 2026-11-14, every run record included, is in `HISTORY.md` verbatim; search it by section name
(e.g. "Trust run 7", "Gate hold") when a code comment points at "ETL CLAUDE.md".

Public ETL for MoleculeFinder. Pulls PubChem, Wikidata (+ Wikipedia pageviews), DailyMed and hand seeds, transforms,
and writes **a static JSON snapshot** (`data/snapshots/`) the web app builds from, plus Supabase. Original design:
`../MoleculeFinder_Technical_Build_Plan.md` (sections 4–7). The web repo is `../moleculefinder-web/` (its own CLAUDE.md).

## Current state (update these lines; the record goes in HISTORY.md)
- **The plan in force:** `../BUILD-PLAN-everyday-chemistry-2026-11.md`. Phases 1, 2, 4, 5A, 5B, 6, 7, the gate hold and
  the drawing guard are live. Catalog 915 molecules; 424 product pages; 6 doors.
- **Phase 8 (the tertiary amine part rule):** built on `molecule-page-2026-11` (code `7252ad1`, data `711882c`), goes
  with the web's phase 8; deploy brief `../PHASE-8-DEPLOY-PROMPT.md`.
- **Monday 2026-11-16** is the drawing guard's acceptance: the counts it must show are in HISTORY.md, "Phase 5B" and
  "Drawing guard"; the guide is `docs/DRAWING-RECIPES.md` section 10.
- **Deferred:** monthly tranches from `../drugs-wing-deferred.csv`; the ~10k bulk canon (`--target 10000`) stays gated
  on engagement (watch `/dashboard`).

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
   Classes: `public_domain`, `cc0`, `own`, `computed`; `cc_by`, `ogl`, `acknowledged` (displayed WITH the entry's
   `attribution` line); `restricted`, `non_commercial`, `share_alike` (never displayed); an unknown key is False.
   PubChem annotations are their depositors' content: each depositor is its own source, matched by its exact PUG-View
   `SourceName`; an unregistered depositor fails closed. The CC0 dataset takes only public-domain, CC0, own or computed values.

## Commands
**STANDING ORDER (Garrett, 2026-10-21): local servers and local runs use BLANKED database keys** unless the
step genuinely needs the live database (a migration, a deploy check). Blank them on the command itself:
`SUPABASE_URL= SUPABASE_SERVICE_KEY= SUPABASE_DB_URL= <command>` (the `.env`/`.env.local` files hold the live
keys). **Every session stops its own servers (by process id) and checks for leftovers before it closes:**
`lsof -nP -iTCP -sTCP:LISTEN | grep -E 'node|python'` must show nothing the session started.

**A build on this Mac is PINNED (2026-10-20): run `mfetl sync-inputs` first.** It downloads the exact inputs main was
built from (the weekly run's `inputs-<fingerprint16>` artifact, verified against the committed fingerprint); `mfetl all`
then reproduces main, fetching only what is genuinely new. Without the sync, a pinned export refuses. A pinned run never
expires a cache entry and keeps main's `refreshed` date. `MFETL_INPUTS=refresh` is a one-off local data refresh, never a
code build. **The build here is checked by running it twice: byte-identical, and no unexpected PubChem requests.**

**On Garrett's machine `source .venv/bin/activate` silently gives you the WRONG python** (the venv's `activate` and the
`mfetl` shebang still point at the old Dropbox path, so `python3` falls through to a build without rdkit). Call the venv's
binaries directly:
```bash
./.venv/bin/python3 -m moleculefinder_etl.cli sync-inputs
./.venv/bin/python3 -m moleculefinder_etl.cli all       # = mfetl all
./.venv/bin/python3 -m pytest                           # offline tests must stay green
./.venv/bin/ruff check .
./.venv/bin/python3 -m moleculefinder_etl.cli migrate [--apply]
```
Fresh setup elsewhere: `python -m venv .venv && pip install -e ".[dev]"`; `mfetl seed --target 200` for a small smoke canon.
The env has no pip: use `uv pip install --python .venv/bin/python3 ...`. After a run, refresh the web's copy with
`npm run sync-data` there.

## How it flows (disk-to-disk, resumable)
- `stage_seed` → `data/seed/canon.parquet` (marquee names→CID + curated CIDs + Wikidata notability, ranked by pageviews).
- `stage_fetch` → `data/seed/fetched.json` (batched properties + synonyms; PUG-View Toxicity/GHS into `data/raw_cache/`;
  DailyMed labels; the FDA UNII table).
- `stage_transform` → `data/seed/molecules.json` (`assemble.py`; the presence, claim and product-hold checks run here).
- `pipeline._preflight` (boards, comparisons, doors, drawing guard, data claims), then `stage_load` → Supabase upserts
  (**skips with no creds**), then `stage_export` → `data/snapshots/` (per-molecule JSON, index, boards, `featured.json`,
  `products.json`, `products_published.json`, `doors.json`, `compare_drawings.json`, `sources.json`, `meta.json`).
- `mfetl featured` (offline) rebuilds only `featured.json` for previewing a seed edit; it never moves meta.json.

## Deploying and the weekly loop
- **Pushes are held by default.** Commit locally as Trommsdorff / `291580674+Trommsdorff@users.noreply.github.com` (never a
  local identity override, no `Co-Authored-By` trailer); push only on Garrett's word. **ETL `main` first, then web `main`**,
  clear of the news cron (`50 */6 * * *` UTC; runs fire late, check none is in progress) and of Monday's 06:00 UTC run.
  Before any publish, name every finished branch waiting to merge and ask whether it goes too.
- **`.github/workflows/etl.yml`** (weekly, Monday 06:00 UTC; it may publish on its own, that is authorised): `mfetl all
  --target 10000`, commits the refresh, uploads the inputs artifact, then `sync-web` checks out the sha the run pushed,
  copies `data/snapshots/` WHOLE into the web repo and opens or updates ONE data PR, waits for the web's `ci / verify`
  (decided from the Actions API by `head_sha`) and squash-merges when green; the merge is the deploy. A red check leaves
  the PR open and fails the job; the `alarm` job opens or comments on the refresh-failure issue. `WEB_REPO_TOKEN` needs
  Contents, Pull requests, Actions: Read and Issues: RW. Also `news.yml` (six-hourly, standard library only, never prints a
  headline), `migrations.yml`, `watchdog.yml`. Build and test on this Mac, not GitHub, unless Garrett asks.
- **If a run stops or its PR is held:** do not re-run the job and do not merge a held PR by hand (a re-run replays the old
  merge; close and reopen the PR after a fix). Read the run's summary page and the step log, find the input that moved,
  fix it on a branch.

## The guards in the weekly run (none may be weakened) and what a stop looks like
- **The snapshot guard** (`load/snapshot_guard.py`, before the export writes anything): a protected field may only regress
  if the input behind the new value was fetched live in this run (an existing LD50 going null, a QID changing). A summary
  reverting to "chemical compound" never passes, live or not. `MFETL_ALLOW_REGRESSION=1` overrides and logs each molecule,
  for a deliberate rule change only.
- **Wikidata text ages 7 days** (`transform/wikidata_age.py`, Garrett's ruling, trust run 8): a CHANGE to a Wikidata text
  field the site shows (description, label, aliases) ships only once the revision that introduced it is at least 7 days
  old; until then the shipped value stands. A brand-new molecule takes the current value; a reverted edit never ships.
  Not a blacklist of names. Held values: run summary and `data/seed/wikidata_held.json`.
- **Product pages are held, not dropped** (`transform/products_hold.py`, gate hold): a product the SHIPPED snapshot has,
  whose row is still in `products.yaml`, and which this run would drop, is published again from what shipped, logged
  `held:`, in the run summary and `data/seed/products_held.json`. A product leaves ONLY by removing its row from
  `products.yaml`; then the web must list `/whats-in/<slug>` in `lib/gone.ts` (410). A held product that would fall under 3
  molecules refuses the run. The ledger `products_published.json` never shrinks.
- **Doors** (`transform/doors.py`, `pipeline._preflight`): every door's `requires:` fact must hold and every pinned line must
  match its `pin` (12 hex of sha256 over the whitespace-collapsed text); otherwise `DoorError` lists each problem and
  nothing is loaded or written. An edited line stops the build until the door is read again: replace its pin with "?" and
  run `scripts/door_pins.py` (it never overwrites a pin). Every `links` target must have a live page.
- **The drawing guard** (`transform/drawing_guard.py`, before the load and the export): every `structure_svg`, part layer,
  pair drawing and repeat unit is compared byte for byte with what shipped. Allowed: carried, a palette repaint, a new
  molecule/pair/unit, a key moved with a named input, a words-only seed change. Anything else stops the run:
  `DrawingChanged: refusing to export: N drawing(s) changed with nothing to explain it.`, one line per entry, **STOPPED (N)**
  at the top of the summary's Drawings section, no data PR, the site keeps last week's data. The only release valve,
  `MFETL_DRAWING_SEEDS_CHANGED=1`, is for a Mac build carrying a deliberate seed PATTERN change committed with its data;
  `etl.yml` never sets it (a test holds that). What to do: `docs/DRAWING-RECIPES.md` section 10.
- **Presence** (`transform/presence.py`, start of `stage_transform` and pytest): a bad mark stops the build (no mark on a
  seed row, a value outside the list, `formed` without `formed_when`, `none` without a reason, a dash or "inferred" in a
  note, a note over 160, two marks for one fact). **Never stops Monday:** a new unmarked Wikidata row exports
  `presence: null`, listed in `data/seed/presence_unmarked.json` and the run summary.
- **Claims** (`transform/claims.py`): `check_lines()` at the start of `stage_transform` and in pytest, `check_data_claims()`
  in `_preflight`. See the claim rule below.
- **The licence gate** (`transform/licence_gate.py`) at export; the pinned-input refusal (`inputs.verify`); the featured
  compiler (a failed compile writes nothing); `attach_descriptions` raises on a duplicate, short (<100) or dashed description.
- The Supabase load retries only the idempotent DELETE (3 attempts) on a dropped connection or gateway 429/5xx; **the 4
  inserts must never be retried**; a database error is never retried.

## Data rules
- **THE APPROVED-MEDICINE RULE (Garrett, 2026-10-18; read before any tranche).** A molecule qualifies when it holds a
  **CURRENT marketing authorisation for human use** from the **FDA, the MHRA, the EMA, or the national regulator of any
  single EU member state. One national licence is enough** (an FDA OTC monograph counts). It applies the same way to new
  rows and to pages already live. Rows that fail go to `sources/seeds/deferred_rows.csv` (held for good,
  `tests/test_deferred_rows.py`); rows let in under a ruling carry their basis in `sources/seeds/approvals.yaml`.
  **Phenibut and flunitrazepam stay. Do not raise them again.** No recreational-drug row, ever (Garrett, 2026-10-18).
  A live page removed under the rule answers 410 (web `lib/gone.ts`).
- **A label ingredient is matched to a molecule by CODE only (UNII), never by name** (Garrett's ruling, trust run 3: fix
  the matching, never soften the line). A molecule shown as "not yet" that is one: add the code to
  `unii_aliases.yaml` (a form) or `substances` (the molecule's own code), never a name rule; a chemically altered
  material is never a form.
- **Product pages:** URL `/whats-in/<product>` (never `/in/`); a page exists only when MF holds THREE OR MORE of its
  molecules (a gate, not a quota); a DailyMed label must be a label for people; the brand owner's label, never a
  repackager's. `products.yaml` is HAND-MAINTAINED; `scripts/draft_products.py` drafts rows and never writes the seed.
- **Structure drawings: nothing redraws a shipped structure.** A drawing is a stored artifact keyed by
  `structures.svg_key()` (SMILES + `RECIPE_VERSION`) and carried byte for byte; a live drawing changes only by a repaint
  (colours only) or a deliberate `RECIPE_VERSION` bump. The palette's fingerprint is pinned to the recipe version. CPK
  colours: the ten brief hues exactly, every other element Jmol's colour tuned into their band by one rule
  (`structures.tuned`), no per-element exceptions (Garrett, 2026-10-25: "keep it as is"). Parts are SMARTS rules
  (`structure_parts.yaml`), never atom numbers; a part with no label is never shown.
- **Names and titles:** a name goes in a title only when the record carries it (no hand seed of names for titles).
  `title_synonym` is never used when the title has a parenthesis; `synonym_do_not_use.yaml` lists names the parenthetical
  never uses (a test fails any committed title using one). Short answers' other names come only from curated `brands` and
  `wikidata_names`, never raw PubChem synonyms. A pair's `names` parenthetical must be a name the record carries, not
  the title, and appear in the answer line.
- **LD50:** `toxicity.primary_ld50` is the one LD50 (oral rat, oral mouse, any oral, then the lowest by another route);
  the boards take it only when oral (`leaderboards.ORAL_ONLY`).
- **Descriptions:** every record gets a unique 100-200 character description; every new family slug needs an entry in
  `description_phrases.yaml`.
- **Determinism:** `mfetl all` twice from the same inputs is byte-identical (`tests/test_determinism.py`). No timestamps on
  committed records; freshness lives in gitignored `data/seed/freshness.json`. The molecule of the week is keyed to the
  snapshot's `refreshed` date, never a clock.
- **Dataset:** a new Zenodo version's DOI is recorded only by `mfetl dataset --version V --doi D` (never by hand), then the
  same line in the web's `lib/dataset.ts`. Lessons' text CC BY 4.0; descriptions and curated data CC0.
- **News:** names only in public; every match's headline, outlet, link and query go to the private `molecule_news_match`.
  Matching is exact on names, a miss before a wrong match; never the raw PubChem synonyms.
- **IndexNow ignore list:** a new snapshot field no page renders yet goes on the web's ignore list, with a test.

## Copy rules
- No em or en dash. No advice and no dosing. A door answers "what is in it and how does it work", never "is it bad for you".
- **THE CLAIM RULE.** "only", "first", "most", "leading", "largest", "world's", "never", "always" need an entry in
  `sources/seeds/claims_allowed.yaml` (words, basis `data`/`science`/`history`/`ordinary`/`held`, why, and `line`, 12 hex of
  sha256 over the whitespace-collapsed text). A claim about how common something is, what people do or a health outcome is
  rewritten or loses the word; a rewrite stays as interesting as the line it replaces (a specific true fact, never a list
  of where the molecule occurs). To add or edit such a line: check the claim, then write or update its entry.
- **The completeness rule:** a curated list never claims to be every molecule in something.
- **Titles and descriptions are frozen through the redesign**, character for character.

## Supabase / DB
- Creds in gitignored `.env`: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_DB_URL` (session pooler, for migrations only).
  Project ref `nzhhjdbgogfidjrsuqiv`. It powers only `/api/e`, `/dashboard` and the news feed.
- **DDL/migrations run from this Mac with `mfetl migrate` (lists pending) / `--apply`. NEVER ask Garrett to paste SQL into
  the Supabase dashboard.** Each migration grants explicitly by name (`tests/test_migration_grants.py`); `event` and
  `ingest_run` stay unreadable to anon. Needs `psycopg[binary]` (the `db` extra) via uv.
- **Never `source` or `.` the `.env` in a shell** (its unquoted password breaks parsing and the error prints it); read it with
  python-dotenv. Password rotation: Garrett's one dashboard step, then `scripts/set_db_password_from_clipboard.py`.

## Working on this Mac
- Blank the database keys on every local build, test and server; stop only what your session started, by process id.
- `data/raw_cache` holds the inputs; `sync-inputs` swaps the artifact in (one cache, never a second copy).
- PubChem: read `SMILES` + `ConnectivitySMILES`; batched POSTs take ONE comma-separated `cid=1,2,3`.

## Where things live
- `moleculefinder_etl/`: `cli.py`, `pipeline.py`, `inputs.py`, `migrate.py`, `news.py`, `dataset.py`; `sources/`
  (`registry.py`, `pubchem.py`, `wikidata.py`, `dailymed.py`, and `seeds/`); `transform/` (`assemble.py`, `structures.py`,
  `drawings.py`, `drawing_guard.py`, `doors.py`, `presence.py`, `claims.py`, `products.py`, `products_hold.py`,
  `wikidata_age.py`, `licence_gate.py`, `toxicity.py`, `relationships.py`); `load/` (`snapshot_guard.py`, the loaders).
- **Seeds** (`moleculefinder_etl/sources/seeds/`): `scope_b_core.csv`, `deferred_rows.csv`, `approvals.yaml`,
  `licences*.yaml`, `products.yaml`, `product_pairs.yaml`, `comparisons.yaml`, `why_it_matters.yaml`, `food_hubs.yaml`,
  `worlds.yaml`, `featured.yaml`, `claims_allowed.yaml`, `structure_parts.yaml`, `compare_drawings.yaml`,
  `repeat_units.yaml`, `presence_wikidata.yaml`, `unii_aliases.yaml`, `synonym_do_not_use.yaml`, `doors/`.
- **Recipes:** `docs/DRAWING-RECIPES.md` (the drawing engine, parts, pairs, the guard; section 10 is what to do on a stop).
- **Scripts:** `scripts/door_pins.py`, `draft_products.py`, and the review-page generators (`copy_sweep_review.py`,
  `door_chains_review.py`, `phase5_review.py`, `presence_review.py`), which write into `../moleculefinder-web/docs/design/`.
- `supabase/migrations/`; `tests/`; `.github/workflows/` (`etl.yml`, `news.yml`, `migrations.yml`, `watchdog.yml`).

## More
- `HISTORY.md`: every run record, newest first (the old CLAUDE.md is at its foot, verbatim).
- `../CLAUDE.md` (standing rules for both repos), `../HISTORY.md`, `../BUILD-PLAN-everyday-chemistry-2026-11.md`.
- GitHub `Trommsdorff/moleculefinder-etl` (public).
