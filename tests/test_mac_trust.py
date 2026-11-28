"""The Mac mini's trust-review jobs (scripts/mac/trust-review.sh and its launchd files; drawing truth 2026-11-27,
one fact on every surface 2026-11-27, which made the drawing job's script the shared one).

They must never get in another job's way: each its own lock only, the review run as a module that the weekly refresh's
"another build?" check cannot mistake for a build, a wait (never a step on) while the weekly refresh or the news job
runs, and "did not run" recorded when the wait runs out. They write nothing but the report folder, and hold no key.
"""
from __future__ import annotations

import json
import os
import plistlib
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mac" / "trust-review.sh"
WEEKLY = ROOT / "scripts" / "mac" / "weekly-refresh.sh"
JOBS = {"drawings": {"Hour": 6, "Minute": 30}, "facts": {"Hour": 6, "Minute": 45}, "findings": {"Hour": 6, "Minute": 55}}


def _code(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


CODE = _code(SCRIPT.read_text())


@pytest.mark.parametrize("review", sorted(JOBS))
def test_each_job_starts_daily_from_main_and_runs_the_shared_script(review):
    p = plistlib.loads((ROOT / "scripts" / "mac" / f"com.137finder.moleculefinder.trust-{review}.plist").read_bytes())
    assert p["Label"] == f"com.137finder.moleculefinder.trust-{review}"
    assert p["StartCalendarInterval"] == JOBS[review]
    cmd = p["ProgramArguments"][-1]
    assert "origin/main:$S" in cmd and 'show main:$S' in cmd and "S=scripts/mac/trust-review.sh" in cmd
    assert f'F="$D/trust-review-{review}.sh"' in cmd                   # each job its own copy of the script
    assert cmd.rstrip().endswith(f'exec /bin/bash "$F" {review}')
    assert p["StandardOutPath"].endswith(f"launchd-trust-{review}.log")


def test_the_facts_job_is_clear_of_the_news_slot_and_after_the_drawing_job():
    assert (JOBS["facts"]["Hour"], JOBS["facts"]["Minute"]) > (JOBS["drawings"]["Hour"], JOBS["drawings"]["Minute"])
    assert JOBS["facts"]["Hour"] * 60 + JOBS["facts"]["Minute"] <= 7 * 60 + 50 - 60   # an hour before 07:50


def test_the_findings_job_takes_origin_mains_script_only_once_it_names_the_review():
    cmd = plistlib.loads((ROOT / "scripts" / "mac" / "com.137finder.moleculefinder.trust-findings.plist").read_bytes())["ProgramArguments"][-1]
    assert 'grep -q "^ *findings)"' in cmd                         # origin/main's copy predates the review until the push


def test_the_findings_job_follows_the_facts_job_and_is_clear_of_the_news_slot():
    at = lambda r: JOBS[r]["Hour"] * 60 + JOBS[r]["Minute"]
    assert at("findings") > at("facts") + 5                       # the facts review's Tuesday full read: about 5.3 min
    assert at("findings") <= 7 * 60 + 50 - 30                     # half an hour before 07:50 (it takes about half a minute)


def test_the_review_runs_as_a_module_the_weekly_build_check_never_matches():
    m = re.search(r"pgrep -f '([^']+)'", WEEKLY.read_text())
    assert m, "the weekly refresh's check for another build moved"
    run = next(line for line in CODE.splitlines() if "/bin/python\" -m " in line)
    assert '-m "moleculefinder_etl.review.$REVIEW"' in run
    for review in JOBS:
        assert not re.search(m.group(1), run.replace("$REVIEW", review))
    assert "mfetl" not in CODE and "moleculefinder_etl.cli" not in CODE


def test_it_names_only_the_known_reviews():
    for review in JOBS:
        assert re.search(rf"^\s*{review}\)", CODE, re.MULTILINE), review
    r = subprocess.run(["/bin/bash", str(SCRIPT), "everything"], capture_output=True, text=True, timeout=30,
                       check=False)
    assert r.returncode == 2 and "usage" in r.stderr


def test_it_takes_only_its_own_lock_and_waits_for_the_others():
    assert 'LOCK="$STATE_DIR/trust-$REVIEW.lock"' in CODE
    assert re.search(r'mkdir "\$LOCK"', CODE)
    for other in ("WEEKLY_LOCK", "NEWS_LOCK"):
        assert f'cat "${other}/pid"' in CODE
        assert not re.search(rf'(mkdir|rm -rf|>) *"?\${other}', CODE), f"it must never take or clear {other}"
    assert 'WAIT_SECONDS="${MF_TRUST_WAIT_SECONDS:-3600}"' in CODE


def test_it_reads_only():
    for word in ("git push", "git commit", "gh ", "with_keys.py", "osascript", "curl "):
        assert word not in CODE, word
    assert "SUPABASE_URL= SUPABASE_SERVICE_KEY= SUPABASE_DB_URL=" in CODE


@pytest.mark.parametrize("review", sorted(JOBS))
def test_a_job_that_holds_the_mac_past_the_wait_means_did_not_run(tmp_path, review):
    state, out, logs = tmp_path / "state", tmp_path / "out", tmp_path / "logs"
    (state / "running.lock").mkdir(parents=True)
    (state / "running.lock" / "pid").write_text(str(os.getpid()))       # a live pid: the weekly refresh "runs"
    env = {**os.environ, "MF_TRUST_STATE_DIR": str(state), "MF_TRUST_OUT": str(out), "MF_TRUST_LOG_DIR": str(logs),
           "MF_TRUST_WAIT_SECONDS": "0", "MF_TRUST_POLL_SECONDS": "1"}
    r = subprocess.run(["/bin/bash", str(SCRIPT), review], env=env, capture_output=True, text=True, timeout=60,
                       check=False)
    assert r.returncode == 3
    hb = json.loads((out / f"{review}-last-run.json").read_text())
    assert hb["state"] == "did not run" and hb["exit"] == 3 and "the weekly refresh" in hb["reason"]
    assert (state / "running.lock" / "pid").exists()                     # the other job's lock untouched
    assert not (state / f"trust-{review}.lock").exists()                 # its own released
    assert not (state / "trust-checkout").exists()                       # it fetched nothing
    log = next(logs.glob(f"trust-{review}-*.log")).read_text()
    assert "DID NOT RUN" in log
