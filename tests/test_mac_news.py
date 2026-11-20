"""The Mac mini's news job (scripts/mac/news.sh and its launchd file, 2026-11).

The job replaces news.yml's six-hourly cron. These pin what it promises: the times and why they work in both
seasons, the module run exactly as the workflow ran it (Python 3.12, standard library, no install, never a
headline), the keys only through with_keys.py, the alarm relayed under its own label, and the two jobs keeping
out of each other's way. The whole job is proved by its dry run and the proofs in docs/MAC-NEWS.md.
"""
from __future__ import annotations

import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mac" / "news.sh"
WEEKLY = ROOT / "scripts" / "mac" / "weekly-refresh.sh"
PLIST = ROOT / "scripts" / "mac" / "com.137finder.moleculefinder.news.plist"
WEEKLY_PLIST = ROOT / "scripts" / "mac" / "com.137finder.moleculefinder.weekly-refresh.plist"
ET, UTC = ZoneInfo("America/New_York"), ZoneInfo("UTC")


def _code(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


CODE = _code(SCRIPT.read_text())


# ── when it runs ──────────────────────────────────────────────────────────────────────────────
def _slots() -> list[tuple[int, int]]:
    p = plistlib.loads(PLIST.read_bytes())
    return [(s["Hour"], s["Minute"]) for s in p["StartCalendarInterval"]]


def test_the_plist_starts_four_times_a_day_at_50_past_1_7_13_19_eastern():
    p = plistlib.loads(PLIST.read_bytes())
    assert p["Label"] == "com.137finder.moleculefinder.news"
    assert _slots() == [(1, 50), (7, 50), (13, 50), (19, 50)]
    assert not any("Weekday" in s for s in p["StartCalendarInterval"])     # every day


def _bands(day: datetime) -> list[int]:
    return [datetime(day.year, day.month, day.day, h, m, tzinfo=ET).astimezone(UTC).hour // 6 for h, m in _slots()]


@pytest.mark.parametrize("day", [datetime(2026, 1, 14), datetime(2026, 7, 14),       # winter, summer
                                 datetime(2026, 3, 9), datetime(2026, 11, 2)])         # the days after the changes
def test_each_start_falls_in_its_own_six_hour_utc_band_so_the_four_rotations_all_run(day):
    """news.py rotates its batch list by now.hour // 6 (UTC). EST puts the starts at 06:50, 12:50, 18:50, 00:50
    UTC (news.yml's own minutes), EDT an hour earlier: either way four different bands."""
    assert sorted(_bands(day)) == [0, 1, 2, 3]


@pytest.mark.parametrize("day, twice, missed", [(datetime(2026, 3, 8), 1, 0), (datetime(2026, 11, 1), 0, 1)])
def test_on_a_clock_change_day_one_band_is_asked_twice_and_one_waits_a_day(day, twice, missed):
    """Harmless: every search looks seven days back, and the next day asks all four again (docs/MAC-NEWS.md)."""
    bands = _bands(day)
    assert bands.count(twice) == 2 and missed not in bands


def test_no_start_is_in_the_hour_the_clocks_skip():
    assert all(h != 2 for h, _ in _slots())                     # 02:00 to 02:59 does not exist on the spring day


def test_no_news_start_meets_a_weekly_start_and_a_news_run_ends_before_the_next_weekly_start():
    weekly = {(s["Hour"], s["Minute"]) for s in plistlib.loads(WEEKLY_PLIST.read_bytes())["StartCalendarInterval"]}
    assert not weekly & set(_slots())
    limit = int(re.search(r'LIMIT_SECONDS="\$\{MF_NEWS_LIMIT_SECONDS:-(\d+)\}"', CODE).group(1))
    assert limit == 600                                          # news.yml: timeout-minutes: 10
    assert all(m == 10 for _, m in weekly) and all(m == 50 for _, m in _slots())
    assert 50 + limit // 60 <= 60                                 # a news run is over by :00; the weekly starts at :10


def test_the_plist_runs_origin_mains_script_from_the_jobs_own_clone_and_never_prompts():
    p = plistlib.loads(PLIST.read_bytes())
    cmd = p["ProgramArguments"][2]
    assert 'C="$D/news-checkout"' in cmd and "show origin/main:scripts/mac/news.sh" in cmd
    assert "-c credential.helper=" in cmd and "gh auth" not in cmd     # a public clone: no credentials at all
    assert "GIT_TERMINAL_PROMPT=0" in cmd and "alarm 60" in cmd
    assert "fetch" not in cmd.split('elif [ ! -f "$D/news.sh" ]')[1]   # the interactive repo is only read


# ── it runs the module exactly as news.yml did ────────────────────────────────────────────────
def test_the_module_runs_on_python_312_standard_library_only_with_no_install():
    assert 'PY_BASE="/opt/homebrew/opt/python@3.12/bin/python3.12"' in CODE
    assert '"Python 3.12."*' in CODE
    assert 'NEWS=(env TZ=UTC "$PY_BASE" -E -s -B -m moleculefinder_etl.news)' in CODE
    assert "pip install" not in CODE and "uv sync" not in CODE
    assert "--show-headlines" not in CODE                          # never a headline in a log or an alarm


def test_the_job_never_writes_to_git():
    for word in ("git push", "git commit", "git add"):
        assert word not in CODE, word


def test_it_clears_every_variable_a_shell_could_leak_in():
    assert re.search(r'case "\$v" in MFETL_\*\|SUPABASE_\*\|GITHUB_\*\) unset', CODE)


def test_the_keys_reach_it_only_through_with_keys_and_a_dry_run_blanks_them():
    assert not re.search(r"(^|[;&|]\s*)(source|\.)\s+\S*(ENV_FILE|\.env)", CODE, re.MULTILINE)
    uses = [line for line in CODE.splitlines() if "$ENV_FILE" in line and not line.startswith("ENV_FILE=")]
    assert uses and all("with_keys.py" in line for line in uses)
    dry = CODE.split('if [ "$DRY" = 1 ]; then\n  say "dry run: the database keys are BLANKED"', 1)[1].split("elif", 1)[0]
    assert "SUPABASE_URL= SUPABASE_SERVICE_KEY=" in dry and "--dry-run" in dry


def test_a_proof_run_never_takes_the_real_keys():
    proof = CODE.split('elif [ "$PROOF" = 1 ]; then', 1)[1].split("\nelse\n", 1)[0]
    assert "$ENV_FILE" not in proof and '"$TEST_ENV"' in proof
    assert "--env-file must be a test file, never the real keys" in CODE


def test_every_git_call_is_prompt_free_and_uses_no_keychain():
    assert 'GIT_CONFIG_KEY_0="credential.helper" GIT_CONFIG_VALUE_0=""' in CODE
    assert "GIT_TERMINAL_PROMPT=0" in CODE and "GH_PROMPT_DISABLED=1" in CODE
    assert 'ETL_URL="https://github.com/$ETL_GH.git"' in CODE


# ── the alarm ─────────────────────────────────────────────────────────────────────────────────
def test_the_alarm_is_news_ymls_issue_relayed_through_github_under_its_own_label():
    alarm = CODE.split("alarm() {", 1)[1].split("\nstop_watchdog() {", 1)[0]
    assert 'title="Molecules-in-the-news run FAILED"' in alarm
    assert alarm.index("tgh workflow run mac-alarm.yml") < alarm.index("tgh issue create")   # relay first
    assert 'label: "news-failure"' in alarm and "--label news-failure" in alarm
    assert "redacted" in alarm and "tilde" in alarm
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "mac-alarm.yml").read_text())
    on = wf.get("on", wf.get(True))
    assert set(on) == {"workflow_dispatch"}
    assert on["workflow_dispatch"]["inputs"]["label"]["default"] == "refresh-failure"   # the weekly job sends none
    run = wf["jobs"]["alarm"]["steps"][0]["run"]
    assert "${{" not in run and run.rstrip().endswith("exit 1")
    assert "news-failure)" in run and "refresh-failure)" in run and "unknown label" in run


def test_a_cancelled_run_raises_no_alarm_and_a_timeout_does():
    fin = CODE.split("finish() {", 1)[1].split("\non_signal() {", 1)[0]
    assert fin.index('elif [ "$CAUSE" = "cancelled" ]') < fin.index('alarm "$what"')
    assert "TIMED OUT" in fin


# ── the two jobs keep out of each other's way ─────────────────────────────────────────────────
def test_the_weekly_refresh_never_mistakes_a_news_run_for_another_build():
    pattern = re.search(r"pgrep -f '([^']+)'", WEEKLY.read_text()).group(1)
    cmdline = "/opt/homebrew/opt/python@3.12/bin/python3.12 -E -s -B -m moleculefinder_etl.news"
    assert not re.search(pattern.replace("\\.", r"\."), cmdline)
    assert 'WEEKLY_LOCK="$STATE_DIR/running.lock"' in CODE and 'LOCK="$STATE_DIR/news.lock"' in CODE
    assert re.search(r'^LOCK="\$STATE_DIR/running\.lock"', WEEKLY.read_text(), re.MULTILINE)


needs_mac = pytest.mark.skipif(not (shutil.which("bash") and sys.platform == "darwin"),
                               reason="the script runs on the Mac mini")


def _start(tmp_path: Path, *args: str, **env: str) -> tuple[subprocess.CompletedProcess, str]:
    state, logs = tmp_path / "state", tmp_path / "logs"
    state.mkdir(exist_ok=True)
    e = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path), "MF_NEWS_STATE_DIR": str(state),
         "MF_NEWS_LOG_DIR": str(logs), "MF_NEWS_GH": "/usr/bin/false", **env}
    out = subprocess.run(["/bin/bash", str(SCRIPT), *args], capture_output=True, text=True, timeout=60, env=e, check=False)
    text = "".join(p.read_text() for p in sorted(logs.glob("*.log"))) if logs.exists() else ""
    return out, text


@needs_mac
def test_a_news_start_during_the_weekly_refresh_steps_aside_with_no_alarm(tmp_path):
    lock = tmp_path / "state" / "running.lock"
    lock.mkdir(parents=True)
    (lock / "pid").write_text(str(os.getpid()))                  # a live process holds the weekly lock
    out, log = _start(tmp_path, "--dry-run")
    assert out.returncode == 0
    assert f"stepping aside: the weekly refresh is running (pid {os.getpid()})" in log
    assert "ALARM" not in log and "DONE: stepped aside" in log
    assert not (tmp_path / "state" / "news.lock").exists()       # it tidied its own lock
    assert lock.exists()                                          # and never touched the weekly one


@needs_mac
def test_a_second_news_start_exits_at_once(tmp_path):
    lock = tmp_path / "state" / "news.lock"
    lock.mkdir(parents=True)
    (lock / "pid").write_text(str(os.getpid()))
    t = time.monotonic()
    out, log = _start(tmp_path, "--dry-run")
    assert out.returncode == 0 and time.monotonic() - t < 5
    assert "another news run is going" in log
    assert lock.exists()


@needs_mac
def test_a_start_inside_two_hours_of_a_good_run_steps_aside(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "news-last-ok").write_text(str(int(time.time()) - 600))
    out, log = _start(tmp_path)
    assert out.returncode == 0 and "inside the two-hour spacing" in log and "ALARM" not in log


@needs_mac
def test_a_stale_lock_from_a_dead_run_is_taken_over(tmp_path):
    lock = tmp_path / "state" / "news.lock"
    lock.mkdir(parents=True)
    (lock / "pid").write_text("999999")
    wlock = tmp_path / "state" / "running.lock"                   # step aside right after, so nothing else runs
    wlock.mkdir()
    (wlock / "pid").write_text(str(os.getpid()))
    out, log = _start(tmp_path, "--dry-run")
    assert out.returncode == 0 and "stepping aside: the weekly refresh" in log


def test_the_weekly_job_is_unchanged_by_the_news_job():
    assert "news" not in _code(WEEKLY.read_text()).replace("newsletter", "")
