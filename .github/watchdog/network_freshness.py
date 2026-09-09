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


TARGETS = [
    Target("judicialfinder", "refresh-data.yml", 10, "weekly"),
    Target("thefiscalfinder", "refresh-data.yml", 40, "monthly"),
    Target("gravityfinder", "freshness.yml", 10, "weekly"),
    Target("moleculefinder-etl", "etl.yml", 10, "weekly"),
]

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


def _classify(api, t: Target, now: _dt.datetime, report: Report) -> Finding:
    runs_url = (
        f"https://api.github.com/repos/{OWNER}/{t.repo}"
        f"/actions/workflows/{t.workflow}/runs?status=success&per_page=1"
    )
    try:
        runs = api(runs_url).get("workflow_runs", [])
    except Exception as e:  # noqa: BLE001 - fail loud; see workflow header
        return Finding(
            t.repo,
            UNKNOWN,
            f"- **{t.repo}** — COULD NOT CHECK ({type(e).__name__}: {e}). "
            f"Treat as broken until proven otherwise.",
        )

    if not runs:
        return Finding(
            t.repo, UNKNOWN, f"- **{t.repo}** — no successful `{t.workflow}` run on record at all."
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


def build_report(api, now: _dt.datetime) -> Report:
    report = Report()
    for t in TARGETS:
        report.findings.append(_classify(api, t, now, report))
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


def decide(report: Report, issue_open: bool) -> Decision:
    """Choose what to do. Quieter than exit-1-every-day, not weaker.

    - COULD NOT CHECK alarms every day. It is the starvation case the watchdog
      exists for, and a silent starving watchdog is the original failure.
    - Real staleness alarms once, at the start of the episode, then comments.
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
