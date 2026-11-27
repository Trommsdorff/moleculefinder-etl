"""The Mac mini's drawing-truth job (scripts/mac/trust-drawings.sh and its launchd file, 2026-11-27).

It must never get in another job's way: its own lock only, the review run as a module that the weekly refresh's
"another build?" check cannot mistake for a build, a wait (never a step on) while the weekly refresh or the news job
runs, and "did not run" recorded when the wait runs out. It writes nothing but the report folder, and holds no key.
"""
from __future__ import annotations

import json
import os
import plistlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mac" / "trust-drawings.sh"
PLIST = ROOT / "scripts" / "mac" / "com.137finder.moleculefinder.trust-drawings.plist"
WEEKLY = ROOT / "scripts" / "mac" / "weekly-refresh.sh"


def _code(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


CODE = _code(SCRIPT.read_text())


def test_it_starts_every_day_at_0630_eastern_from_main():
    p = plistlib.loads(PLIST.read_bytes())
    assert p["Label"] == "com.137finder.moleculefinder.trust-drawings"
    assert p["StartCalendarInterval"] == {"Hour": 6, "Minute": 30}
    cmd = p["ProgramArguments"][-1]
    assert "origin/main:$S" in cmd and 'show main:$S' in cmd and "S=scripts/mac/trust-drawings.sh" in cmd
    assert cmd.rstrip().endswith('exec /bin/bash "$D/trust-drawings.sh"')


def test_the_review_runs_as_a_module_the_weekly_build_check_never_matches():
    m = re.search(r"pgrep -f '([^']+)'", WEEKLY.read_text())
    assert m, "the weekly refresh's check for another build moved"
    run = next(line for line in CODE.splitlines() if "-m moleculefinder_etl" in line)
    assert "-m moleculefinder_etl.review.drawings" in run
    assert not re.search(m.group(1), run)
    assert "mfetl" not in CODE and "moleculefinder_etl.cli" not in CODE


def test_it_takes_only_its_own_lock_and_waits_for_the_others():
    assert 'LOCK="$STATE_DIR/trust-drawings.lock"' in CODE
    assert re.search(r'mkdir "\$LOCK"', CODE)
    for other in ("WEEKLY_LOCK", "NEWS_LOCK"):
        assert f'cat "${other}/pid"' in CODE
        assert not re.search(rf'(mkdir|rm -rf|>) *"?\${other}', CODE), f"it must never take or clear {other}"
    assert 'WAIT_SECONDS="${MF_TRUST_WAIT_SECONDS:-3600}"' in CODE


def test_it_reads_only():
    for word in ("git push", "git commit", "gh ", "with_keys.py", "osascript", "curl "):
        assert word not in CODE, word
    assert "SUPABASE_URL= SUPABASE_SERVICE_KEY= SUPABASE_DB_URL=" in CODE


def test_a_job_that_holds_the_mac_past_the_wait_means_did_not_run(tmp_path):
    state, out, logs = tmp_path / "state", tmp_path / "out", tmp_path / "logs"
    (state / "running.lock").mkdir(parents=True)
    (state / "running.lock" / "pid").write_text(str(os.getpid()))       # a live pid: the weekly refresh "runs"
    env = {**os.environ, "MF_TRUST_STATE_DIR": str(state), "MF_TRUST_OUT": str(out), "MF_TRUST_LOG_DIR": str(logs),
           "MF_TRUST_WAIT_SECONDS": "0", "MF_TRUST_POLL_SECONDS": "1"}
    r = subprocess.run(["/bin/bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60, check=False)
    assert r.returncode == 3
    hb = json.loads((out / "drawings-last-run.json").read_text())
    assert hb["state"] == "did not run" and hb["exit"] == 3 and "the weekly refresh" in hb["reason"]
    assert (state / "running.lock" / "pid").exists()                     # the other job's lock untouched
    assert not (state / "trust-drawings.lock").exists()                  # its own released
    assert not (state / "trust-checkout").exists()                       # it fetched nothing
    log = next(logs.glob("trust-drawings-*.log")).read_text()
    assert "DID NOT RUN" in log
