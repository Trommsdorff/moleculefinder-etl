"""The weekly refresh's mirrors step (scripts/mac/weekly-refresh.sh, 2026-11-20): once Zenodo is current, `mfetl
mirrors` brings Hugging Face and Kaggle to its latest version. Like the dataset step it must never fail, retry or
block the refresh, and a failure raises its OWN alarm (label mirror-failure). The step's functions are run here from
the script itself, with `mfetl` and `gh` stubbed."""
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
FAKE_HF = "hf_" + "A" * 34
FAKE_KG = "KGAT_" + "b" * 40


def _code(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _function(text: str, name: str) -> str:
    body = text.split(f"\n{name}() {{", 1)[1].split("\n}\n", 1)[0]
    return f"{name}() {{{body}\n}}\n"


def test_it_runs_after_the_dataset_step_and_only_when_zenodo_is_current():
    code = _code(SCRIPT.read_text())
    finish = code.split("finish() {", 1)[1].split("\non_signal() {", 1)[0]
    ok, failed = finish.split("  else\n", 1)
    assert ok.index("dataset_step") < ok.index("mirrors_step")
    assert "mirrors_step" not in failed
    step = _function(SCRIPT.read_text(), "mirrors_step")
    assert step.lstrip().split("\n")[1].strip() == '[ "$DATASET_OK" = 1 ] || return 0'
    ds = _function(SCRIPT.read_text(), "dataset_step")
    assert ds.index("DATASET_OK=1") < ds.index('[ "$DRY" = 1 ] && return 0')
    assert code.count("DATASET_OK=0") == 1


def test_it_can_never_fail_the_refresh():
    text = SCRIPT.read_text()
    step, run, alarm = (_function(text, n) for n in ("mirrors_step", "mirrors_run", "mirrors_alarm"))
    for body in (step, run, alarm):
        assert "fail " not in _code(body) and "step_aside" not in body
    assert step.rstrip().rstrip("}").rstrip().endswith("return 0")
    exits = re.compile(r"\bexit\s+(\d|\$)")
    assert not exits.search(_code(run)) and not exits.search(_code(alarm))
    assert "( cd \"$WORK/etl\"" in step
    assert not re.search(r"\breturn\s+[1-9$]", _code(step)) and not re.search(r"\breturn\s+[1-9$]", _code(alarm))


def test_no_login_appears_in_the_script_and_the_file_path_is_handed_over():
    code = _code(SCRIPT.read_text())
    for name in ("HF_TOKEN", "KAGGLE_API_TOKEN", "KAGGLE_KEY", "KAGGLE_USERNAME"):
        assert name not in code
    assert 'mir --env-file "$ENV_FILE"' in code and 'mir --dry-run --env-file "$ENV_FILE"' in code


def test_its_alarm_has_its_own_label_and_mac_alarm_accepts_it():
    alarm = _code(_function(SCRIPT.read_text(), "mirrors_alarm"))
    assert 'title="MoleculeFinder dataset mirrors FAILED"' in alarm
    assert '"mirror-failure"' in alarm and "refresh-failure" not in alarm and "dataset-failure" not in alarm
    assert alarm.index("tgh workflow run mac-alarm.yml") < alarm.index("tgh issue create")
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "mac-alarm.yml").read_text())
    run = wf["jobs"]["alarm"]["steps"][0]["run"]
    for label in ("mirror-failure", "dataset-failure", "refresh-failure", "news-failure"):
        assert re.search(rf"^\s*{label}\) desc=", run, re.MULTILINE)


_FAKE_MFETL = r"""#!/bin/bash
shift 3
echo "fake mfetl $*" >> "$CALLS"
case "$FAKE_MODE" in
  ok) echo "mirrors: SUMMARY huggingface HOLDS; kaggle HOLDS"; exit 0 ;;
  fail) echo "mirrors: kaggle: REFUSED: HTTP 401 for $FAKE_HF and Bearer $FAKE_KG"; exit 1 ;;
esac
"""


@pytest.fixture
def harness(tmp_path):
    if not shutil.which("jq") or not Path("/usr/bin/perl").exists():
        pytest.skip("needs jq and perl")
    (tmp_path / "etl").mkdir()
    fake = tmp_path / "fake-python"
    fake.write_text(_FAKE_MFETL)
    fake.chmod(0o755)
    (tmp_path / "run").mkdir()
    (tmp_path / "state").mkdir()
    text = SCRIPT.read_text()
    funcs = "".join(_function(text, n) for n in ("mirrors_step", "mirrors_run", "mirrors_alarm"))
    sayt = "\n".join(line for line in text.splitlines() if re.match(r"^(say|tilde)\(\) \{", line)) + "\n"
    return {"tmp": tmp_path, "fake": fake, "funcs": funcs, "say": sayt}


def _run(h, mode, *, dry=0, ok=1):
    tgh_log, calls = h["tmp"] / "tgh.log", h["tmp"] / "calls.log"
    tgh_log.write_text("")
    calls.write_text("")
    script = f"""
set -uo pipefail
{h["say"]}
tgh() {{ echo "tgh $*" >> "{tgh_log}"; if [ "$1 $2" = "workflow run" ]; then echo "--- stdin" >> "{tgh_log}"; cat >> "{tgh_log}"; fi; return 0; }}
osascript() {{ :; }}
{h["funcs"]}
DRY={dry}; DATASET_OK={ok}; WORK="{h["tmp"]}"; RUN_DIR="{h["tmp"] / "run"}"; STATE_DIR="{h["tmp"] / "state"}"
LOG="$HOME/Library/Logs/MoleculeFinder/weekly-x.log"; WEEK=2026-W48
ETL_GH=Trommsdorff/moleculefinder-etl; ENV_FILE=/nonexistent/.env; PY="{h["fake"]}"; MIRROR_SECONDS=60
ETL_ENV=(env CALLS="{calls}" FAKE_MODE={mode} FAKE_HF={FAKE_HF} FAKE_KG={FAKE_KG})
mirrors_step
echo "STEP-RC=$?"
"""
    p = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, timeout=120, check=False)
    rc = int(re.search(r"STEP-RC=(\d+)", p.stdout).group(1))
    return rc, p.stdout + p.stderr, tgh_log.read_text(), calls.read_text()


def test_a_green_run_hands_over_the_env_file_and_closes_an_open_issue(harness):
    rc, out, tgh, calls = _run(harness, "ok")
    assert rc == 0, out
    assert "fake mfetl --env-file /nonexistent/.env" in calls
    assert "workflow run" not in tgh and "issue list --repo Trommsdorff/moleculefinder-etl --label mirror-failure" in tgh


def test_a_failure_raises_the_mirrors_alarm_and_still_returns_0(harness):
    rc, _out, tgh, _ = _run(harness, "fail")
    assert rc == 0
    sent = json.loads(tgh.split("--- stdin\n", 1)[1])
    assert sent["label"] == "mirror-failure" and sent["title"] == "MoleculeFinder dataset mirrors FAILED"
    assert "The refresh and Zenodo are fine" in sent["body"]
    for secret in (FAKE_HF, FAKE_KG):
        assert secret not in sent["body"] and secret not in tgh
    assert "[redacted]" in sent["body"]


def test_a_dry_run_only_dry_runs_and_files_nothing(harness):
    rc, out, tgh, calls = _run(harness, "fail", dry=1)
    assert rc == 0 and "MIRRORS ALARM (dry run: not filed)" in out and tgh == ""
    assert "fake mfetl --dry-run --env-file /nonexistent/.env" in calls


def test_nothing_runs_when_zenodo_is_not_current(harness):
    rc, _out, tgh, calls = _run(harness, "ok", ok=0)
    assert rc == 0 and calls == "" and tgh == ""
