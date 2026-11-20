# The weekly refresh on the Mac mini

MoleculeFinder's weekly data refresh moves from GitHub Actions (`.github/workflows/etl.yml`, Mondays 06:00 UTC) to a
launchd job on Garrett's Mac mini, as the network's rule requires (`network/137-Finder-Web-Standards.md` section 14).
Built and proved 2026-11-15 on branch `mac-weekly-2026-11`; **switched on 2026-11-16** on Garrett's word (section 4;
the first Mac run is Monday 2026-11-23, 03:10 Eastern). `etl.yml` is the manual backup (section 7). The review page is
`moleculefinder-web/docs/design/mac-weekly-review-2026-11.html`.

Files: `scripts/mac/weekly-refresh.sh` (the job), `scripts/mac/com.137finder.moleculefinder.weekly-refresh.plist`
(its launchd file), `scripts/mac/with_keys.py` (hands the build the two database keys), `.github/workflows/mac-alarm.yml`
(relays the Mac's alarm so it arrives by email), `uv.lock` (the pinned Python packages), `tests/test_mac_weekly.py`.

## 1. Runbook (plain language)

**What it does each Monday.** At 03:10 Eastern the Mac checks out the code that is live on GitHub, rebuilds the
catalog from PubChem, Wikidata and DailyMed with every guard switched on, saves the result to the ETL repository, copies
it into the website's repository as one pull request, waits for the website's own check to pass, merges it (that is
the deploy), and waits until Vercel says the new site is live. Then it closes any old failure issue. It takes about
15 to 30 minutes. If it fails it tries again every two hours until 18:10, then once a day at 03:10 until a run works.
A week that has already worked does nothing at the later times.

**Where the log is.** `~/Library/Logs/MoleculeFinder/weekly-YYYYMMDD-HHMMSS.log`, one per run, and beside it
`summary-....md` (what was held, every drawing made or remade, the pull request, the deploy). Logs older than 90 days
are deleted by the job. launchd's own output (normally empty) goes to `~/Library/Logs/MoleculeFinder/launchd.log`.
The job's state (one small file per week, its inputs cache and Python environment) is in
`~/Library/Application Support/MoleculeFinder/`.

**What an alarm looks like.** An email from GitHub saying the `mac-alarm` run failed, and an open issue on
`Trommsdorff/moleculefinder-etl` titled **MoleculeFinder ETL FAILED** (label `refresh-failure`). It says what
failed, where the log is, which attempt this was, the Drawings block, and the last 80 log lines. When the website's
check (`ci / verify` on the data PR) is what failed, it also names the failed step, the broken test (the test runner's
`FAIL` lines) and quotes the last 40 lines of that step's log (since 2026-11-16; the web repo is private, so those
lines appear in the ETL's public issue). A Mac notification too. The site stays up with last week's data. **Do not re-run to make it go green**: read the log, find the input that
moved, fix it on a branch. The next green run closes the issue itself.

**If the Mac is off.** Nothing runs, so nothing on the Mac can complain. The GitHub watchdog (`watchdog.yml`, daily
13:00 UTC, on GitHub's machines) sees no new refresh commit and opens an issue (and emails) once MoleculeFinder is 8
days past its last good refresh: in practice on the Wednesday after a missed Monday, if the Tuesday and Wednesday
03:10 catch-ups also did not run.

**Run it by hand.**
```bash
cd ~/137/moleculefinder/moleculefinder-etl
scripts/mac/weekly-refresh.sh --dry-run      # everything except the load, the commit, the pushes, the PR, the merge
scripts/mac/weekly-refresh.sh --force        # a real run even if this week already worked (it publishes)
```
A dry run builds from a throwaway copy of the inputs cache, so it never moves the real one. Run a branch's code with
`--dry-run --ref <branch>` (dry runs only; only `origin/main` is ever published). To see what a start at a given
moment would do: `scripts/mac/weekly-refresh.sh --schedule-check $(date +%s)`.

**Turning it on, off, and back to GitHub.**
```bash
# on (the deploy session does this once; section 4)
cp scripts/mac/com.137finder.moleculefinder.weekly-refresh.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.137finder.moleculefinder.weekly-refresh.plist
# off (a running refresh is stopped and files its "cancelled" alarm)
launchctl bootout gui/$(id -u)/com.137finder.moleculefinder.weekly-refresh
rm ~/Library/LaunchAgents/com.137finder.moleculefinder.weekly-refresh.plist
# back to GitHub: turn it off (above), then put `schedule: [{ cron: "0 6 * * 1" }]` back under `on:` in
# .github/workflows/etl.yml and push. GitHub's cache will have expired, so its first run fetches every input fresh
# (slower; every guard holds).
```

## 2. Every step, check and guard of `etl.yml`, in order, and how the Mac does it

Nothing is dropped silently: each row says what the Mac does instead, or why the step is no longer needed and what
replaces it. "Same" means the same code runs: every guard inside `mfetl all` is unchanged and runs on the Mac exactly
as on GitHub.

### Job `run`

| # | etl.yml step | What it protects against | On the Mac |
|---|---|---|---|
| 1 | `schedule: 0 6 * * 1` (+ `workflow_dispatch`; the schedule removed at the switch, 2026-11-16) | A missed week; the molecule of the week changes with the ISO week | launchd, Monday 03:10 Eastern, retries Monday 06:10 to 18:10 every two hours, catch-ups 03:10 Tuesday to Sunday; the job runs only while the UTC ISO week (the clock `refreshed` and the molecule of the week use) has no success and fewer than 8 tries. A start missed while asleep fires at the next wake. `etl.yml` keeps `workflow_dispatch` as the manual backup. |
| 2 | `permissions: contents: write`; a fresh runner per run | A job that can do more than it needs; leftovers from an earlier run | A lock (a second start exits at once); its own worktrees of `origin/main` for both repos, created fresh and removed after; refuses a checkout that is not clean or not `origin/main`; clears every `MFETL_*`, `SUPABASE_*` and `GITHUB_*` variable a shell could leak in. It steps aside (no try counted, no alarm) while another session's `mfetl` build runs on this Mac or a GitHub `etl.yml` run is in progress. **Reach:** it uses `gh`'s login, which can do more than the workflow's tokens (see the review page). |
| 3 | `actions/checkout@v6` | Building something other than what is on `main` | `git worktree add --detach … origin/main` after a `fetch` (time-limited, credentials from `gh`, never a prompt). The interactive checkout is never touched, whatever branch or state it is in. |
| 4 | `setup-python 3.12` + `pip install -e .` (since 2026-11-16: `setup-uv` 0.13.0 + `uv sync --frozen`, as the Mac) | An environment that cannot build | Python 3.12 at a fixed path, packages exactly as `uv.lock` names them (`uv sync --frozen`). **Was stronger than GitHub**, whose `pip install -e .` took whatever was newest each Monday (the manual backup now installs from the same lock); the lock was regenerated at the moment of GitHub's 2026-11-09 install, so it names the very versions that run used (rdkit 2026.9.1, numpy 2.5.4, pyarrow 26.0.1, Pillow 13.0.0, supabase 2.34.1). |
| 5 | `actions/cache/restore` (`pubchem-raw-*`) | Refetching every input every week (slow, and more churn than upstream really had) | The job's own cache, `~/Library/Application Support/MoleculeFinder/raw_cache`, kept between runs (`MFETL_RAW_CACHE`). It is seeded once at the switch from the last GitHub run's inputs (`--seed-cache`), so the first Mac run carries on from exactly where GitHub stopped. Expiry rules (`config.py` TTLs) unchanged. |
| 6 | `mfetl all --target 10000` with the two secrets and `GITHUB_SHA` | The refresh itself | The same command, in refresh mode (`MFETL_WEEKLY=1`), with the real `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` read from the ETL's gitignored `.env` by `with_keys.py` (never sourced, printed or logged; the database password is not passed). `MFETL_GIT_SHA` stands in for `GITHUB_SHA` in `ingest_run`. Every check below runs inside it, unchanged. |
| 6a | the presence check and the claim check (`check_lines`), start of transform | A bad presence mark; a claim word with no entry | Same. Proved: both stop the Mac job (section 3). |
| 6b | the Wikidata 7-day hold (`wikidata_age.py`) | A fresh Wikidata edit (vandalism) reaching the site before it is a week old | Same; held changes in the summary and `data/seed/wikidata_held.json`. |
| 6c | the gate hold (`products_hold.py`) | A live product page vanishing because a refresh lost it | Same; held pages in the summary and `data/seed/products_held.json`; a held page under 3 molecules stops the run. |
| 6d | `_preflight` before the load: data claims, comparisons, the featured compiler, the doors (`requires:` and pins), compare drawings, **the drawing guard**, the snapshot guard | Anything the export would refuse reaching the database; a door saying something no longer true; a drawing changing with nothing to explain it; a cached value walking a shipped one backwards | Same. The release valves (`MFETL_DRAWING_SEEDS_CHANGED`, `MFETL_ALLOW_REGRESSION`, `MFETL_ALLOW_STALE_WIKIDATA`) are never set and are actively cleared (a test holds it). Proved: doors, the drawing guard, the snapshot guard and the featured compiler each stop the Mac job (section 3). |
| 6e | the Supabase load: retries only the idempotent DELETE (3 tries); the four inserts never | A dropped connection half-loading the database | Same code. A dry run blanks the keys, so the load logs that it skipped. |
| 6f | export: the licence gate, the snapshot guard, descriptions checks, the pinned-inputs refusal (pinned builds only) | A value from a source that may not be shown; a regression; a duplicate or short description | Same. Proved: the licence gate stops the Mac job (section 3). Note: it runs after the load, on GitHub too (review page). The pinned-inputs refusal does not apply to the refresh, as on GitHub; it still guards every interactive build. |
| 6g | `MFETL_DRAWINGS_REPORT` | The Drawings block for the summaries and the alarm | Same, written outside the checkout. |
| 7 | "Count held Wikidata changes" / "Count held product pages" (`find -newer pyproject.toml`) | Counting last week's committed file as this week's | Same idea: counted only if this run rewrote the file (newer than a marker the job touches at the start). |
| 8 | "Count drawings" | The Drawings block | Same, from the report file. |
| 9 | "commit snapshot": `git add data/snapshots data/seed`; no change → the heartbeat (`data/LAST_CHECK`, "etl: no changes DATE [heartbeat]"); else "etl: refresh DATE"; push | Publishing nothing silently; a public repo's crons being switched off after 60 quiet days | Same subjects, committed as Trommsdorff (the repo rule) instead of github-actions[bot]. **Every** commit the job pushes stamps `data/LAST_CHECK`, so the watchdog can find it among the sessions' commits. The push has a time limit. If `main` moved during the run the push is refused and the run fails and alarms (nothing is rebased onto code it was not built from); the next start rebuilds from the new `main`. |
| 10 | "Name the inputs artifact" + `upload-artifact` (90 days) | Another machine rebuilding a different snapshot from its own drifted cache | **No longer possible** (nothing outside Actions can upload an artifact) **and no longer needed**: the Mac is now the canonical builder and its inputs are on the Mac. `data/seed/inputs.json` records `"built_on": "mac-mini"` and the fingerprint; after each push the job clones its cache to `~/Library/Application Support/MoleculeFinder/inputs-main` (copy-on-write, costs only what changed), and `mfetl sync-inputs` copies from there, checked against the fingerprint as before. What is lost: GitHub's off-machine copy. If the Mac's disk died, the next refresh would fetch every input fresh; the snapshot itself is committed and every guard holds. |
| 11 | "heartbeat after a failed run" | 60 quiet days switching off this public repo's crons (the watchdog lives here) | Same, once a week at most (retries would otherwise push one per try): from a fresh `origin/main`, only `data/LAST_CHECK`, "etl: run failed DATE [heartbeat]". The watchdog does not count it as a success. |
| 12 | `actions/cache/save` (always) | Losing what a run fetched | Not needed: the cache is a folder on the Mac and stays. |

### Job `sync-web`

| # | etl.yml step | What it protects against | On the Mac |
|---|---|---|---|
| 13 | `needs: run`, not gated on `snapshot_changed` | The web silently lagging the ETL after one failed sync | Same: it compares against the web's committed copy every time. |
| 14 | check out the ETL at the sha the run pushed | Syncing last week's tree (the 2026-09-06 bug) | Not needed: the job's ETL worktree IS the commit it just pushed. |
| 15 | check out the web with `WEB_REPO_TOKEN` | Reading another repo needs its own token | A worktree of the web's `origin/main`; credentials from `gh`. |
| 16 | sync: `rm -rf web/data/snapshots; cp -R …` | A diffed copy missing a deletion | Same, whole copy. |
| 17 | open or update ONE data PR (lowest open `data/snapshot-*`, branch off current main, force-with-lease, create or edit) | A second PR left behind after a red week; a stale branch history | Same logic, same branch names, same title and body (it names the Mac run instead of an Actions URL). |
| 18 | close superseded data PRs | Several open data PRs | Same; tidying, never a gate. |
| 19 | wait for `ci / verify` on that exact sha (Actions API; appear in 5 min, finish in 30; the `verify` job itself must be `success`) | Merging an unverified tree; a green roll-up over a skipped job | Same logic and limits. A red check leaves the PR open and the run alarms, naming the failed step and the broken test with the step's last 40 log lines (2026-11-16). Since 2026-11-16 the web's `ci.yml` also runs on every push to `main`; the data PR's head commit is never on `main`, so a push run is never the one waited on. |
| 20 | squash-merge (`WEB_REPO_TOKEN`, not `GITHUB_TOKEN`) | Deploying without the web's push-triggered workflows (IndexNow) running | Same, with `gh`'s login (a user token, so the push-triggered workflows run). **Stronger:** `--match-head-commit` merges only the commit that was verified. |
| 21 | (nothing) | A merge that never goes live | **New:** waits up to 30 min for Vercel's production deployment of the merge commit to report success (GitHub deployments API), then checks the site answers 200. Otherwise it alarms: "merged but not live". |

### Jobs `all-clear` and `alarm`

| # | etl.yml step | What it protects against | On the Mac |
|---|---|---|---|
| 22 | `all-clear`: close every open `refresh-failure` issue, naming the run | An issue that stays open after recovery | Same, after the deploy is live (a no-change week too). |
| 23 | `all-clear` summary (held counts, drawings) | Not seeing what the run held | The run's summary file in the log folder and the log itself. |
| 24 | `alarm` (a separate job, `if: failure()`): open or comment on "MoleculeFinder ETL FAILED", with held counts, drawings, and the warning about re-running a failed check | A failure nobody hears about | The job's exit trap raises it on any failure, a cancel (stopped, shut down, the agent unloaded) and a timeout. Same title, label and text, plus the log path and its last 80 lines (home folder written `~`, anything shaped like a key redacted). It dispatches `mac-alarm.yml`, which files the issue as github-actions[bot] and fails, so GitHub emails Garrett as a failed `etl.yml` run did. If the dispatch fails it files the issue itself. A Mac notification too. |
| 25 | GitHub's own "run failed" email; the run's page | Hearing about it | The `mac-alarm` run's failure email; the log and summary files. |
| 26 | (GitHub's machines are always on) | The machine running the job being down | **New risk, covered from outside:** the watchdog on GitHub (`watchdog.yml`) now counts the Mac's refresh commits and alarms after 8 days without one. |

### Not in etl.yml, added on the Mac

- **Disk:** refuses (and alarms) with less than 25 GiB free; removes its worktrees and any dry-run cache after every
  run; deletes logs over 90 days; reports free space before and after in the log.
- **A hard time limit** of 2 hours for the whole run (the time limit is a timeout alarm, every child stopped).
- **The network** is waited for (up to an hour) instead of spending a try on an outage.
- **Time zone:** warns if the Mac is ever not on America/New_York.

## 3. Proofs (2026-11-15)

Recorded in full on the review page. In short: the dry run from a clean checkout; parity of a Mac build with GitHub's
last committed snapshot from the same inputs; each guard stopping the Mac job with its alarm text; every git and
GitHub call with no terminal attached, from launchd itself; two starts at once, one refusing.

## 4. The switch (the deploy session, on Garrett's word "deploy"; done 2026-11-16, the record is HISTORY.md)

In this order. Name every finished branch waiting to merge first and ask whether it goes too. Clear of the news cron.

1. **After a Monday GitHub run has finished and merged** (check `gh run list --repo Trommsdorff/moleculefinder-etl
   --workflow etl.yml --limit 1` shows `completed success` and the web's data PR is merged), and before the next one.
2. **Parity** (if not already done for that run): section 5's command; it must print `IDENTICAL`.
3. Merge `mac-weekly-2026-11` into the ETL's `main`, and in the same commit edit `.github/workflows/etl.yml`: remove
   the `schedule:` line from `on:` (keep `workflow_dispatch: {}`) and add this header at the top:
   ```
   # ════════════════════════════════════════════════════════════════════════════════════════════════
   # MANUAL BACKUP ONLY (2026-11). The weekly refresh runs on Garrett's Mac mini: scripts/mac/weekly-refresh.sh,
   # launchd agent com.137finder.moleculefinder.weekly-refresh, Mondays 03:10 Eastern with retries and catch-ups
   # (network/137-Finder-Web-Standards.md section 14: "scheduled jobs run on the Mac mini, not on GitHub Actions,
   # for every finder site; GitHub workflows stay only as manual backups"). This workflow has NO schedule; it runs
   # only from the "Run workflow" button. Before pressing it, check the Mac job is not running
   # (~/Library/Logs/MoleculeFinder/, newest log). Its cache will usually have expired, so it fetches every input
   # fresh: slower, every guard holds. It publishes its own inputs artifact as before, and the Mac job carries on
   # from whatever main then names. docs/MAC-WEEKLY-REFRESH.md.
   # ════════════════════════════════════════════════════════════════════════════════════════════════
   ```
   Update `tests/test_etl_workflow.py` if it asserts the schedule. Run the whole suite (keys blanked), ruff at its
   baseline. Push ETL `main` (this also delivers `mac-alarm.yml` and the watchdog change).
4. **Mark the switch week done** when its refresh ran on GitHub (otherwise the job's first daily catch-up, 03:10
   the next morning, runs a full refresh in that same week): `echo "success <UTC time> switch: this ISO week's
   refresh ran on GitHub (run <id>)" >> ~/Library/Application\ Support/MoleculeFinder/week-<YYYY-Www>`, then
   `scripts/mac/weekly-refresh.sh --schedule-check <epoch>` reads `run=no` for every start before the next Monday
   and `run=yes` for that Monday 03:10. **Seed the job's cache** from the inputs main names (the last GitHub run's artifact):
   `scripts/mac/weekly-refresh.sh --seed-cache`. Then a **dry run from main**: `scripts/mac/weekly-refresh.sh --dry-run`.
   It must read, in its Drawings lines, every existing drawing carried and nothing made (as of 2026-11-15:
   `903 carried, 0 repainted, 0 drawn`; parts `723 carried, 0 made`; pairs `147 carried, 0 repainted, 0 made`; repeat
   units `3 carried`), and end `DRY RUN complete`.
5. **Install and load the agent:**
   `cp scripts/mac/com.137finder.moleculefinder.weekly-refresh.plist ~/Library/LaunchAgents/ && launchctl bootstrap
   gui/$(id -u) ~/Library/LaunchAgents/com.137finder.moleculefinder.weekly-refresh.plist`, then
   `launchctl print gui/$(id -u)/com.137finder.moleculefinder.weekly-refresh | grep -E 'state|path'` shows it loaded.
6. **Prove the relay once:** `gh workflow run mac-alarm.yml --repo Trommsdorff/moleculefinder-etl -f title="TEST: Mac
   alarm relay" -f body="A test of the relay from the switch session. Close this."`; the issue appears and the email
   arrives; close the issue by hand (`gh issue close N --comment "relay test"`).
7. Records: HISTORY.md (ETL, web, folder), the "Current work" lines; `network/OUTREACH-COORDINATION.md` standing order
   18 and Web Standards section 14's status line (MoleculeFinder moved) are Cowork's to update: tell Garrett.
8. **The first Monday's acceptance:** by 09:00 Eastern on the Monday after the switch: the newest log in
   `~/Library/Logs/MoleculeFinder/` ends `DONE: published: …`; the ETL's `main` has "etl: refresh DATE" by
   Trommsdorff; the web's data PR for that date is merged and its production deployment succeeded; no `etl.yml` run
   was scheduled that day; no open `refresh-failure` issue. The Drawings lines read as section 4's (plus any new
   molecule). On the Wednesday, the watchdog's run lists MoleculeFinder as healthy ("last green 2d ago").

## 5. Parity: a Mac build from GitHub's inputs equals GitHub's snapshot

After any GitHub run of `etl.yml` has committed (`etl: refresh DATE` by github-actions[bot]), from the ETL repo:
```bash
SHA=$(git log origin/main --author=github-actions --format=%H -1 --grep='^etl: refresh')
WT=$(mktemp -d)/parity && git worktree add --detach "$WT" "$SHA" && cd "$WT"
export UV_PROJECT_ENVIRONMENT="$HOME/Library/Application Support/MoleculeFinder/venv"
uv sync --quiet --frozen --no-dev --no-install-project --python /opt/homebrew/opt/python@3.12/bin/python3.12
SUPABASE_URL= SUPABASE_SERVICE_KEY= SUPABASE_DB_URL= MFETL_INPUTS=pinned "$UV_PROJECT_ENVIRONMENT/bin/python" -m moleculefinder_etl.cli sync-inputs
SUPABASE_URL= SUPABASE_SERVICE_KEY= SUPABASE_DB_URL= MFETL_INPUTS=pinned "$UV_PROJECT_ENVIRONMENT/bin/python" -m moleculefinder_etl.cli all --target 10000
git status --porcelain data/snapshots | wc -l   # 0 = IDENTICAL: the Mac rebuilt GitHub's snapshot byte for byte
cd - && git worktree remove --force "$WT"
```
(The worktree uses the `uv.lock` this branch adds; on a commit older than the branch, copy it in first:
`git show mac-weekly-2026-11:uv.lock > uv.lock`.)

## 6. What changed in the code for the move

- `config.py`: `weekly_run()` (GitHub, or `MFETL_WEEKLY=1`), `summary_path()`, `MFETL_RAW_CACHE`.
- `cli.py`: the weekly run's refresh mode no longer means "on GitHub" only.
- `pipeline.py`: the run-summary sections are written for either weekly run.
- `inputs.py`: a Mac-built `inputs.json` (`built_on: mac-mini`, no artifact); `sync-inputs` copies from the Mac's
  `inputs-main`; a GitHub-built pointer still downloads its artifact.
- `load/supabase_loader.py`: `ingest_run.git_sha` from `MFETL_GIT_SHA` when not on GitHub.
- `.github/watchdog/network_freshness.py` and `watchdog.yml`: MoleculeFinder counts a refresh commit touching
  `data/LAST_CHECK` or (2026-11-16) `data/snapshots/meta.json` as a success, the newest of the two (8 days, not 10);
  GitHub's refresh commits touch only `meta.json`; a target that stalls while an older episode is open now emails.
- 2026-11-16, at the switch: the alarm names what broke on the website's check (`ci_failure_detail`); `etl.yml` has no
  schedule and installs from `uv.lock`, frozen; the web's `ci.yml` runs on every push to `main` too.
- `.github/workflows/mac-alarm.yml`: the alarm relay (dispatch only, no schedule).
- `uv.lock`: committed (it had been excluded locally in `.git/info/exclude`, so no build was ever pinned).

## 7. The manual backup: what pressing "Run workflow" on `etl.yml` does (since 2026-11-16)

It runs the whole refresh on GitHub's machines, exactly as the Monday cron did before the switch: the same
`mfetl all --target 10000` with every guard, installed from the same `uv.lock` (frozen) as the Mac, then the commit,
its own inputs artifact, the one data PR, the wait for `ci / verify`, the merge (the deploy), all-clear or alarm. Its
cache will usually have expired, so it fetches every input fresh: slower, more molecule files move, every guard holds
(the snapshot guard, the drawing guard, the Wikidata 7-day hold, the gate hold, the doors, the licence gate).

**It cannot fight the Mac job.** The ETL's `main` is where the two meet, and a push there only goes through on top of
the commit the run was built from:
- If the Mac job is running when the button is pressed, whichever pushes second is refused. On GitHub the `run` job
  fails (its failed-run heartbeat is refused too and only warns), so `sync-web`, which needs `run`, never starts: no
  data PR, no merge. On the Mac the push is refused and the run alarms ("did main move during the run?"); the next
  start rebuilds from the new `main`. Proved by `tests/test_etl_workflow.py::test_the_manual_button_cannot_fight_the_mac_job`.
- If `etl.yml` is running when a Mac start comes, the Mac steps aside (no try counted, no alarm) and tries at the next
  start (`test_the_mac_job_steps_aside_while_the_manual_backup_runs`).
- In the one remaining overlap (the button pressed after the Mac pushed its ETL commit but while the Mac waits on its
  data PR), GitHub's later push to the PR branch moves it, so the Mac's `--match-head-commit` merge is refused and the
  Mac alarms, while GitHub merges its own verified commit. Either way only a verified commit is merged, and the newest
  data ships.

Afterwards `main`'s `data/seed/inputs.json` names GitHub's artifact (`sync-inputs` downloads it as before), and the Mac
job carries on from its own cache at its next start. A green manual run counts for the watchdog too.

## 8. The dataset on Zenodo (since 2026-11-20)

The CC0 dataset (Zenodo concept DOI `10.5281/zenodo.23605767`, which always resolves to the latest version) is
published by **one command, `mfetl zenodo`** (`moleculefinder_etl/zenodo.py`), through Zenodo's API with Garrett's
personal access token. Version 2026.11 was the first published this way (record 24407566, DOI
`10.5281/zenodo.24407566`). The website names only the concept DOI, so a new version changes nothing on the site.

**How a version reaches Zenodo today (by hand, a session, on Garrett's word).** In the ETL checkout, on `main`, with
the pinned inputs (`mfetl sync-inputs`) and the database keys blanked:
```bash
mfetl dataset --version 2026.12        # build the package from main's snapshot (twice: byte-identical), review it
mfetl zenodo --dry-run                 # public reads only, no token: every check, nothing created
mfetl zenodo --draft-only              # the real draft with its files, read back against MANIFEST.json; not published
mfetl zenodo                           # publish that draft (Zenodo's reply must carry the reserved DOI)
mfetl zenodo --check                   # read only: latest version, old versions answer, files download and match,
                                       # the concept DOI leads to it
git add data/dataset moleculefinder_etl/sources/seeds/dataset_published.yaml && git commit   # the DOI it recorded
```
It refuses, publishing nothing, when the version is already on Zenodo or not newer than its latest, a file does not
match `MANIFEST.json` byte for byte, the licence is not CC0, the record is not MoleculeFinder's, the repo's list of
versions is not Zenodo's, another draft is open, or the draft's files differ after upload. A failed run deletes the
draft it made and puts `data/dataset/` and `dataset_published.yaml` back; if the delete fails it names the draft:
discard it with `mfetl zenodo --discard` or at `https://zenodo.org/uploads/<id>` (Delete).

**When the weekly job does it (branch `zenodo-weekly-hook-2026-11`, NOT merged: it waits until after the first Mac
Monday, 2026-11-23).** `dataset_published.yaml` gains a `release:` line, the version the dataset should be at. Cutting a
version is changing that one line (Garrett decides; a session commits it). After a weekly run's data is live and the
week's success is written, the job runs `mfetl zenodo --release`: when `release` is newer than Zenodo's latest, it
builds that version from the live snapshot, publishes it with every check above, commits the DOI to the ETL's main
(`dataset: 2026.12 published on Zenodo (10.5281/zenodo.N)`) and runs `--check` (six tries, two minutes apart, for
doi.org). Nothing due is silent. The step cannot fail, retry or block the refresh.

**What its alarm looks like (once the hook is merged).** An email from GitHub saying the `mac-alarm` run failed, and an
open issue on `Trommsdorff/moleculefinder-etl` titled **MoleculeFinder dataset publish FAILED** (label
`dataset-failure`, separate from the refresh's `refresh-failure`). It says what happened, that the refresh itself
succeeded and the site's data is live, where the log is, and the step's last 60 lines (token-shaped strings
redacted). A Mac notification too. The next Monday tries again while the release is still due; the next green
dataset step closes the issue. Most likely causes and what to do:
- *"has no ZENODO_TOKEN"* or *HTTP 401/403*: the token is missing, revoked or lacks a scope; renew it (below).
- *"an open draft already exists"*: a draft was left on Zenodo; discard it (`mfetl zenodo --discard`, or Delete at
  `https://zenodo.org/uploads/<id>`).
- *"PUBLISHED ... but the push of its record ... was refused"*: the version IS on Zenodo; on a checkout of main run the
  `mfetl dataset --version V --doi D` the alarm quotes and commit `data/dataset/` and `dataset_published.yaml`.
- *"are not Zenodo's"*: a version was published another way; record it the same way first.
To stop the job trying, set `release` back to the latest published version.

**Renewing the token.** Zenodo's personal access tokens do not expire on their own; renew one that was revoked,
leaked, or stops working.
1. Signed in to Zenodo, open https://zenodo.org/account/settings/applications/tokens/new/ , name it, tick only
   `deposit:write` and `deposit:actions`, Create, copy it. (Revoke the old one at
   https://zenodo.org/account/settings/applications/ .)
2. In the Terminal app (never in a chat window), this asks for it with hidden typing and writes it into the ETL's
   `.env` as `ZENODO_TOKEN`, keeping the file at permissions 600:
   ```bash
   /bin/bash -c 'umask 077; f=/Users/garrettpoe/137/moleculefinder/moleculefinder-etl/.env; read -rsp "Paste the Zenodo token, then press Return: " T; echo; [ -n "$T" ] || { echo "nothing entered, nothing saved"; exit 1; }; grep -v "^ZENODO_TOKEN=" "$f" > "$f.tmp"; printf "ZENODO_TOKEN=%s\n" "$T" >> "$f.tmp"; chmod 600 "$f.tmp"; mv "$f.tmp" "$f"; unset T; echo "saved to .env (not shown)"'
   ```
3. Check it with a read-only call (prints a count, never the token):
   ```bash
   cd ~/137/moleculefinder/moleculefinder-etl && ./.venv/bin/python3 -c 'from moleculefinder_etl import zenodo; c = zenodo.Client(zenodo.token()); print(len(c.call("GET", "/deposit/depositions?size=100")), "deposits visible: the token works")'
   ```
The token is read only by Python (python-dotenv) inside `mfetl zenodo`, sent only in the Authorization header,
redacted from every message, and taken back out of the environment for every other stage (`cli.py`).
