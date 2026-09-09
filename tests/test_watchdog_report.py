"""Offline tests for the network freshness watchdog's report logic.

The watchdog runs in a workflow, against four repos, once a day. That makes its
decision table almost impossible to exercise in place: to see the "recovered"
branch you would have to break a sibling site and then fix it. So the logic is
a pure function over an injected API, and this file drives it through the four
states with a stub. No network.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest

# The module lives under .github/, which is not on the import path and is not
# part of the shipped ETL package. Load it by path. It must be registered in
# sys.modules before exec_module or @dataclass cannot resolve its own module.
_MOD = Path(__file__).resolve().parents[1] / ".github" / "watchdog" / "network_freshness.py"
_spec = importlib.util.spec_from_file_location("network_freshness", _MOD)
assert _spec and _spec.loader
nf = importlib.util.module_from_spec(_spec)
sys.modules["network_freshness"] = nf
_spec.loader.exec_module(nf)

NOW = dt.datetime(2026, 9, 9, 17, 0, tzinfo=dt.timezone.utc)

ALL_REPOS = ["judicialfinder", "thefiscalfinder", "gravityfinder", "moleculefinder-etl"]


def _run(repo: str, when: str, conclusion: str = "success") -> dict:
    return {
        "updated_at": when,
        "created_at": when,
        "conclusion": conclusion,
        "html_url": f"https://github.com/Trommsdorff/{repo}/actions/runs/1",
    }


class StubApi:
    """Answers the three URL shapes the watchdog asks for, and nothing else."""

    def __init__(self, *, green=None, scheduled=None, issues=None, broken=()):
        self.green = green or {}  # repo -> ISO timestamp of last success, or None
        self.scheduled = scheduled or {}  # repo -> list of run dicts
        self.issues = issues or {}  # repo -> list of issue dicts
        self.broken = set(broken)  # repos whose runs API raises
        self.calls: list[str] = []

    def __call__(self, url: str):
        self.calls.append(url)
        repo = url.split("/repos/Trommsdorff/")[1].split("/")[0]
        if repo in self.broken:
            raise TimeoutError("The read operation timed out")
        if "/issues?" in url:
            return self.issues.get(repo, [])
        if "event=schedule" in url:
            return {"workflow_runs": self.scheduled.get(repo, [])}
        when = self.green.get(repo)
        return {"workflow_runs": [_run(repo, when)] if when else []}


def _all_green(**overrides):
    green = {r: "2026-09-07T13:00:00Z" for r in ALL_REPOS}
    green.update(overrides)
    return green


# ── Case 1: everything green ─────────────────────────────────────────────────


def test_all_green_is_silent_and_opens_nothing():
    report = nf.build_report(StubApi(green=_all_green()), NOW)

    assert [f.state for f in report.findings] == [nf.OK] * 4
    assert report.all_clear

    d = nf.decide(report, issue_open=False)
    assert (d.action, d.exit_code) == (nf.NONE, 0)


# ── Case 2: one stale ────────────────────────────────────────────────────────


def test_one_stale_alarms_once_then_goes_quiet():
    api = StubApi(green=_all_green(judicialfinder="2026-08-10T13:00:00Z"))
    report = nf.build_report(api, NOW)

    assert [f.repo for f in report.stale] == ["judicialfinder"]
    assert len(report.ok) == 3
    assert "30 days ago" in report.stale[0].line
    assert "the limit for this cron is 10 days" in report.stale[0].line

    # Day one of the episode: fail the job, which is what sends the email.
    first = nf.decide(report, issue_open=False)
    assert (first.action, first.exit_code) == (nf.CREATE, 1)

    # Every day after: same finding, same issue, no email.
    later = nf.decide(report, issue_open=True)
    assert (later.action, later.exit_code) == (nf.COMMENT, 0)

    assert "judicialfinder" in report.detail()
    assert "Healthy: thefiscalfinder" in report.detail()
    assert "gravityfinder — last green 2d ago" in report.detail()


# ── Case 3: could not check ──────────────────────────────────────────────────


def test_could_not_check_alarms_every_single_day():
    api = StubApi(green=_all_green(), broken=["gravityfinder"])
    report = nf.build_report(api, NOW)

    assert [f.repo for f in report.unknown] == ["gravityfinder"]
    assert "COULD NOT CHECK" in report.unknown[0].line
    assert "TimeoutError" in report.unknown[0].line

    # This is the starvation case. It is loud on day one and every day after:
    # an open issue must NOT buy silence here.
    for issue_open in (False, True):
        d = nf.decide(report, issue_open=issue_open)
        assert d.exit_code == 1, f"could-not-check must alarm (issue_open={issue_open})"
    assert nf.decide(report, issue_open=False).action == nf.CREATE
    assert nf.decide(report, issue_open=True).action == nf.COMMENT


def test_no_successful_run_on_record_is_also_unknown():
    report = nf.build_report(StubApi(green=_all_green(gravityfinder=None)), NOW)
    assert [f.repo for f in report.unknown] == ["gravityfinder"]
    assert nf.decide(report, issue_open=True).exit_code == 1


def test_unknown_outranks_stale():
    api = StubApi(
        green=_all_green(judicialfinder="2026-08-10T13:00:00Z"), broken=["moleculefinder-etl"]
    )
    report = nf.build_report(api, NOW)
    assert report.stale and report.unknown
    assert nf.decide(report, issue_open=True).exit_code == 1


# ── Case 4: recovered ────────────────────────────────────────────────────────


def test_recovery_closes_the_open_issue_without_emailing():
    report = nf.build_report(StubApi(green=_all_green()), NOW)

    d = nf.decide(report, issue_open=True)
    assert (d.action, d.exit_code) == (nf.CLOSE, 0)
    assert "every target is back inside its window" in d.why


def test_recovery_needs_every_target_green_not_just_most():
    api = StubApi(green=_all_green(thefiscalfinder="2026-07-05T15:00:00Z"))
    report = nf.build_report(api, NOW)
    assert nf.decide(report, issue_open=True).action == nf.COMMENT


# ── The monthly-cron carve-out ───────────────────────────────────────────────

TFF_FAILED_SEP = {
    "created_at": "2026-09-01T13:32:58Z",
    "updated_at": "2026-09-01T16:50:00Z",
    "conclusion": "failure",
    "html_url": "https://github.com/Trommsdorff/thefiscalfinder/actions/runs/33514048879",
}
TFF_FAILED_OCT = dict(TFF_FAILED_SEP, created_at="2026-10-01T08:20:00Z")
OPEN_FAILURE_ISSUE = [
    {
        "title": "Monthly data freshness FAILED",
        "html_url": "https://github.com/Trommsdorff/thefiscalfinder/issues/57",
    }
]


def _tff(scheduled, issues, now=NOW):
    """TheFiscalFinder stale; the other three green as of two days before `now`.

    Pinning the healthy three to `now` matters: these cases move the clock into
    October, and a fixed date would quietly make every target stale and pass the
    assertions for the wrong reason.
    """
    fresh = f"{now - dt.timedelta(days=2):%Y-%m-%dT%H:%M:%SZ}"
    green = {r: fresh for r in ALL_REPOS}
    green["thefiscalfinder"] = "2026-07-05T15:08:13Z"
    api = StubApi(
        green=green,
        scheduled={"thefiscalfinder": scheduled},
        issues={"thefiscalfinder": issues},
    )
    return api, nf.build_report(api, now)


def test_monthly_failure_already_tracked_is_known_and_waiting():
    _, report = _tff([TFF_FAILED_SEP], OPEN_FAILURE_ISSUE)

    assert [f.repo for f in report.waiting] == ["thefiscalfinder"]
    assert not report.stale
    line = report.waiting[0].line
    assert "KNOWN and WAITING" in line
    assert "next scheduled run is 2026-10-01" in line
    assert "issues/57" in line

    # Known and waiting does not start an episode of its own.
    assert nf.decide(report, issue_open=False) == nf.Decision(
        nf.NONE, 0, "known failure tracked in its own repo, waiting for its next scheduled run"
    )
    assert nf.decide(report, issue_open=True).exit_code == 0


def test_monthly_failure_with_no_open_issue_is_plain_staleness():
    # This is TheFiscalFinder as it actually stands on 2026-09-09: issue #57 was
    # closed on 2026-09-06 while the refresh is still red, so nothing upstream
    # is carrying the failure and the watchdog will not soften it.
    _, report = _tff([TFF_FAILED_SEP], [])
    assert [f.repo for f in report.stale] == ["thefiscalfinder"]
    assert not report.waiting


def test_the_next_scheduled_run_failing_too_alarms_again():
    _, report = _tff(
        [TFF_FAILED_OCT, TFF_FAILED_SEP],
        OPEN_FAILURE_ISSUE,
        now=dt.datetime(2026, 10, 2, 12, 0, tzinfo=dt.timezone.utc),
    )
    assert [f.repo for f in report.stale] == ["thefiscalfinder"]
    assert nf.decide(report, issue_open=False).exit_code == 1


def test_a_monthly_cron_that_never_fired_again_alarms_when_due():
    # No second run at all after the grace window is the starvation shape:
    # waiting has to end somewhere, or the carve-out becomes permanent silence.
    _, report = _tff(
        [TFF_FAILED_SEP],
        OPEN_FAILURE_ISSUE,
        now=dt.datetime(2026, 10, 4, 12, 0, tzinfo=dt.timezone.utc),
    )
    assert [f.repo for f in report.stale] == ["thefiscalfinder"]


def test_waiting_still_holds_the_day_before_the_next_run_is_due():
    _, report = _tff(
        [TFF_FAILED_SEP],
        OPEN_FAILURE_ISSUE,
        now=dt.datetime(2026, 10, 2, 12, 0, tzinfo=dt.timezone.utc),
    )
    assert [f.repo for f in report.waiting] == ["thefiscalfinder"]


def test_unreadable_issues_fall_back_to_staleness_and_say_why():
    api = StubApi(
        green=_all_green(thefiscalfinder="2026-07-05T15:08:13Z"),
        scheduled={"thefiscalfinder": [TFF_FAILED_SEP]},
    )
    real = api.__call__

    def raising(url):
        if "/issues?" in url:
            raise PermissionError("403 Forbidden")
        return real(url)

    report = nf.build_report(raising, NOW)
    assert [f.repo for f in report.stale] == ["thefiscalfinder"]
    assert any("Issues: Read" in n for n in report.notes)
    assert "Issues: Read" in report.detail()


# ── Only the four intended repos, and only the API the token is scoped for ───


def test_targets_are_the_four_refresh_crons():
    assert [t.repo for t in nf.TARGETS] == ALL_REPOS
    # PolitiFinder is absent deliberately: no refresh cron until ~late 2027.
    assert not any(t.repo == "politifinder" for t in nf.TARGETS)


def test_it_only_ever_reads_actions_and_issues():
    api = StubApi(green=_all_green(thefiscalfinder="2026-07-05T15:08:13Z"),
                  scheduled={"thefiscalfinder": [TFF_FAILED_SEP]},
                  issues={"thefiscalfinder": OPEN_FAILURE_ISSUE})
    nf.build_report(api, NOW)
    for url in api.calls:
        assert "/actions/workflows/" in url or "/issues?" in url, url


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
