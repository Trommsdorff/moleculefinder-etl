# The trust reviews on the Mac mini (runbook)

The plan: `../TRUST-REVIEWS-PLAN.md` (eight reviews, agreed with Garrett 2026-11-27). Review 1, the deploy smoke, lives
in the web repo (`scripts/deploy-smoke.mjs`, run by `smoke.yml` after every production deploy). This runbook covers
the reviews that run on the Mac mini. Today that is three: **review 3, drawing truth** (built 2026-11-27, brief
`../TRUST-2-DRAWING-TRUTH-PROMPT.md`; sections 1 to 3), **review 2, one fact on every surface** (built 2026-11-27,
brief `../TRUST-3-ONE-FACT-PROMPT.md`; section 5) and **review 5, findings arithmetic** (built 2026-11-28, brief
`../TRUST-4-FINDINGS-ARITHMETIC-PROMPT.md`; section 6). All run from one script (section 4).

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
- **On the Mac:** the launchd agent `com.137finder.moleculefinder.trust-drawings` (`scripts/mac/trust-review.sh drawings`,
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
| `salts-as-ions` | Garrett, ruling 3 on the extended-solids review, 2026-11-26: keep the salts drawn as their ions; and (`later:`, 2026-11-27, Cowork's ruling A, Garrett's word) the 31 salts of a discrete organic ion | metal floating, lattice, fragments | 72 |
| `kept-as-drawn` | Garrett, the same review: stannous fluoride, sucralfate, bismuth subsalicylate, povidone-iodine keep their drawing; and (`later:`, 2026-11-27, ruling C) BHA and ivermectin | metal floating, lattice, fragments | 6 |
| `discrete-inorganic` | the survey's group c (discrete inorganic molecules, rightly drawn), named as check 3's allowlist by the trust-2 brief | lattice | 16 |

**Rules.** An entry is added only on a ruling: **Garrett rules** (Cowork reviews the chemistry and brings him the
question with a recommended answer). Never add an entry to make a finding go away. A new ruling is a new list with its
own date; a record joins an existing list only when that ruling covers it. Every entry names a record that exists and
carries a reason (a test holds both). A later ruling of the same kind joins a list under `later:` (date, by, what),
and each record it adds is `{reason, date}` with that date (2026-11-27). Commit the change on a branch with the ruling's source in the message.

The survey's classification (`survey:`) is the extended-solids survey's, copied verbatim (a test holds it equal to
`scripts/extended_solids_review.py`). A record the scope rule catches that is not classified is a finding of check 5:
classify it there (group a, b, c or d, with the survey's `why`), with Cowork reading the chemistry.

## 4. The Mac jobs (every review, one script)

`scripts/mac/trust-review.sh <review>` runs either review (it was `trust-drawings.sh` until the facts review joined it,
2026-11-27); each review has its own launchd file, lock, log, heartbeat and report:

| review | launchd agent | when | lock | heartbeat | its own limit |
|---|---|---|---|---|---|
| `drawings` | `com.137finder.moleculefinder.trust-drawings` | daily 06:30 Eastern | `trust-drawings.lock` | `drawings-last-run.json` | 30 min (it takes about one) |
| `facts` | `com.137finder.moleculefinder.trust-facts` | daily 06:45 Eastern | `trust-facts.lock` | `facts-last-run.json` | 60 min (sample about 1; Tuesday's full read: section 5) |
| `findings` | `com.137finder.moleculefinder.trust-findings` | daily 06:55 Eastern | `trust-findings.lock` | `findings-last-run.json` | 30 min (it takes about half a minute) |

- **When:** after Monday's 03:10 refresh, clear of the 07:50 news slot, on no other job's minute (the LaunchAgents
  were read 2026-11-27 and again 2026-11-28: nothing else at 06:30, 06:45 or 06:55). The findings review at 06:55
  follows the facts review: its daily sample ends about 06:46, and Tuesday's full read (317 s measured 2026-11-27) about
  06:50. A cold full read just after a deploy took 794 s once; on such a morning the two would overlap for a few
  minutes, which is harmless (each only reads, with its own lock). A start missed while the Mac slept fires once at the next wake.
- **Never in the way.** Its own lock (`~/Library/Application Support/MoleculeFinder/trust-<review>.lock`), which no
  other job reads. It runs the review as `python -m moleculefinder_etl.review.<review>`, never through `mfetl`, so the
  weekly refresh's "another build is running" check (`pgrep 'moleculefinder_etl\.cli|bin/mfetl '`) never sees it.
  While the weekly refresh (`running.lock`) or the news job (`news.lock`) runs, it waits, checking each minute, up to
  an hour; still busy after that, it stops with exit 3 and writes `did not run` and the reason in the heartbeat. The two
  reviews never wait for each other (each only reads).
- **Which code:** its own shallow clone of the public repository (`trust-checkout` in the state folder), checked out
  at `origin/main`: the code and snapshot that were published. If `origin/main` does not carry the review yet (the
  days between a local merge and Garrett's push), it runs the interactive repository's local `main` and says so in the
  log. **Python:** the weekly job's environment (`venv` in the state folder, built from `uv.lock`). The launchd file
  copies `origin/main`'s `scripts/mac/trust-review.sh` to `trust-review-<review>.sh` in the state folder and runs it.
- **Exit:** 0 ran; 2 could not run (the heartbeat says why); 3 did not run (another job held the Mac for the hour).
- **Logs:** `~/Library/Logs/MoleculeFinder/trust-<review>-<stamp>.log` (kept 30 days); launchd's own
  `launchd-trust-<review>.log` beside them.
- **No alarm, no email** (yet): the plan's morning email (build-order step 4) will read the heartbeats and the reports.

### Install, reload, check, run now

```bash
for r in drawings facts findings; do
  cp ~/137/moleculefinder/moleculefinder-etl/scripts/mac/com.137finder.moleculefinder.trust-$r.plist ~/Library/LaunchAgents/
  launchctl bootout gui/$(id -u)/com.137finder.moleculefinder.trust-$r 2>/dev/null
  launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.137finder.moleculefinder.trust-$r.plist
done
launchctl print gui/$(id -u)/com.137finder.moleculefinder.trust-facts | head -40      # state, the 06:45 trigger
launchctl kickstart gui/$(id -u)/com.137finder.moleculefinder.trust-facts             # a run now (it only reads)
```

By hand: `scripts/mac/trust-review.sh facts --full` (the Tuesday read, any day), `--sample` (the day's sample, even on
a Tuesday); `scripts/mac/trust-review.sh drawings --no-live`; `scripts/mac/trust-review.sh findings` (it takes no option). To stop one for good: `launchctl bootout
gui/$(id -u)/com.137finder.moleculefinder.trust-<review>` and remove the installed plist.

## 5. One fact, every surface (review 2)

The same fact is stated in many places on the site, each built by different code: a molecule's formula on its own
page, in a comparison, in a board, in the search index, in structured data. When two disagree, a reader who sees both
stops trusting either. This review reads pages from the **live site**, pulls every fact each page states and compares
each with the snapshot `main` holds and, through it, with every other surface that states it.

- **Code:** `moleculefinder_etl/review/facts.py` (its docstring is the method), `moleculefinder_etl/review/facts_differences.yaml`
  (the deliberate differences). Tests: `tests/test_review_facts.py`, `tests/test_mac_trust.py`.
- **By hand:** `./.venv/bin/python3 -m moleculefinder_etl.cli review facts` (= `mfetl review facts`; `--full` reads
  every sitemap address, `--sample` the day's sample, `--date`, `--out`, `--snapshot`, `--site`). A hand run through
  `mfetl` (either review) is "another build" to the weekly refresh, which steps aside while it runs (seen 2026-11-27 on a
  dry run); the Mac job runs the module directly and never is. Run a review by hand clear of Monday's refresh, or as
  `python -m moleculefinder_etl.review.facts`.
- **It only reads.** Cold reads of https://moleculefinder.com, four at a time, each reader pausing a quarter second
  after each page, User-Agent `MoleculeFinder-trust-review/1 (+https://moleculefinder.com/about)`. No PubChem request,
  no database key. It writes only into `trust-reports/`.

**Which pages.** A pinned set (`PINNED` in the code: every page family and variant, each with its written reason,
listed in every report) plus 150 sitemap addresses spread across the families (two of each family, the rest by the
family's size), drawn by a seed made from the date (`moleculefinder-facts-<date>`): two runs on a day read the same
pages, tomorrow reads others. Each molecule page read also has its embed card read. **On Tuesdays it reads every
sitemap address** (and every molecule's embed card), the day after Monday's refresh. A page it could not read is
listed NOT READ with the reason and contributes nothing: it is never counted as agreeing. A sitemap address answering
404 or 410 is read and is a finding.

**The facts** (the brief's numbering): 1 name, formula and weight (a molecule page's top line, Properties, JSON-LD,
short answers, meta description; /vs; every row and card; the search index; the embed card; the RSS feed; structure
hubs; the size hub); 2 the LD50 (value, unit, qualifier, species, route, chemical form together); 3 the hazard label
(signal word, pictograms, statements, attribution); 4 status (a label page's over the counter or prescription line
against the label's DailyMed document type; a molecule page's licence and status lines against its record); 5 counts
(hubs, /explore, labels, worlds, boards' length and leader, the site-wide counts; not a findings headline, review 5's);
6 the data date (Data refreshed, this week's molecule, the feed's build date) against `meta.json`; 7 text naming a
formula, weight, drawing or 3D model the molecule's page lacks (a sentence that says it has none is not one); 8 a title
or description promising formula, structure or 3D the page lacks (reported for the freeze release after 2026-12-08,
never fixed while titles are frozen); 9 links to a page the catalogue lacks or that answers 404 or 410, and a name
linking to another molecule's page.

**How values are compared (the rounding rules, stated once; the same words are in the code's docstring).**
Formula: equal when the element counts and the charge are equal, any order; written differently from the record is its
own shape, "one value, written two ways" (in a page's running text that shape is ruled, below: the same atoms in the
way a reader knows them). **Weight (ruled 2026-11-27, Garrett's word on Cowork's ruling 1): a shown weight agrees when
it equals the record's value rounded half-up to the precision shown, down to whole grams** (253.81 and 254 for
253.8089). Anything else is a finding: "shown to more precision than the record" (more decimals than the record has),
"rounded the wrong way" (within half a unit of the last printed place, but not the half-up rounding: 440 for 440.5),
"two different values" (everything else). LD50: the number exact, the qualifier words, the species and route words the
site uses, the form "pure <name>"; the site prints every part through one phrase (web `scripts/ld50-words.mjs`), and a
/vs text writes its figures as `{ld50:<slug>}` (the ETL compile refuses a figure typed by hand). Status: a molecule
page says over the counter, prescription, or (ruled 2026-11-27, ruling 4) "Sold over the counter in some products and
on prescription in others", which agrees only where the record's `is_otc` is true.
Counts are integers; a week range must contain the snapshot's refreshed date. In running text a value belongs to the
molecule named nearest before it in the sentence (or the one after "for"); a value that matches any molecule the
sentence or page names is never a finding, and a group (CH3), a vitamin's letter (B12) or a value nobody can own is
counted as "not attributed" and listed, not compared.

**Reading the report** (`trust-reports/facts-<date>.md` and `.json`): the first line is the verdict (classes found,
findings, facts compared, pages read, pages not read). Findings are grouped by CLASS: the fact, the surface it was read
on, what it was compared with, and the shape ("two different values", "rounded the wrong way", "one value, written
two ways", "stated here, absent there", ...), each with its count over its denominator (the facts of that kind compared
on that surface), the pages, up to ten addresses, the change since the last run, and the recommended fix. A class on two
consecutive runs goes to `trust-reports/QUEUE.md` once, prefixed `facts:` (the drawing review's queue, shared). The
heartbeat is `trust-reports/facts-last-run.json`.

**Deliberate differences** (`facts_differences.yaml`) are the only excuse, each one ruling with its date, who ruled and
where it is written: the conventional formula on panel pages (Garrett, 2026-11-26, extended to the wrong-drawings
panels), the repeat-unit hub memberships (Garrett, 2026-11-27, ruling 1 at the drawing findings' deploy) and a
conventional formula in a page's running text whose atoms are exactly the record's (NaHCO3 for CHNaO3; Garrett's word
on Cowork's ruling 2, 2026-11-27). Each
excused case is counted and listed in the report, never hidden. **Add an entry only on a ruling; never to make a finding
go away** (section 3's rule; a test holds that exactly these entries exist and that nothing else is excused).

**The repetition measure** (Tuesday's full read only; reported, never a finding; Garrett asked for the number before
any rewrite is considered). Each page's visible text in its main part is cut into pieces: every paragraph, list item,
cell, heading, caption or link with no such element inside it, split into sentences, whitespace collapsed, case kept.
A piece is **shared** when it appears on at least half of the family's pages read; a page's **unique share** is the
characters of the pieces found on that page alone over all its characters. Per family (three pages or more): the
median and range of the unique share, the median shared share, the ten longest shared pieces with how many pages carry
each, and the ten pages with the least text of their own.

**Timing.** The daily sample (about 200 pages and their embed cards) takes about a minute. **The full read**
(every sitemap address and every molecule's embed card, about 2,700 reads) was measured on 2026-11-27: see HISTORY.md
for the figure; 06:45 leaves it well clear of the 07:50 news slot.

## 6. Findings arithmetic (review 5)

The findings pages are the pages sent to reporters (five emails on 2026-11-23: "112 of the 300 medicine labels list
one of the six dyes"). A reporter adds the columns up. This review reads every findings address from the **live site**
every day and checks that every number on them adds up, against the page's own data, against the other two forms of
it, against the labels themselves and against what was pitched. No sampling: every address, every row, every label.

- **Code:** `moleculefinder_etl/review/findings.py` (its docstring is the method), `moleculefinder_etl/review/pitched_numbers.yaml`
  (what was told to people outside) and `review/pitched/` (the labels as they stood when it was sent). Tests:
  `tests/test_review_findings.py` (a world of eight labels rendered with the web's markup; each check found and not
  found; the recomputation against the transform on the real snapshot), `tests/test_mac_trust.py`.
- **By hand:** `./.venv/bin/python3 -m moleculefinder_etl.cli review findings` (= `mfetl review findings`; `--out`,
  `--snapshot`, `--date`, `--site`). The same caution as section 5: a hand run through `mfetl` is "another build" to the
  weekly refresh; run it clear of Monday's refresh, or as `python -m moleculefinder_etl.review.findings`.
- **What it reads.** The 14 findings addresses (`/findings`, `/findings/dyes-in-medicines`, its seven dye pages and
  `none-listed`, `/findings/inactive-ingredients` and its three ingredient pages; the sitemap is checked to list exactly
  these), the two `data.csv` and two `data.json`, a HEAD of every `/whats-in` page the tables link (300), each page's
  share image and feed, and every rule or guidance the pages link (eCFR, fda.gov, the Federal Register). From the
  snapshot ETL `main` holds: `products.json` (the declared label set), `meta.json` and the two findings files; the two
  code tables that define the findings (`colour_additives.yaml`, `inactive_groups.yaml`); and each label's own
  ingredient list from the **weekly job's DailyMed cache** (`~/Library/Application Support/MoleculeFinder/raw_cache`,
  read only; the products file keeps one row per molecule, so a label naming two forms of lactose shows one there).
  About 340 addresses, about 30 seconds. No PubChem request, no database key; it writes only into `trust-reports/`.
- **The checks** (the brief's numbering, each finding in a named class): 1 every number a page prints equals the count
  made from its data's rows, with the data's denominators; 2 the table, the CSV and the JSON hold the same labels with the
  same values (a multi-valued cell compared as a set), the documented CSV header, the CC0 licence on the page, in the
  JSON and in the Dataset; 3 the parts add up (over the counter plus prescription; a sub-page's two lists disjoint and
  whole and equal to the main table's filter; the none page exactly the labels with no FD&C or D&C colour, by the page's
  own rule; a label under two dyes once in the headline; the forms cover an ingredient's count; the JSON's totals equal
  its rows); 4 **recomputed** from the labels' own codes, written in the review and never importing
  `transform/findings.py` (the routes are in neither source, so the by-mouth counts are held by 1 and 3); 5 the label set
  (the declared 300, none twice, each `/whats-in` page answers, each DailyMed link carries the label's own set id and
  version, a route reading "Not read" listed); 6 the familiar labels the text names have that status; 7 the dates; 8
  **pitched numbers**; 9 citations (linked, the text names the section its link points at, the link answers); 10 share
  images and feeds.
- **eCFR and the Federal Register** answer an automated reader with a "Request Access" page. For those two the review
  asks the publisher's own API instead (eCFR's versioner: the section exists and is not removed; the Federal Register's
  documents API: the document exists) and says so in the report; a link that answers neither way is "not read".
- **Pitched numbers.** `pitched_numbers.yaml`: each figure as it was told, where it lives in the finding, and whether a
  FILE confirms it was sent (the tracker in `../outreach/` names "112 of 300" and "four Red No. 3 labels"; 47 of 116 and
  65 of 184 were on the page the emails linked but no file holds the emails' text, so they are marked unconfirmed). A
  live number no longer equal to a pitched one is the class **"a pitched number moved"**: the verdict line starts with
  it, it heads the report, it goes to `QUEUE.md` the same day, and the report says which labels moved and why against
  `pitched/`. Add a pitch when one is sent; never edit a sent figure. The repository is public: outlets only, contacts
  stay in the tracker.
- **The queue.** Every class on two consecutive runs (the plan's rule), except "a pitched number moved" and the
  recomputation class, which are queued the first day they are seen. Lines are prefixed `findings:`.
- **The report:** `trust-reports/findings-<date>.md` and `.json`: the verdict line (classes, findings, numbers checked,
  addresses read and not read), the pitched figures table, each class with its count over its denominator, up to ten
  cases, the change since the last run and the fix; the recomputation (counts compared, which source each label's
  ingredients came from); numbers checked by check; the denominators; every address read. The heartbeat is
  `trust-reports/findings-last-run.json`.

