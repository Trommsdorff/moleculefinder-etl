# The news job on the Mac mini

MoleculeFinder's "molecules in the news" job moves from GitHub Actions (`.github/workflows/news.yml`, every six
hours) to a launchd job on Garrett's Mac mini, as the network's rule requires (`network/137-Finder-Web-Standards.md`
section 14), the same way the weekly refresh did on 2026-11-16 (`docs/MAC-WEEKLY-REFRESH.md`). Built, proved and
switched on in one session on Garrett's word (brief `../MAC-NEWS-PROMPT.md`). `news.yml` is the manual backup
(section 8).

Files: `scripts/mac/news.sh` (the job), `scripts/mac/com.137finder.moleculefinder.news.plist` (its launchd file),
`scripts/mac/with_keys.py` (hands the module the two database keys; shared with the weekly job),
`.github/workflows/mac-alarm.yml` (relays the alarm so it arrives by email; label `news-failure`),
`.github/watchdog/network_freshness.py` (the watchdog reads the public feed's age), `tests/test_mac_news.py`.

## 1. Runbook (plain language)

**What it does.** Four times a day the Mac asks Google News for recent headlines that name the catalogue's
molecules, records which molecules were named (names and counts in public; every headline, outlet and link only in
the private table), rewrites the small public list the home page reads ("In the news"), and tells search engines
about any molecule page that is new to that list. It builds nothing, deploys nothing and commits nothing. A run
takes about two minutes.

**When.** 01:50, 07:50, 13:50 and 19:50 Eastern, every day (section 3).

**Where the log is.** `~/Library/Logs/MoleculeFinder/news-YYYYMMDD-HHMMSS.log`, one per run, kept 30 days. A start
that found another news run going writes one line to `news-skipped.log`. launchd's own output (normally empty):
`launchd-news.log`. The job keeps its own copy of the code in `~/Library/Application Support/MoleculeFinder/news-checkout`
(a clone of the public repository, about 40 MB) and the time of its last good run in `news-last-ok`.

**What a good run's log looks like.** It starts `MoleculeFinder news: the scheduled job`, names the code
(`code: <sha> ...`) and `python: Python 3.12.x`, then the module's own lines: `[news] 31 queries, 55 requests after
splitting full ones (N failed), ...`, `[news] 91 molecule(s) matched in ... headline(s)`, the match list (names and
counts only), `[news] molecule_news_match: ... recorded`, `[news] feed: ... molecule(s) written to
public-data/news/in-the-news.json`, then either `nobody new to the list` or `IndexNow: ... HTTP 200`, and finally
`DONE: molecules in the news: done`. A few `a query failed (429), skipped` lines are normal (GitHub's runs had them
too).

**What an alarm looks like.** An email from GitHub that the `mac-alarm` run failed, and an open issue on
`Trommsdorff/moleculefinder-etl` titled **Molecules-in-the-news run FAILED** (label `news-failure`), with what failed,
the log path and the last 40 log lines (the job never prints a headline). A later failure comments on the same issue.
Close it by hand once a run goes green (news.yml's issue said the same; it never closed itself). The site is
unaffected either way: the home page keeps the last list and empties the block once its newest headline is a week old.

**Run it by hand.**
```bash
cd ~/137/moleculefinder/moleculefinder-etl
scripts/mac/news.sh --dry-run      # search and match only: writes nothing, pings nothing
scripts/mac/news.sh --force        # a real run now (it writes), even within two hours of the last good one
```

**Turning it on, off, and back to GitHub.**
```bash
# on (the switch session did this once)
cp scripts/mac/com.137finder.moleculefinder.news.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.137finder.moleculefinder.news.plist
# off
launchctl bootout gui/$(id -u)/com.137finder.moleculefinder.news
rm ~/Library/LaunchAgents/com.137finder.moleculefinder.news.plist
# back to GitHub: turn it off (above), then put `schedule: [{ cron: "50 */6 * * *" }]` back under `on:` in
# .github/workflows/news.yml and push.
```

## 2. Every step, check and guard of `news.yml`, in order, and how the Mac does it

Nothing is dropped silently: each row says what the Mac does instead, or why it is not needed. "Same" means the same
code runs: every rule inside `moleculefinder_etl/news.py` is unchanged and runs on the Mac exactly as on GitHub.

| # | news.yml | What it protects against | On the Mac |
|---|---|---|---|
| 1 | `schedule: '50 */6 * * *'` (+ `workflow_dispatch` with `dry_run`) | A stale list; the home page's "in the news" lagging the news | launchd, 01:50, 07:50, 13:50, 19:50 Eastern (section 3). GitHub actually fired it late and often not at all: 77 runs in its 27 days (about 2.9 a day, not 4), up to 4.9 hours late, the longest gap 15.5 hours. `news.yml` keeps `workflow_dispatch` (with `dry_run`) as the manual backup; `schedule:` removed. |
| 2 | `concurrency: molecule-news`, `cancel-in-progress: false` | Two overlapping runs racing on the same rows | A lock (`news.lock`, holding the pid): a second start exits at once, logged in `news-skipped.log`; a lock left by a dead run is taken over. It also steps aside (no alarm) while a GitHub `news.yml` run is in progress, while the weekly refresh runs (section 4), and within two hours of its own last good run (section 5). If GitHub cannot be asked whether `news.yml` is running it goes ahead with a warning: two runs at once only rewrite the same rows. |
| 3 | `permissions: contents: read` | A news run changing the repository | Its checkout is a clone of the public repository over https with no credential helper: it cannot push, and the script never commits (a test holds that). |
| 4 | `timeout-minutes: 10` | A hung request holding the slot | The same 10 minutes: a timer stops the run's whole process group, and the run is reported as TIMED OUT, with the alarm. |
| 5 | `actions/checkout@v6` | Running something other than `main` | Its own shallow clone of `origin/main` (`news-checkout`), fetched (2 min limit, no prompt possible), reset hard and cleaned; refuses a checkout that is not clean or not `origin/main`. Never the interactive checkout, never the weekly job's worktrees, so neither git can lock the other out. If the fetch fails (GitHub down) it runs the `main` it fetched last, with a warning, as long as that is under 8 days old; older, it fails and alarms. The news module reads only the committed snapshot's molecule files, which change once a week. |
| 6 | `setup-python 3.12`, no install | An install on every run; a Python the module cannot run on | Homebrew's Python 3.12 at a fixed path (`/opt/homebrew/opt/python@3.12/bin/python3.12`, checked to be 3.12.x and logged), standard library only, no install, as on GitHub (3.12.16 there, 3.12.15 here). Run with `-E -s -B` (no `PYTHON*` variable or user site-packages, no `.pyc` written) and `TZ=UTC`, as GitHub's runner. |
| 7 | env `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` from secrets | The keys reaching the logs | The real keys from the ETL's gitignored `.env` through `scripts/mac/with_keys.py` (python-dotenv, from the weekly job's `uv.lock` environment): never sourced, printed or logged; the database password is not passed. Every `MFETL_*`, `SUPABASE_*` and `GITHUB_*` variable a shell could leak in is cleared first (a stray `GITHUB_STEP_SUMMARY` would make the module write a file). A dry run blanks the keys. |
| 8 | `DRY_RUN` input through the environment, never spliced into the script | Script injection | `--dry-run` is a fixed flag; nothing from outside reaches the command line. |
| 9 | `python3 --version` | Knowing which Python ran | Logged (`python: Python 3.12.15`), with the code's commit. |
| 10 | the module: one failed search request is skipped and logged; the run refuses when more than half fail (`not writing a list built from half the news`) | A list built from half the news | Same code. A refusal exits 1: the run fails and alarms, as on GitHub. One failed request never alarms, on either machine. |
| 11 | the module: `--show-headlines` refused on GitHub (`GITHUB_ACTIONS`) | A headline in a public log | The job never passes `--show-headlines` (a test holds it), so no headline reaches the log or the public alarm issue. The alarm also redacts anything shaped like a key and writes the home folder as `~`. |
| 12 | the module: keys unset, it prints the list and exits 0 (a no-op) | A first run before the secrets existed | Stronger on the Mac: a missing key in `.env` stops the run at `with_keys.py --check` and alarms, so a broken keys file can never make the job silently do nothing. (A dry run still blanks them on purpose.) |
| 13 | the module: no molecule files, a PostgREST or Storage error (`HTTP <code>`, a match row's body withheld), the IndexNow ping not 200/202 | Writing from a broken checkout; a half-done write going unseen; pages new to the list not announced | Same code; any of them exits non-zero, and the run fails and alarms. |
| 14 | the module: `GITHUB_STEP_SUMMARY` table | Seeing the list on the run's page | The same lines are in the run's log (names and counts only). |
| 15 | job `alarm` (`needs: news`, `if: failure()`): one open `news-failure` issue at a time, "Molecules-in-the-news run FAILED", a comment on later failures; GitHub's own failed-run email | A failure nobody hears about | The job's exit trap, on a failure or a timeout: it dispatches `mac-alarm.yml` with label `news-failure`, which opens the issue (same title, same one-at-a-time rule) or comments on the open one, as github-actions[bot], and fails so GitHub emails, as a failed `news.yml` run did. If the dispatch fails it files the issue itself (no email for that one) and shows a Mac notification. Like `news.yml`, it alarms on every failed run and never closes the issue itself. A **cancelled** run (stopped, shut down) does not alarm, as a cancelled `news.yml` run (2026-10-24) did not (`if: failure()`). |
| 16 | (GitHub's machines are always on) | The machine running the job being down | **New risk, covered from outside:** the GitHub watchdog reads the age of the public feed and emails once it is more than 24 hours old (section 7). A Mac with no network at a slot leaves it to the next (4 tries over about 3 minutes; no alarm, none could be sent). |

### Not in news.yml, added on the Mac
- Logs per run, 30 days; a Mac notification on an alarm; a warning if the Mac's zone is ever not America/New_York;
  `caffeinate` while it runs; it cleans its checkout (`git clean`) and its run folder after every run.

## 3. The times

`news.yml` ran at :50 past 00, 06, 12 and 18 UTC. In Eastern time that is 19:50, 01:50, 07:50 and 13:50 in winter
(EST) and 20:50, 02:50, 08:50 and 14:50 in summer (EDT). launchd keeps local time, so the Mac runs at **01:50, 07:50,
13:50 and 19:50 Eastern** all year:

- **In winter these are news.yml's own minutes** (06:50, 12:50, 18:50, 00:50 UTC); in summer they are an hour earlier
  in UTC (05:50, 11:50, 17:50, 23:50).
- **The rotation still works.** The module starts each run from a different point in its batch list by the UTC hour
  (`now.hour // 6`). In either season each Mac start falls in a different six-hour UTC band, so all four starting
  points are asked every day. (GitHub, firing late and only about three times a day, often missed one.)
- **The clock changes.** 01:50 is before 02:00, so it exists on both change days (the spring day has no 02:00 to
  02:59). On those two days the UTC bands shift mid-day, so one starting point is asked twice and one waits until the
  next day: harmless, every search looks seven days back. On the autumn day 01:00 to 01:59 happens twice; if launchd
  were to start the job in both, the second finds the first's good run under two hours old and steps aside.
- **Nothing else on this Mac starts at :50** (read 2026-11-16 from `~/Library/LaunchAgents`). The weekly refresh starts
  at :10 (Monday 03:10, then 06:10 to 18:10 every two hours; 03:10 daily catch-ups). A news run has a 10-minute limit,
  so it is always over by :00, ten minutes before any weekly start. The nearest other starts: GravityFinder at :40
  (01:40 daily; Wednesdays also 07:40, 13:40, 19:40), PolitiFinder 05:10, TheFiscalFinder 04:20 and Mondays on the half
  hour, ThePatentFinder 00:30, 04:00, 05:00, 11:00, 12:15, 15:15, 19:00 (and its 15- and 60-minute pulls), the snapshot
  thinning 03:50. Different sites, different folders: a neighbour running at the same time costs nothing but a little
  bandwidth.
- Why these four and not others: they keep news.yml's spacing and, in winter, its exact minutes; they avoid the
  skipped spring hour; they are clear of the weekly job's :10.

## 4. The two jobs

They share nothing that either writes: the news job has its own checkout (`news-checkout`), its own lock
(`news.lock`), its own logs (`news-*.log`); it writes only the news tables (`molecule_news`, `molecule_news_match`, no
foreign key to the catalogue) and the feed in Storage, which the weekly load never touches; the weekly job writes the
catalogue tables, its own worktrees and its inputs cache, which the news job never reads. The one thing the news job
borrows is the weekly job's Python environment, for `with_keys.py`'s python-dotenv, and only to read it.

- **A news slot while the weekly refresh runs** (possible on a Monday: 07:50 or 13:50 while a retry or a long wait
  for the website's check is going): the news job sees the weekly lock held by a live process and **steps aside**:
  `stepping aside: the weekly refresh is running (pid N)`, exit 0, no alarm, no state. The next slot runs as usual
  and its seven-day search picks up what this one would have found.
- **A weekly start while a news run is going** cannot happen on the schedule (a news run is over by :00; the weekly
  starts at :10). After a wake, launchd can start both at once: the weekly job does not step aside for a news run
  (its check looks for `moleculefinder_etl.cli` builds; the news run is `moleculefinder_etl.news`), and the news job
  either sees the weekly lock and steps aside, or, if it started a moment earlier, finishes its two minutes beside it
  without touching anything the weekly job uses.

## 5. Missed runs

launchd keeps no record of starts missed while the Mac was **off** (the next slot after it boots runs as usual); it starts a job it missed while the Mac was
**asleep** once at the next wake, however many starts were missed (they are coalesced into one; this Mac never
sleeps: `sleep 0`). So a restart or a wake never fires several news runs at once. On top of that: the lock (a second
start exits at once) and the two-hour spacing (a start within two hours of the last good run steps aside, so a wake
just before a slot does not run twice). A missed slot is not caught up: the next slot's seven-day search covers it,
as GitHub's late and missing runs were covered.

## 6. Alarms

`news.yml`'s rule, matched: **one failed search request never alarms** (the module skips it and logs `a query failed
(429), skipped`); **a failed run always alarms** (more than half the requests failed, a database or Storage error,
the IndexNow ping refused, no molecule files) with the `news-failure` issue and an email, every failed run, one open
issue at a time, never closed automatically. In its 27 days on GitHub the job never failed (one run was cancelled,
no alarm). Added on the Mac: a timeout alarms; a cancel does not; a Mac with no network at all leaves the slot to the
next without an alarm (none could be sent) and the watchdog covers a long outage; a fetch that fails while the last
fetched `main` is under 8 days old runs that, with a warning.

## 7. The watchdog (stays on GitHub)

`watchdog.yml` (daily 13:00 UTC) now also reads the public feed `in-the-news.json` (a plain GET, no token; the feed
is public by design and names only molecules) and its `generated_at`, written by every good run. **Stale = more than
24 hours old**: four slots in a row wrote nothing, so the Mac is off, the agent is unloaded, or the job fails where
it cannot raise its own alarm. One or two skipped or failed slots never reach it (a failed one has already
alarmed). It would never have fired on GitHub's own history (longest gap 15.5 hours). A stale feed opens (or joins)
the network-staleness episode as `moleculefinder-news` and emails once; an unreadable feed is COULD NOT CHECK and
emails every day, as for every other target. Issue #8 (TheFiscalFinder's open episode) is left as it is; the watchdog
comments on it daily by itself.

## 8. The manual backup: what pressing "Run workflow" on `news.yml` does (after the switch)

It runs one news run on GitHub's machines, exactly as a Mac run: the same module from `main`, the same rows, the same
feed, the same IndexNow rule (only pages new to the list). It installs nothing (no lock file to pin: the module is
standard library only). Tick `dry_run` to match and log only. It is safe: if the Mac's slot comes while it runs, the
Mac steps aside; if it is pressed while a Mac run is going, both write the same rows (match rows are
insert-or-ignore by story, the names-only rows and the feed are recomputed from the whole history), so the later of the
two simply wins with the same answer give or take a headline. A failure opens or comments on the same `news-failure`
issue.

## 9. Proofs

See `HISTORY.md` (the switch record) for the numbers: the dry run from a clean checkout, parity with GitHub's most
recent run, each guard breaking one input in a scratch copy, every git and GitHub call under launchd with no terminal,
the lock and the two-jobs case.
