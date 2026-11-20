"""Report logic for the 137 network freshness watchdog.

Extracted from .github/workflows/watchdog.yml on 2026-09-09 so the decision
table can be tested offline against a stubbed API. The workflow injects a real
urllib-backed `api`; the tests inject a dict-backed one. Nothing here performs
I/O of its own, and nothing here writes to GitHub — `build_report` classifies,
`decide` chooses the action, and the workflow carries it out.

The rationale for the watchdog itself lives in the workflow header. The rule
that matters here: COULD NOT CHECK is never a pass. See `decide`.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field

OWNER = "Trommsdorff"

# A repo's own issue counts as "this failure is already known" when its title
# says something failed. Both TheFiscalFinder failure issues to date matched
# ("Monthly data freshness FAILED", "Publish code FAILED").
FAILURE_TITLE = re.compile(r"fail", re.IGNORECASE)

# A monthly cron may land a day or two late; do not call it missing until then.
MONTHLY_GRACE_DAYS = 2


@dataclass(frozen=True)
class Target:
    repo: str
    workflow: str  # workflow FILE, stable across display-name edits
    max_age_days: int  # 2x cadence + slack
    cadence: str  # "weekly" | "monthly"
    # A refresh that runs OFF GitHub (on the Mac mini, the network's rule since 2026-11-09) leaves no
    # workflow run behind. When it commits to the repo's main branch, the newest commit that touches
    # one of `commit_paths` and whose first line matches `commit_subject` counts as a success too, alongside
    # any green run of `workflow` (which stays as the manual backup). None: the runs are the only signal.
    commit_subject: str | None = None
    # Asking by path keeps the answer on the first page however many other commits a week has
    # (MoleculeFinder's sessions pushed 77 between two Monday refreshes in November 2026). Each path is
    # asked separately and the newest match wins.
    commit_paths: tuple[str, ...] = ()


# MoleculeFinder (2026-11): the weekly refresh moves to the Mac mini (scripts/mac/weekly-refresh.sh).
# Every run that gets as far as its commit stamps data/LAST_CHECK and pushes "etl: refresh YYYY-MM-DD"
# (or, in a week with nothing new, "etl: no changes YYYY-MM-DD [heartbeat]") to main; a failed run's
# heartbeat touches the same file but says "etl: run failed" and does not count. Sessions never touch it. The GitHub workflow wrote the same subjects, so either machine
# counts. 8 days, not 10: the Mac runs early Monday Eastern and catches up daily at 03:10, so a week
# with no success by the Wednesday check means the Monday run and two catch-ups all failed or the Mac
# has been off since Monday; that is worth an email that day. The Mac's own alarm issue covers a run
# that committed but did not get its data PR merged and live.
# Two paths (2026-11-16, the switch): data/LAST_CHECK (every Mac commit, and both heartbeats) and
# data/snapshots/meta.json (every refresh that changed the snapshot, on either machine). GitHub's own refresh
# commits never touched LAST_CHECK, so a GitHub refresh whose run ended red for a reason after the commit
# (2026-11-16: run 43885851341 built, committed 366a6ab and shipped, but its web check failed) would leave
# MoleculeFinder looking 8 days stale in the week of the switch, before the Mac's first Monday.
MF_COMMIT_SUBJECT = r"^etl: (refresh|no changes) \d{4}-\d{2}-\d{2}"

TARGETS = [
    Target("judicialfinder", "refresh-data.yml", 10, "weekly"),
    Target("thefiscalfinder", "refresh-data.yml", 40, "monthly"),
    Target("gravityfinder", "freshness.yml", 10, "weekly"),
    Target("moleculefinder-etl", "etl.yml", 8, "weekly",
           commit_subject=MF_COMMIT_SUBJECT, commit_paths=("data/LAST_CHECK", "data/snapshots/meta.json")),
]

# MoleculeFinder's news job (2026-11) moves to the Mac mini too (scripts/mac/news.sh). It commits nothing, so it
# leaves no run and no commit behind; what it does leave is public by design: every good run rewrites the feed
# the home page reads, stamped `generated_at`. The watchdog reads that stamp with a plain unauthenticated GET
# (never the GitHub token: the feed is on Supabase Storage).
# STALE AFTER 24 HOURS. The Mac runs it four times a day (01:50, 07:50, 13:50, 19:50 Eastern), so a day without a
# new feed means four slots in a row wrote nothing: the Mac is off, the agent is unloaded, or the job is failing
# where it cannot raise its own alarm (no network). One or two skipped slots (a weekly refresh running, a failed
# run the next slot repairs, which the job's own news-failure alarm already reports) never reach it. On GitHub
# the cron fired late and often not at all (77 runs in its 27 days, the longest gap 15.5 hours), so the limit
# would never have fired on that history either. And the site needs no faster alarm: the home page keeps the last
# feed and only empties the block once its newest headline is a week old.
NEWS_FEED_URL = ("https://nzhhjdbgogfidjrsuqiv.supabase.co/storage/v1/object/public/"
                 "public-data/news/in-the-news.json")


@dataclass(frozen=True)
class Feed:
    name: str  # how the report and the episode issue name it ("- **name**")
    url: str  # a public JSON with a `generated_at` ISO timestamp (UTC)
    max_age_hours: int


FEEDS = [Feed("moleculefinder-news", NEWS_FEED_URL, 24)]

OK = "ok"
STALE = "stale"
UNKNOWN = "unknown"  # could not check — the starvation case, always an alarm
KNOWN_WAITING = "known_waiting"  # monthly cron, failure already tracked upstream


@dataclass
class Finding:
    repo: str
    state: str
    line: str  # markdown, one bullet or one summary phrase


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def _of(self, state: str) -> list[Finding]:
        return [f for f in self.findings if f.state == state]

    @property
    def unknown(self) -> list[Finding]:
        return self._of(UNKNOWN)

    @property
    def stale(self) -> list[Finding]:
        return self._of(STALE)

    @property
    def waiting(self) -> list[Finding]:
        return self._of(KNOWN_WAITING)

    @property
    def ok(self) -> list[Finding]:
        return self._of(OK)

    @property
    def all_clear(self) -> bool:
        return not (self.unknown or self.stale or self.waiting)

    def detail(self) -> str:
        """The problem block quoted into the issue body or comment."""
        blocks = [f.line for f in self.unknown + self.stale + self.waiting]
        out = "\n".join(blocks) if blocks else "- No target is outside its freshness window."
        if self.notes:
            out += "\n\n" + "\n".join(f"> {n}" for n in self.notes)
        healthy = "; ".join(f.line for f in self.ok)
        return out + "\n\nHealthy: " + (healthy or "none")


def _parse(ts: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _next_month_first(when: _dt.datetime) -> _dt.datetime:
    """First of the month after `when` — the next firing of a day-1 monthly cron."""
    year, month = when.year, when.month + 1
    if month > 12:
        year, month = year + 1, 1
    return when.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)


def _open_failure_issue(api, repo: str, report: Report) -> str | None:
    """URL of an open issue in `repo` whose title says something failed, or None.

    A probe that cannot read issues returns None on purpose: the softening in
    `build_report` is a concession, so losing it fails toward the alarm, never
    away from it. The reason is recorded so the report says why.
    """
    try:
        items = api(f"https://api.github.com/repos/{OWNER}/{repo}/issues?state=open&per_page=100")
    except Exception as e:  # noqa: BLE001 - any failure means "cannot claim it is known"
        report.notes.append(
            f"Could not read {repo}'s own issues ({type(e).__name__}: {e}), so its failure "
            f"could not be confirmed as already-tracked. Reporting it as staleness. If this "
            f"persists, NETWORK_READ_TOKEN needs `Issues: Read` alongside `Actions: Read`."
        )
        return None
    for it in items:
        if "pull_request" in it:
            continue
        if FAILURE_TITLE.search(it.get("title", "")):
            return it.get("html_url")
    return None


def _newest_refresh_commit(api, t: Target) -> dict | None:
    """The newest commit on main whose first line matches ``t.commit_subject``, as a run-shaped dict
    (``updated_at``, ``created_at``, ``html_url``), or None. Raises when the API cannot be read: the
    caller reports that as COULD NOT CHECK, never as a pass."""
    pattern = re.compile(t.commit_subject or "")
    found: list[dict] = []
    for p in t.commit_paths or ("",):
        path = f"&path={p}" if p else ""
        commits = api(
            f"https://api.github.com/repos/{OWNER}/{t.repo}/commits?sha=main{path}&per_page=30"
        )
        for c in commits:
            subject = (c.get("commit", {}).get("message") or "").splitlines()[:1]
            if subject and pattern.search(subject[0]):
                when = c["commit"]["committer"]["date"]
                found.append({"updated_at": when, "created_at": when, "html_url": c.get("html_url", "")})
                break
    return max(found, key=lambda r: _parse(r["updated_at"]), default=None)


def _classify(api, t: Target, now: _dt.datetime, report: Report) -> Finding:
    runs_url = (
        f"https://api.github.com/repos/{OWNER}/{t.repo}"
        f"/actions/workflows/{t.workflow}/runs?status=success&per_page=1"
    )
    try:
        runs = api(runs_url).get("workflow_runs", [])
        if t.commit_subject:
            commit = _newest_refresh_commit(api, t)
            if commit:
                runs = sorted(runs + [commit], key=lambda r: _parse(r["updated_at"]), reverse=True)
    except Exception as e:  # noqa: BLE001 - fail loud; see workflow header
        return Finding(
            t.repo,
            UNKNOWN,
            f"- **{t.repo}** — COULD NOT CHECK ({type(e).__name__}: {e}). "
            f"Treat as broken until proven otherwise.",
        )

    if not runs:
        what = f"`{t.workflow}` run" + (" or refresh commit" if t.commit_subject else "")
        return Finding(
            t.repo, UNKNOWN, f"- **{t.repo}** — no successful {what} on record at all."
        )

    run = runs[0]
    when = _parse(run["updated_at"])
    age = (now - when).days
    if age <= t.max_age_days:
        return Finding(t.repo, OK, f"{t.repo} — last green {age}d ago ({when:%Y-%m-%d})")

    stale = Finding(
        t.repo,
        STALE,
        f"- **{t.repo}** — last successful refresh was **{age} days ago** "
        f"({when:%Y-%m-%d}); the limit for this cron is {t.max_age_days} days.\n"
        f"  Last green run: {run['html_url']}",
    )

    if t.cadence != "monthly":
        return stale

    # A monthly cron that failed once is not unknown staleness: it is a known
    # failure with a known next attempt. Only say so when the target repo is
    # actually carrying that failure, and only until the next firing is due.
    try:
        sched = api(
            f"https://api.github.com/repos/{OWNER}/{t.repo}"
            f"/actions/workflows/{t.workflow}/runs?event=schedule&per_page=20"
        ).get("workflow_runs", [])
    except Exception as e:  # noqa: BLE001
        report.notes.append(
            f"Could not read {t.repo}'s scheduled run history ({type(e).__name__}: {e}); "
            f"reporting it as staleness."
        )
        return stale

    failed_since = [
        r
        for r in sched
        if r.get("conclusion") != "success" and _parse(r["created_at"]) > when
    ]
    if len(failed_since) != 1:
        # Zero means the cron never fired at all (the starvation shape); two or
        # more means the next scheduled run also did not succeed. Both alarm.
        return stale

    failed = failed_since[0]
    due = _next_month_first(_parse(failed["created_at"])) + _dt.timedelta(days=MONTHLY_GRACE_DAYS)
    if now >= due:
        return stale

    tracked = _open_failure_issue(api, t.repo, report)
    if not tracked:
        return stale

    return Finding(
        t.repo,
        KNOWN_WAITING,
        f"- **{t.repo}** — stale ({age} days, limit {t.max_age_days}) but KNOWN and WAITING: "
        f"its {_parse(failed['created_at']):%Y-%m-%d} scheduled run failed, the repo is tracking "
        f"that at {tracked}, and this is a monthly cron whose next scheduled run is "
        f"{_next_month_first(_parse(failed['created_at'])):%Y-%m-%d}. Not counted as unknown "
        f"staleness. This will alarm if that run does not succeed either.\n"
        f"  Failed run: {failed['html_url']}",
    )


def _classify_feed(public, f: Feed, now: _dt.datetime) -> Finding:
    """A public feed's age, from its own `generated_at`. Unreadable, unparsable or with no stamp is COULD
    NOT CHECK (fail loud), never a pass."""
    try:
        if public is None:
            raise RuntimeError("the watchdog was given no way to read a public URL")
        when = _parse(str(public(f.url)["generated_at"]))
        if when.tzinfo is None:
            raise ValueError(f"generated_at has no time zone: {when.isoformat()}")
    except Exception as e:  # noqa: BLE001 - fail loud; see workflow header
        return Finding(f.name, UNKNOWN, f"- **{f.name}** — COULD NOT CHECK the feed {f.url} "
                                        f"({type(e).__name__}: {e}). Treat as broken until proven otherwise.")
    hours = (now - when).total_seconds() / 3600
    if hours <= f.max_age_hours:
        return Finding(f.name, OK, f"{f.name} — feed written {hours:.0f}h ago ({when:%Y-%m-%d %H:%M} UTC)")
    return Finding(
        f.name,
        STALE,
        f"- **{f.name}** — the public news feed was last written **{hours:.0f} hours ago** "
        f"({when:%Y-%m-%d %H:%M} UTC); the limit is {f.max_age_hours} hours (four six-hourly runs).\n"
        f"  The news job runs on the Mac mini (scripts/mac/news.sh): is the Mac on, and is the launchd agent "
        f"com.137finder.moleculefinder.news loaded? Its log: ~/Library/Logs/MoleculeFinder/news-*.log.\n"
        f"  Feed: {f.url}",
    )


def build_report(api, now: _dt.datetime, public=None) -> Report:
    """``api`` reads GitHub with the read token; ``public`` reads a public URL with no credentials (the
    feeds). A missing ``public`` makes every feed COULD NOT CHECK, never a pass."""
    report = Report()
    for t in TARGETS:
        report.findings.append(_classify(api, t, now, report))
    for f in FEEDS:
        report.findings.append(_classify_feed(public, f, now))
    return report


# ── The decision table ───────────────────────────────────────────────────────
# Actions the workflow can carry out. Exit 1 is what sends Garrett an email.
CREATE = "create"  # open a new episode issue
COMMENT = "comment"  # add to the open episode issue
CLOSE = "close"  # comment "recovered", then close
NONE = "none"


@dataclass
class Decision:
    action: str
    exit_code: int
    why: str


# The repos an episode issue already names as a problem: the bullets `- **repo** —` that the
# report writes into the issue body and every daily comment.
REPORTED = re.compile(r"^- \*\*([A-Za-z0-9._-]+)\*\*", re.MULTILINE)


def reported_repos(issue_text: str) -> frozenset[str]:
    return frozenset(REPORTED.findall(issue_text or ""))


def decide(report: Report, issue_open: bool, known: frozenset[str] | set[str] = frozenset()) -> Decision:
    """Choose what to do. Quieter than exit-1-every-day, not weaker.

    - COULD NOT CHECK alarms every day. It is the starvation case the watchdog
      exists for, and a silent starving watchdog is the original failure.
    - Real staleness alarms once, at the start of the episode, then comments.
      "Once" is per target (2026-11-15): ``known`` is the repos the open issue
      already names. A target that goes stale while an older episode is open
      (TheFiscalFinder's has been open since October) emails on the day it
      joins; before this, one open episode made every later stall silent.
    - Everything green closes the episode.
    """
    if report.unknown:
        return Decision(
            COMMENT if issue_open else CREATE,
            1,
            "a target could not be checked — alarming every day by design",
        )
    if report.stale:
        if issue_open:
            joined = sorted({f.repo for f in report.stale} - set(known))
            if joined:
                return Decision(
                    COMMENT, 1, f"new staleness joined the open episode: {', '.join(joined)}"
                )
            return Decision(COMMENT, 0, "staleness already reported in the open episode issue")
        return Decision(CREATE, 1, "new staleness episode")
    if report.waiting:
        if issue_open:
            return Decision(COMMENT, 0, "known failure, waiting for its next scheduled run")
        return Decision(
            NONE, 0, "known failure tracked in its own repo, waiting for its next scheduled run"
        )
    if issue_open:
        return Decision(CLOSE, 0, "every target is back inside its window")
    return Decision(NONE, 0, "all green, nothing open")
