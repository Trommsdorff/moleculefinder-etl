# The trust reviews on the Mac mini (runbook)

The plan: `../TRUST-REVIEWS-PLAN.md` (eight reviews, agreed with Garrett 2026-11-27). Review 1, the deploy smoke, lives
in the web repo (`scripts/deploy-smoke.mjs`, run by `smoke.yml` after every production deploy). This runbook covers
the reviews that run on the Mac mini. Today that is one: **review 3, drawing truth** (built 2026-11-27, brief
`../TRUST-2-DRAWING-TRUTH-PROMPT.md`).

## 1. What the drawing-truth review is

A machine look at every structure drawing the site shows, every day, so that a drawing that is not true is found the
day it appears (a new molecule in a tranche, a PubChem record that changes, a seed edit), not when a person happens to
read the page. Between 2026-11-15 and 2026-11-27 eighteen live pages were found by hand: lattices drawn as molecules,
a mixture drawn as a molecule, metals drawn floating beside the atoms they bond.

- **Code:** `moleculefinder_etl/review/drawings.py` (the checks, the report), `moleculefinder_etl/review/drawings_rulings.yaml`
  (the allowlists, the survey's classification, the pinned 3D models and pages). Tests: `tests/test_review_drawings.py`,
  `tests/test_mac_trust.py`.
- **By hand:** `./.venv/bin/python3 -m moleculefinder_etl.cli review drawings` (= `mfetl review drawings`; `--no-live`
  skips the live site, `--out DIR` writes elsewhere, `--date` sets the run's date).
- **On the Mac:** the launchd agent `com.137finder.moleculefinder.trust-drawings` (`scripts/mac/trust-drawings.sh`,
  `scripts/mac/com.137finder.moleculefinder.trust-drawings.plist`), **every day at 06:30 Eastern**.
- **It only reads.** It reads the snapshot that ETL `main` holds (`data/snapshots`), the seeds, and about 70 pages of
  https://moleculefinder.com; it makes no PubChem request, draws nothing, loads no database key, commits nothing. It
  writes only into `~/137/moleculefinder/trust-reports/` (that folder is not a git repository; nothing is committed
  daily). **It never blocks, stops or changes the weekly refresh, the news job or a deploy.**

### The ten checks (the brief's numbering)

| # | fact | what is checked | read |
|---|---|---|---|
| 1 | atoms | the structure each drawing is drawn from has the record's formula and charge; the SVG draws exactly that structure (every bond, every atom); a pair's second drawing draws its molecule. Repeat units are chain fragments by design and are named, not formula-checked | every drawing, every repeat unit, every pair drawing |
| 2 | metal floating | a metal or metalloid with no bond, beside a piece holding atoms that could bond it (N, O, S, P, a halogen, a C-), no `metal_bonds` entry, not on an allowlist | every drawing |
| 3 | lattice as molecule | no C-H, a neutral bonded piece holding a metal or metalloid (or the family is inorganic or mineral), no `structure_none` or `metal_bonds` entry, not on an allowlist | every drawing |
| 4 | fragments | each drawing of more than one piece is a salt, a hydrate or solvate, a mixture or polymer, or unexplained (the last two are findings); a one-piece drawing of a polymer record (family polymer or polysaccharide, or its summary says polymer or polysaccharide) is a finding | every drawing |
| 5 | classification | every record the extended-solids survey's scope rule catches is classified in `drawings_rulings.yaml` `survey` | the scope rule's records |
| 6 | seeds | every `structure_none`, `structure_display` (sugars and metal bonds), `repeat_units` and `structure_parts` entry names a record that exists, passes its own build-time check, and the snapshot carries what it makes | every entry |
| 7 | stereo | a record that specifies centres whose drawing shows none; fewer wedges than specified centres; a centre drawn that the record does not specify without `stereo_from` | every drawing |
| 8 | 3D against 2D | a 3D model on a page with no drawing, a panel or a metal-bonds drawing; a model compound whose connectivity is not the drawing's (models pinned in `drawings_rulings.yaml` `models`) | every page with a 3D model |
| 9 | live equals built | pinned pages (every seed entry and a hand-picked one of each other kind, each with its reason) plus 40 molecule pages sampled by a seed made from the date: the drawing served is byte for byte the snapshot's, a page with no drawing serves none, the 3D control matches the record, the notes line is the seed's | about 70 pages |
| 10 | part layers | every part layer's atoms and bonds exist in its drawing, its marks sit on its atoms in the SVG, and its rule lights the same atoms today (a curated part's `expect` included) | every part layer |

## 2. How to read a report

`trust-reports/drawings-<date>.md` (and the same as `.json`). **The first line is the verdict:** how many finding
classes, how many records they name, how many records were read, how many pages were read live, how many were not read.
A page it could not read is listed as NOT READ with the reason, never counted as a pass.

Then one section per **class**, named by the fact, the surface and the shape (for example
`metal floating / structure drawing / an s-block ion beside an anion`): the count and its denominator ("32 of 896
drawings"), the change since the last run (+/-, which records came and went), up to ten addresses, and the recommended
fix. Then what each check read, what the rulings covered today, and the pages read live.

**The queue:** a class found on two consecutive runs is appended to `trust-reports/QUEUE.md` that day, once, with a
one-line recommended fix. Tick the line when the fix is merged or a ruling covers it.

**The heartbeat:** `trust-reports/drawings-last-run.json`: time, state (`ran`, `could not run`, `did not run`), the
verdict and the exit code. The job's log: `~/Library/Logs/MoleculeFinder/trust-drawings-<stamp>.log` (kept 30 days);
launchd's own: `launchd-trust-drawings.log` beside it.

A finding is a fact about the site, not a failure of the job: the job exits 0 whatever it found. Nothing is fixed
automatically. Findings go to Cowork, who reviews the chemistry and briefs a fix.

## 3. Adding an allowlist entry, and who rules on one

`moleculefinder_etl/review/drawings_rulings.yaml`, under `allow:`. Each list is **one ruling**: `date`, `by` (who
ruled, and where it is written down), `what` (the ruling in a line), `covers` (which facts it answers:
`metal-floating`, `lattice`, `fragments`) and `records` (`slug: reason`). Today:

| list | ruling | covers | records |
|---|---|---|---|
| `salts-as-ions` | Garrett, ruling 3 on the extended-solids review, 2026-11-26: keep the salts drawn as their ions | metal floating, lattice, fragments | 41 |
| `kept-as-drawn` | Garrett, the same review: stannous fluoride, sucralfate, bismuth subsalicylate, povidone-iodine keep their drawing | metal floating, lattice, fragments | 4 |
| `discrete-inorganic` | the survey's group c (discrete inorganic molecules, rightly drawn), named as check 3's allowlist by the trust-2 brief | lattice | 16 |

**Rules.** An entry is added only on a ruling: **Garrett rules** (Cowork reviews the chemistry and brings him the
question with a recommended answer). Never add an entry to make a finding go away. A new ruling is a new list with its
own date; a record joins an existing list only when that ruling covers it. Every entry names a record that exists and
carries a reason (a test holds both). Commit the change on a branch with the ruling's source in the message.

The survey's classification (`survey:`) is the extended-solids survey's, copied verbatim (a test holds it equal to
`scripts/extended_solids_review.py`). A record the scope rule catches that is not classified is a finding of check 5:
classify it there (group a, b, c or d, with the survey's `why`), with Cowork reading the chemistry.

## 4. The Mac job

- **When:** every day at 06:30 Eastern (after Monday's 03:10 refresh; 80 minutes clear of the 07:50 news slot; no
  other job on this Mac starts at that minute). A start missed while the Mac slept fires once at the next wake.
- **Never in the way.** Its own lock (`~/Library/Application Support/MoleculeFinder/trust-drawings.lock`), which no
  other job reads. It runs the review as `python -m moleculefinder_etl.review.drawings`, never through `mfetl`, so the
  weekly refresh's "another build is running" check (`pgrep 'moleculefinder_etl\.cli|bin/mfetl '`) never sees it.
  While the weekly refresh (`running.lock`) or the news job (`news.lock`) runs, it waits, checking each minute, up to
  an hour; still busy after that, it stops with exit 3 and writes `did not run` and the reason in the heartbeat.
- **Which code:** its own shallow clone of the public repository (`trust-checkout` in the state folder), checked out
  at `origin/main`: the code and snapshot that were published. If `origin/main` does not carry the review yet (the
  days between a local merge and Garrett's push), it runs the interactive repository's local `main` and says so in the
  log. **Python:** the weekly job's environment (`venv` in the state folder, built from `uv.lock`).
- **Exit:** 0 ran; 2 could not run (the heartbeat says why); 3 did not run (another job held the Mac for the hour).
- **No alarm, no email** (yet): the plan's morning email (build-order step 4) will read the heartbeat and the report.

### Install, reload, check, run now

```bash
cp ~/137/moleculefinder/moleculefinder-etl/scripts/mac/com.137finder.moleculefinder.trust-drawings.plist ~/Library/LaunchAgents/
launchctl bootout gui/$(id -u)/com.137finder.moleculefinder.trust-drawings 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.137finder.moleculefinder.trust-drawings.plist
launchctl print gui/$(id -u)/com.137finder.moleculefinder.trust-drawings | head -40     # state, the 06:30 trigger
launchctl kickstart gui/$(id -u)/com.137finder.moleculefinder.trust-drawings            # a run now (it only reads)
```

To stop it for good: `launchctl bootout gui/$(id -u)/com.137finder.moleculefinder.trust-drawings` and remove the
installed plist.
