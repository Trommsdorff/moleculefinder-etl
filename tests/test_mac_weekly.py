"""The Mac mini's weekly refresh (scripts/mac/weekly-refresh.sh and its launchd file, 2026-11).

The job replaces etl.yml's Monday cron. These pin what it promises: it never sets a guard's release valve,
never sources the .env, runs at the time the plist says and only while the ISO week has not succeeded,
writes the commit subjects the network watchdog counts, and hands the build only the two database keys,
without ever printing them. The whole job is proved by its dry run (docs/MAC-WEEKLY-REFRESH.md).
"""
from __future__ import annotations

import importlib.util
import os
import plistlib
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mac" / "weekly-refresh.sh"
PLIST = ROOT / "scripts" / "mac" / "com.137finder.moleculefinder.weekly-refresh.plist"
WITH_KEYS = ROOT / "scripts" / "mac" / "with_keys.py"
ET = ZoneInfo("America/New_York")

_spec = importlib.util.spec_from_file_location("network_freshness", ROOT / ".github" / "watchdog" / "network_freshness.py")
nf = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("network_freshness", nf)
_spec.loader.exec_module(nf)


def _code(text: str) -> str:
    """The script without its comments, so a rule stated in a comment is not mistaken for code."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


# ── the guards' release valves are never set, the .env is never sourced ──────────────────────
def test_the_job_never_sets_a_guards_release_valve():
    code = _code(SCRIPT.read_text())
    for valve in ("MFETL_DRAWING_SEEDS_CHANGED", "MFETL_ALLOW_REGRESSION", "MFETL_ALLOW_STALE_WIKIDATA"):
        assert valve not in code, valve
    # and it clears every MFETL_ / SUPABASE_ / GITHUB_ variable a session's shell could leak in
    assert re.search(r"case \"\$v\" in MFETL_\*\|SUPABASE_\*\|GITHUB_\*\) unset", code)


def test_the_job_never_sources_the_env_file_and_reads_the_keys_only_through_with_keys():
    code = _code(SCRIPT.read_text())
    assert not re.search(r"(^|[;&|]\s*)(source|\.)\s+\S*(ENV_FILE|\.env)", code, re.MULTILINE)
    uses = [line for line in code.splitlines() if "$ENV_FILE" in line]
    assert uses and all("with_keys.py" in line for line in uses)


def test_a_dry_run_blanks_the_keys_and_a_real_run_never_does():
    code = _code(SCRIPT.read_text())
    dry, real = code.split('if [ "$DRY" = 1 ]; then\n  say "dry run: the database keys are BLANKED', 1)[1].split("else", 1)
    assert "SUPABASE_URL= SUPABASE_SERVICE_KEY=" in dry
    assert "with_keys.py" in real.split("fi", 1)[0]


def test_the_build_is_the_weekly_runs_build():
    code = _code(SCRIPT.read_text())
    assert "moleculefinder_etl.cli all --target 10000" in code
    assert "MFETL_INPUTS=refresh MFETL_WEEKLY=1" in code
    assert "uv sync --quiet --frozen --no-dev" in code          # uv.lock, exactly
    assert '"Python 3.12."*' in code


def test_the_merge_takes_only_the_verified_commit():
    code = _code(SCRIPT.read_text())
    merge = next(line for line in code.splitlines() if "pr merge" in line)
    assert "--squash" in merge and '--match-head-commit "$SHA"' in merge
    assert 'select(.name == "verify")' in code and 'select(.workflowName == "ci")' in code


# ── the commit subjects the watchdog counts ───────────────────────────────────────────────────
def test_the_jobs_commit_subjects_are_the_ones_the_watchdog_counts():
    code = _code(SCRIPT.read_text())
    pattern = re.compile(nf.MF_COMMIT_SUBJECT)
    assert 'MSG="etl: refresh $TODAY"' in code and 'MSG="etl: no changes $TODAY [heartbeat]"' in code
    assert pattern.search("etl: refresh 2026-11-23") and pattern.search("etl: no changes 2026-11-23 [heartbeat]")
    assert "etl: run failed $(date -u +%F) [heartbeat]" in code
    assert not pattern.search("etl: run failed 2026-11-23 [heartbeat]")
    # every commit the job pushes to the ETL's main touches data/LAST_CHECK, the path the watchdog asks about
    target = next(t for t in nf.TARGETS if t.repo == "moleculefinder-etl")
    assert target.commit_path == "data/LAST_CHECK" and "date -u +%FT%TZ > data/LAST_CHECK" in code


# ── when it runs ──────────────────────────────────────────────────────────────────────────────
def _plist() -> dict:
    return plistlib.loads(PLIST.read_bytes())


def test_the_plist_starts_monday_0310_eastern_retries_monday_and_catches_up_daily():
    slots = [(s["Weekday"], s["Hour"], s["Minute"]) for s in _plist()["StartCalendarInterval"]]
    assert slots[0] == (1, 3, 10)
    monday = sorted(h for d, h, m in slots if d == 1)
    assert monday == [3, 6, 8, 10, 12, 14, 16, 18]
    assert sorted(d for d, h, m in slots if d != 1) == [0, 2, 3, 4, 5, 6]
    assert all((h, m) == (3, 10) for d, h, m in slots if d != 1)
    assert all(m == 10 for d, h, m in slots)
    assert len(slots) == 14


def test_the_plist_runs_origin_mains_script_and_never_prompts():
    p = _plist()
    assert p["Label"] == "com.137finder.moleculefinder.weekly-refresh"
    cmd = p["ProgramArguments"][2]
    assert "show origin/main:scripts/mac/weekly-refresh.sh" in cmd
    assert "credential.helper=!/opt/homebrew/bin/gh auth git-credential" in cmd and "-c credential.helper=" in cmd
    assert "GIT_TERMINAL_PROMPT=0" in cmd and "alarm 120" in cmd
    assert p["ExitTimeOut"] == 90


def test_every_git_call_in_the_script_uses_gh_credentials():
    code = _code(SCRIPT.read_text())
    assert 'GIT_CONFIG_VALUE_1="!/opt/homebrew/bin/gh auth git-credential"' in code
    assert 'GIT_CONFIG_KEY_0="credential.helper" GIT_CONFIG_VALUE_0=""' in code
    assert "GIT_TERMINAL_PROMPT=0" in code and "GH_PROMPT_DISABLED=1" in code


needs_bash = pytest.mark.skipif(not (shutil.which("bash") and sys.platform == "darwin"),
                                reason="the script runs on the Mac mini (BSD date)")


def _check(when: datetime, state: Path) -> str:
    epoch = str(int(when.timestamp()))
    out = subprocess.run(["/bin/bash", str(SCRIPT), "--schedule-check", epoch, str(state)],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


@needs_bash
@pytest.mark.parametrize("when, week", [
    (datetime(2026, 11, 16, 3, 10, tzinfo=ET), "2026-W47"),      # winter: 08:10 UTC Monday
    (datetime(2026, 7, 6, 3, 10, tzinfo=ET), "2026-W28"),        # summer: 07:10 UTC Monday
    (datetime(2026, 11, 22, 3, 10, tzinfo=ET), "2026-W47"),      # Sunday's catch-up: still the same week
])
def test_the_first_start_of_a_week_runs_in_that_weeks_iso_week(tmp_path, when, week):
    out = _check(when, tmp_path)
    assert f"week={week}" in out and "run=yes" in out


@needs_bash
def test_a_week_that_succeeded_or_ran_out_of_tries_does_not_run_again(tmp_path):
    when = datetime(2026, 11, 16, 6, 10, tzinfo=ET)
    (tmp_path / "week-2026-W47").write_text("attempt 2026-11-16T08:10:01Z x\nsuccess 2026-11-16T08:31:00Z done\n")
    assert "run=no reason=this week already succeeded" in _check(when, tmp_path)
    (tmp_path / "week-2026-W47").write_text("attempt x\n" * 8)
    assert "run=no reason=8 tries this week" in _check(when, tmp_path)
    (tmp_path / "week-2026-W47").write_text("attempt x\n" * 7)
    assert "run=yes" in _check(when, tmp_path)


# ── the keys ──────────────────────────────────────────────────────────────────────────────────
SECRET = "eyJhbGciOiJIUzI1NiJ9.this-is-a-test-value-never-a-real-key"


def _env_file(tmp_path: Path) -> Path:
    env = tmp_path / ".env"
    env.write_text(f"SUPABASE_URL=https://example.invalid\nSUPABASE_SERVICE_KEY={SECRET}\n"
                   "SUPABASE_DB_URL=postgresql://u:p@ss w0rd@host/db\nMFETL_CANON_TARGET=200\n")
    return env


def test_with_keys_check_never_prints_a_value(tmp_path):
    out = subprocess.run([sys.executable, str(WITH_KEYS), str(_env_file(tmp_path)), "--check"],
                         capture_output=True, text=True)
    assert out.returncode == 0 and SECRET not in out.stdout + out.stderr and "values not shown" in out.stdout


def test_with_keys_passes_only_the_two_keys(tmp_path):
    probe = ("import os; print(sorted(k for k in os.environ if k.startswith(('SUPABASE', 'MFETL_CANON')))); "
             "print(os.environ['SUPABASE_SERVICE_KEY'] == %r)" % SECRET)
    out = subprocess.run([sys.executable, str(WITH_KEYS), str(_env_file(tmp_path)), "--", sys.executable, "-c", probe],
                         capture_output=True, text=True,
                         env={k: v for k, v in os.environ.items() if not k.startswith("SUPABASE")} | {"SUPABASE_DB_URL": "x"})
    assert out.returncode == 0, out.stderr
    assert out.stdout.splitlines() == ["['SUPABASE_SERVICE_KEY', 'SUPABASE_URL']", "True"]


def test_with_keys_refuses_a_file_missing_a_key(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SUPABASE_URL=https://example.invalid\n")
    out = subprocess.run([sys.executable, str(WITH_KEYS), str(env), "--check"], capture_output=True, text=True)
    assert out.returncode == 3 and "SUPABASE_SERVICE_KEY" in out.stderr
