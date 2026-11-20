"""The weekly refresh's dataset step (scripts/mac/weekly-refresh.sh, 2026-11-20): once the site's data is live, the
release dataset_published.yaml names is published to Zenodo when it is newer than Zenodo's latest. It must never
fail, retry or block the refresh, and a failure raises its OWN alarm (label dataset-failure). The step's functions
are run here from the script itself, with `mfetl` and `gh` stubbed and a real git remote."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mac" / "weekly-refresh.sh"
FAKE_TOKEN = "Zq7" + "x" * 57                     # shaped like a Zenodo token: 60 letters and digits


def _code(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _function(text: str, name: str) -> str:
    body = text.split(f"\n{name}() {{", 1)[1].split("\n}\n", 1)[0]
    return f"{name}() {{{body}\n}}\n"


# ── where the step sits: after the week's success, never able to change the run's exit ───────────────────────────
def test_the_step_runs_only_after_the_weeks_success_is_written():
    code = _code(SCRIPT.read_text())
    finish = code.split("finish() {", 1)[1].split("\non_signal() {", 1)[0]
    ok, failed = finish.split("  else\n", 1)
    assert ok.index('echo "success') < ok.index('say "DONE: $STEP"') < ok.index("dataset_step")
    assert "dataset_step" not in failed                         # a failed refresh never publishes a dataset


def test_the_step_is_ready_only_once_the_sites_data_is_live():
    code = _code(SCRIPT.read_text())
    assert code.count("DATASET_READY=1") == 3
    live = code.split('STEP="all clear"', 1)[1]
    assert live.lstrip().startswith("DATASET_READY=1")          # the deploy was confirmed live above this point
    assert code.split('STEP="all clear"', 1)[0].count("DATASET_READY=1") == 2  # the two dry-run ends
    assert code.count("DATASET_READY=0") == 1


def test_the_step_can_never_fail_the_refresh():
    text = SCRIPT.read_text()
    step, publish, alarm = (_function(text, n) for n in ("dataset_step", "dataset_publish", "dataset_alarm"))
    for body in (step, publish, alarm):
        assert "fail " not in _code(body) and "step_aside" not in body
    assert step.rstrip().rstrip("}").rstrip().endswith("return 0")
    exits = re.compile(r"\bexit\s+(\d|\$)")
    assert not exits.search(_code(publish)) and not exits.search(_code(alarm))   # they return; they never exit
    assert "( cd \"$WORK/etl\"" in step                         # publish runs in a subshell
    assert not re.search(r"\breturn\s+[1-9$]", _code(step)) and not re.search(r"\breturn\s+[1-9$]", _code(alarm))


def test_the_token_never_appears_in_the_script():
    code = _code(SCRIPT.read_text())
    assert "ZENODO_TOKEN" not in code
    assert 'zen --release --env-file "$ENV_FILE"' in code      # Python reads it from the file


def test_its_alarm_has_its_own_label_and_mac_alarm_accepts_it():
    text = SCRIPT.read_text()
    alarm = _code(_function(text, "dataset_alarm"))
    assert 'title="MoleculeFinder dataset publish FAILED"' in alarm
    assert '"dataset-failure"' in alarm and "refresh-failure" not in alarm
    assert alarm.index("tgh workflow run mac-alarm.yml") < alarm.index("tgh issue create")
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "mac-alarm.yml").read_text())
    run = wf["jobs"]["alarm"]["steps"][0]["run"]
    assert re.search(r"^\s*dataset-failure\) desc=", run, re.MULTILINE)
    assert re.search(r"^\s*refresh-failure\) desc=", run, re.MULTILINE)  # the refresh's own alarm is unchanged


# ── the step, run ───────────────────────────────────────────────────────────────────────────────────────────────
_FAKE_MFETL = r"""#!/bin/bash
# stands in for "$PY -m moleculefinder_etl.cli zenodo ..."; FAKE_MODE says what Zenodo does
shift 3
echo "fake mfetl zenodo $*" >> "$CALLS"
case "$*" in
  *--check*) exit "${FAKE_CHECK:-0}" ;;
  *--dry-run*) [ "$FAKE_MODE" = fail ] && { echo "REFUSED: dry"; exit 1; }; echo "DRY RUN passed"; exit 0 ;;
esac
case "$FAKE_MODE" in
  nothing) echo "zenodo: release 2026.11: nothing due"; exit 0 ;;
  fail) echo "zenodo: REFUSED, nothing published: HTTP 403 for Bearer $FAKE_TOKEN"; exit 1 ;;
  publish)
    printf '  "2026.12": 10.5281/zenodo.200\n' >> moleculefinder_etl/sources/seeds/dataset_published.yaml
    printf '{"version": "2026.12"}\n' > data/dataset/MANIFEST.json
    printf '{"version": "2026.12", "doi": "10.5281/zenodo.200"}\n' > data/dataset/zenodo.json
    echo "zenodo: PUBLISHED version 2026.12"; exit 0 ;;
esac
"""


@pytest.fixture
def harness(tmp_path):
    if not shutil.which("jq") or not Path("/usr/bin/perl").exists():
        pytest.skip("needs jq and perl")
    origin, work = tmp_path / "origin.git", tmp_path / "etl"      # the job's checkout is $WORK/etl
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
    etl = work
    (etl / "data" / "dataset").mkdir(parents=True)
    (etl / "moleculefinder_etl" / "sources" / "seeds").mkdir(parents=True)
    (etl / "data" / "dataset" / "MANIFEST.json").write_text('{"version": "2026.11"}\n')
    (etl / "data" / "dataset" / "zenodo.json").write_text('{"version": "2026.11"}\n')
    (etl / "moleculefinder_etl" / "sources" / "seeds" / "dataset_published.yaml").write_text(
        'release: "2026.12"\nversions:\n  "2026.11": 10.5281/zenodo.100\n')
    git = ["git", "-C", str(etl), "-c", "user.name=T", "-c", "user.email=t@example.com"]
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "etl: refresh 2026-11-23"], check=True)
    subprocess.run([*git, "push", "-q", "origin", "HEAD:main"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(etl), "config", "user.name", "T"], check=True)
    subprocess.run(["git", "-C", str(etl), "config", "user.email", "t@example.com"], check=True)
    fake = tmp_path / "fake-python"
    fake.write_text(_FAKE_MFETL)
    fake.chmod(0o755)
    run_dir, state = tmp_path / "run", tmp_path / "state"
    run_dir.mkdir()
    state.mkdir()
    text = SCRIPT.read_text()
    return {"tmp": tmp_path, "origin": origin, "work": work, "fake": fake, "run_dir": run_dir, "state": state,
            "funcs": "".join(_function(text, n) for n in ("dataset_step", "dataset_publish", "dataset_alarm"))}


def _say_and_tilde() -> str:
    text = SCRIPT.read_text()
    lines = [line for line in text.splitlines() if re.match(r"^(say|tilde)\(\) \{", line)]
    assert len(lines) == 2
    return "\n".join(lines) + "\n"


def _run(h, mode: str, *, dry: int = 0, ready: int = 1, check: int = 0) -> tuple[int, str, str, str]:
    tgh_log = h["tmp"] / "tgh.log"
    calls = h["tmp"] / "calls.log"
    for f in (tgh_log, calls):
        f.write_text("")
    script = f"""
set -uo pipefail
{_say_and_tilde()}
tgh() {{ echo "tgh $*" >> "{tgh_log}"; if [ "$1 $2" = "workflow run" ]; then echo "--- stdin" >> "{tgh_log}"; cat >> "{tgh_log}"; fi; return 0; }}
osascript() {{ :; }}
sleep() {{ :; }}
{h["funcs"]}
DRY={dry}; DATASET_READY={ready}; WORK="{h["tmp"]}"; RUN_DIR="{h["run_dir"]}"; STATE_DIR="{h["state"]}"
LOG="$HOME/Library/Logs/MoleculeFinder/weekly-x.log"; WEEK=2026-W48; SNAP_SHA=abcdef1234567
ETL_GH=Trommsdorff/moleculefinder-etl; ENV_FILE=/nonexistent/.env; PY="{h["fake"]}"
NET_SECONDS=60; DATASET_SECONDS=60; DATASET_CHECK_TRIES=2; ETL_ENV=(env CALLS="{calls}" FAKE_MODE={mode} FAKE_CHECK={check} FAKE_TOKEN={FAKE_TOKEN})
dataset_step
echo "STEP-RC=$?"
"""
    p = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, timeout=120, check=False)
    rc = int(re.search(r"STEP-RC=(\d+)", p.stdout).group(1))
    return rc, p.stdout + p.stderr, tgh_log.read_text(), calls.read_text()


def _origin_subjects(h) -> list[str]:
    out = subprocess.run(["git", "--git-dir", str(h["origin"]), "log", "--format=%s", "main"],
                         capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


def test_nothing_due_commits_nothing_and_raises_no_alarm(harness):
    rc, out, tgh, calls = _run(harness, "nothing")
    assert rc == 0 and "dataset: nothing due" in out
    assert "workflow run" not in tgh and "issue create" not in tgh
    assert "--release --env-file /nonexistent/.env" in calls
    assert _origin_subjects(harness) == ["etl: refresh 2026-11-23"]


def test_a_publish_is_recorded_on_main_and_checked(harness):
    rc, out, tgh, calls = _run(harness, "publish")
    assert rc == 0, out
    assert _origin_subjects(harness)[0] == "dataset: 2026.12 published on Zenodo (10.5281/zenodo.200)"
    assert "--check" in calls and "workflow run" not in tgh
    assert "issue list --repo Trommsdorff/moleculefinder-etl --label dataset-failure" in tgh   # the all clear


def test_a_failure_raises_the_dataset_alarm_and_still_returns_0(harness):
    rc, _out, tgh, _ = _run(harness, "fail")
    assert rc == 0
    assert "tgh workflow run mac-alarm.yml" in tgh
    sent = json.loads(tgh.split("--- stdin\n", 1)[1])
    assert sent["label"] == "dataset-failure" and sent["title"] == "MoleculeFinder dataset publish FAILED"
    assert "NOTHING was published" in sent["body"] and "The refresh itself succeeded" in sent["body"]
    assert FAKE_TOKEN not in sent["body"] and FAKE_TOKEN not in tgh and "[redacted]" in sent["body"]
    assert _origin_subjects(harness) == ["etl: refresh 2026-11-23"]


def test_a_publish_whose_public_check_fails_alarms_but_keeps_the_record(harness):
    rc, _out, tgh, calls = _run(harness, "publish", check=1)
    assert rc == 0 and calls.count("--check") == 2
    assert _origin_subjects(harness)[0].startswith("dataset: 2026.12 published on Zenodo")
    sent = json.loads(tgh.split("--- stdin\n", 1)[1])
    assert "public check still failed" in sent["body"]


def test_a_dry_run_only_dry_runs_and_files_nothing(harness):
    rc, out, tgh, calls = _run(harness, "fail", dry=1)
    assert rc == 0 and "DATASET ALARM (dry run: not filed)" in out
    assert tgh == "" and "--release --dry-run" in calls and "--env-file" not in calls
    rc, out, tgh, calls = _run(harness, "publish", dry=1)
    assert rc == 0 and tgh == "" and _origin_subjects(harness) == ["etl: refresh 2026-11-23"]


def test_a_run_whose_data_is_not_live_never_runs_the_step(harness):
    rc, _out, tgh, calls = _run(harness, "publish", ready=0)
    assert rc == 0 and calls == "" and tgh == ""
