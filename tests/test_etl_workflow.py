"""The weekly workflow's own shell, run offline against a throwaway repository.

The scripts are read out of .github/workflows/etl.yml, not copied, so these tests exercise
exactly what the runner executes. Each runs under `bash -e` like a GitHub `run:` step, against a
local clone whose `origin` is a bare repository standing in for GitHub, with the user's git
configuration switched off so nothing on this machine leaks in.

Why they exist: since the molecule of the week (2026-09-23) every Monday run changes the
snapshot, which leaves the no-change heartbeat looking like dead code. It is not, and a failed
run needs one too. See the comments beside both in etl.yml.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "etl.yml"
pytestmark = pytest.mark.skipif(not (shutil.which("bash") and shutil.which("git")),
                                reason="needs bash and git")
ISOLATED = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_DATE": "2026-09-21T11:30:00Z", "GIT_COMMITTER_DATE": "2026-09-21T11:30:00Z"}


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _step(job: str, name: str) -> dict:
    for step in _workflow()["jobs"][job]["steps"]:
        if step.get("name") == name:
            return step
    raise AssertionError(f"etl.yml has no step {name!r} in job {job!r}")


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **ISOLATED},
                         capture_output=True, text=True)
    assert out.returncode == 0, f"git {' '.join(args)} failed: {out.stderr}"
    return out.stdout.strip()


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def repo(tmp_path):
    """A clone with the snapshot layout, pushed once to a bare `origin`."""
    remote, work = tmp_path / "origin.git", tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True,
                   env={**os.environ, **ISOLATED})
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _git(work, "config", "user.name", "fixture")
    _git(work, "config", "user.email", "fixture@example.invalid")
    _git(work, "remote", "add", "origin", str(remote))
    _write(work, "data/snapshots/featured.json", '{"current": {"week": "2026-W39"}}')
    _write(work, "data/snapshots/meta.json", '{"refreshed": "2026-09-21"}')
    _write(work, "data/snapshots/molecules/caffeine.json", '{"slug": "caffeine"}')
    _write(work, "data/seed/canon.parquet", "parquet")
    _write(work, "data/LAST_CHECK", "2026-09-14T11:25:00Z\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "init")
    _git(work, "push", "-q", "-u", "origin", "main")
    return work, remote


def _run(step: dict, cwd: Path, tmp_path: Path, **env) -> tuple[subprocess.CompletedProcess, dict]:
    outputs = tmp_path / "github_output"
    outputs.write_text("")
    proc = subprocess.run(["bash", "-e", "-c", step["run"]], cwd=cwd, capture_output=True, text=True,
                          env={**os.environ, **ISOLATED, "GITHUB_OUTPUT": str(outputs), **env})
    pairs = dict(line.split("=", 1) for line in outputs.read_text().splitlines() if "=" in line)
    return proc, pairs


def _pushed(remote: Path, *args: str) -> str:
    return _git(remote, *args)


# ── the commit step: change path and no-change heartbeat ────────────────────
def test_a_new_week_commits_a_refresh_and_reports_the_change(repo, tmp_path):
    work, remote = repo
    _write(work, "data/snapshots/featured.json", '{"current": {"week": "2026-W40"}}')
    _write(work, "data/snapshots/meta.json", '{"refreshed": "2026-09-28"}')
    proc, out = _run(_step("run", "commit snapshot"), work, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert out["snapshot_changed"] == "true"
    assert (out["molecules_changed"], out["molecules_added"]) == ("0", "0")
    assert _pushed(remote, "log", "-1", "--format=%s", "main").startswith("etl: refresh ")
    assert out["snapshot_sha"] == _pushed(remote, "rev-parse", "main")
    changed = _pushed(remote, "diff", "--name-only", "main~1", "main").splitlines()
    assert changed == ["data/snapshots/featured.json", "data/snapshots/meta.json"]


def test_a_run_that_changes_nothing_still_commits_the_heartbeat(repo, tmp_path):
    work, remote = repo
    proc, out = _run(_step("run", "commit snapshot"), work, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert out["snapshot_changed"] == "false"
    subject = _pushed(remote, "log", "-1", "--format=%s", "main")
    assert subject.startswith("etl: no changes ") and subject.endswith("[heartbeat]")
    assert _pushed(remote, "diff", "--name-only", "main~1", "main") == "data/LAST_CHECK"


# ── the failed-run heartbeat ─────────────────────────────────────────────────
def test_a_failed_run_publishes_only_the_heartbeat(repo, tmp_path):
    """The run died half way: a rewritten file, a new file, even a local commit. None of it
    may reach origin; the timestamp must."""
    work, remote = repo
    start = _git(work, "rev-parse", "HEAD")
    _write(work, "data/snapshots/featured.json", '{"half": "written"}')
    _git(work, "commit", "-q", "-am", "a commit the failed run made")
    _write(work, "data/snapshots/molecules/new.json", '{"slug": "new"}')
    _write(work, "data/snapshots/meta.json", '{"refreshed": "2026-09-28"}')
    (work / "data" / "raw_cache").mkdir()
    _write(work, "data/raw_cache/keep.json", "{}")          # untracked cache survives for the save step

    proc, _ = _run(_step("run", "heartbeat after a failed run"), work, tmp_path, GITHUB_SHA=start)
    assert proc.returncode == 0, proc.stderr
    subject = _pushed(remote, "log", "-1", "--format=%s", "main")
    assert subject.startswith("etl: run failed ") and subject.endswith("[heartbeat]")
    assert _pushed(remote, "rev-parse", "main~1") == start
    assert _pushed(remote, "diff", "--name-only", "main~1", "main") == "data/LAST_CHECK"
    assert (work / "data" / "raw_cache" / "keep.json").exists()


def test_a_heartbeat_that_cannot_push_warns_instead_of_failing(repo, tmp_path):
    work, remote = repo
    start = _git(work, "rev-parse", "HEAD")
    shutil.rmtree(remote)
    proc, _ = _run(_step("run", "heartbeat after a failed run"), work, tmp_path, GITHUB_SHA=start)
    assert proc.returncode == 0
    assert "::warning::could not push the failed-run heartbeat" in proc.stdout


# ── all-clear: a green run closes any open refresh-failure issue ─────────────
FAKE_GH = """#!/bin/bash
# Stands in for the GitHub CLI: records each call, answers `issue list` from FAKE_GH_LIST.
printf '%s\\n' "$*" >> "$FAKE_GH_LOG"
case "$1 $2" in
  "issue list")
    if [ -n "$FAKE_GH_LIST_RC" ]; then echo "HTTP 502: Bad Gateway" >&2; exit "$FAKE_GH_LIST_RC"; fi
    printf '%s' "$FAKE_GH_LIST"; exit 0 ;;
  "issue close")
    case " $FAKE_GH_CLOSE_FAIL " in *" $3 "*) echo "HTTP 403: Resource not accessible" >&2; exit 1 ;; esac
    exit 0 ;;
esac
echo "unexpected gh call: $*" >&2; exit 2
"""
RUN_URL = "https://github.com/Trommsdorff/moleculefinder-etl/actions/runs/123"


def _all_clear(tmp_path, **fake) -> tuple[subprocess.CompletedProcess, list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    calls = tmp_path / "gh-calls.log"
    calls.write_text("")
    env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_GH_LOG": str(calls),
           "RUNNER_TEMP": str(tmp_path), "RUN": RUN_URL, "EVENT": "schedule",
           "FAKE_GH_LIST": "", "FAKE_GH_LIST_RC": "", "FAKE_GH_CLOSE_FAIL": "", **fake}
    step = _step("all-clear", "Close any open refresh-failure issue")
    proc = subprocess.run(["bash", "-e", "-c", step["run"]], cwd=tmp_path, capture_output=True, text=True,
                          env={**os.environ, **env})
    return proc, calls.read_text().splitlines()


def test_a_green_run_with_no_open_issue_exits_clean(tmp_path):
    proc, calls = _all_clear(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "nothing to close" in proc.stdout
    assert len(calls) == 1 and calls[0].startswith("issue list --label refresh-failure --state open")


def test_a_green_run_closes_every_open_issue_naming_the_run(tmp_path):
    proc, calls = _all_clear(tmp_path, FAKE_GH_LIST="2\n7\n")
    assert proc.returncode == 0, proc.stderr
    closes = [c for c in calls if c.startswith("issue close")]
    assert [c.split()[2] for c in closes] == ["2", "7"]
    for c in closes:
        assert f"--comment Run {RUN_URL} (schedule, " in c and "went green" in c


def test_a_failure_to_list_or_close_warns_and_never_fails_the_run(tmp_path):
    proc, _ = _all_clear(tmp_path, FAKE_GH_LIST_RC="1")
    assert proc.returncode == 0
    assert "::warning::could not list refresh-failure issues" in proc.stdout
    assert "HTTP 502" in proc.stdout

    proc, calls = _all_clear(tmp_path, FAKE_GH_LIST="2\n7\n", FAKE_GH_CLOSE_FAIL="2")
    assert proc.returncode == 0
    assert "::warning::could not close refresh-failure issue #2" in proc.stdout
    assert "closed #7" in proc.stdout


def test_all_clear_runs_only_after_a_green_run_and_alarm_only_after_a_red_one():
    jobs = _workflow()["jobs"]
    clear, alarm = jobs["all-clear"], jobs["alarm"]
    assert clear["needs"] == ["run", "sync-web"] and "if" not in clear      # default: success()
    assert clear["permissions"] == {"issues": "write"}
    assert clear["steps"][0]["env"]["GH_REPO"] == "${{ github.repository }}"
    assert alarm["needs"] == ["run", "sync-web"] and alarm["if"] == "failure()"


def test_both_heartbeats_are_wired_where_they_can_run():
    """The commit step runs only on success and still has its no-change branch; the failed-run
    step runs only on failure, after it, and before the cache is saved."""
    steps = _workflow()["jobs"]["run"]["steps"]
    names = [s.get("name") or s.get("uses") for s in steps]
    commit, failed = names.index("commit snapshot"), names.index("heartbeat after a failed run")
    save = names.index("actions/cache/save@v4")
    assert commit < failed < save
    assert "if" not in steps[commit] and steps[failed]["if"] == "failure()"
    assert "[heartbeat]" in steps[commit]["run"] and "git diff --cached --quiet" in steps[commit]["run"]
    assert steps[save]["if"] == "always()"


# ── a manual backup since the switch to the Mac mini (2026-11-16) ─────────────────────────────
def test_it_is_a_manual_backup_with_no_schedule():
    wf = _workflow()
    on = wf.get("on", wf.get(True))
    assert set(on) == {"workflow_dispatch"}, on
    head = WORKFLOW.read_text().split("name: etl", 1)[0]
    assert "MANUAL BACKUP ONLY (2026-11)" in head and "scripts/mac/weekly-refresh.sh" in head
    assert "docs/MAC-WEEKLY-REFRESH.md" in head


def test_every_job_that_installs_takes_the_committed_lock_frozen_as_the_mac_does():
    """GitHub's build was never pinned (`pip install -e .` took the newest of everything each Monday)."""
    text = WORKFLOW.read_text()
    assert "pip install" not in "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    mac = (WORKFLOW.parents[2] / "scripts" / "mac" / "weekly-refresh.sh").read_text()
    for name, job in _workflow()["jobs"].items():
        runs = [s.get("run", "") for s in job["steps"]]
        if any("moleculefinder_etl" in r or "mfetl" in r for r in runs):
            install = next(r for r in runs if "uv sync" in r)
            assert "--frozen" in install and "--no-dev" in install and "--no-install-project" in install, name
            uv = next(s for s in job["steps"] if s.get("uses", "").startswith("astral-sh/setup-uv@"))
            assert re.fullmatch(r"astral-sh/setup-uv@v\d+\.\d+\.\d+", uv["uses"])          # an exact release
            assert uv["with"]["version"] == "0.13.0"
            build = next(r for r in runs if "cli all" in r)
            assert build.startswith(".venv/bin/python -m moleculefinder_etl.cli all --target 10000")
    assert "uv sync --quiet --frozen --no-dev --no-install-project" in mac          # the same install on the Mac


def test_the_manual_button_cannot_fight_the_mac_job(repo, tmp_path):
    """Pressed while the Mac's run is going: whichever pushes the ETL's main second is refused, publishes
    nothing, and opens no data PR (sync-web needs the run job). Here the Mac pushed first."""
    work, remote = repo
    start = _git(work, "rev-parse", "HEAD")
    mac = tmp_path / "mac"
    subprocess.run(["git", "clone", "-q", str(remote), str(mac)], check=True, env={**os.environ, **ISOLATED})
    _git(mac, "config", "user.name", "Trommsdorff")
    _git(mac, "config", "user.email", "291580674+Trommsdorff@users.noreply.github.com")
    _write(mac, "data/snapshots/meta.json", '{"refreshed": "2026-11-23"}')
    _write(mac, "data/LAST_CHECK", "2026-11-23T08:20:00Z\n")
    _git(mac, "commit", "-q", "-am", "etl: refresh 2026-11-23")
    _git(mac, "push", "-q", "origin", "HEAD:main")
    mac_sha = _git(mac, "rev-parse", "HEAD")

    _write(work, "data/snapshots/meta.json", '{"refreshed": "2026-11-23", "github": true}')
    proc, out = _run(_step("run", "commit snapshot"), work, tmp_path)
    assert proc.returncode != 0                                   # the push is refused: the job fails
    assert "snapshot_sha" not in out                              # nothing for sync-web to check out
    assert _pushed(remote, "rev-parse", "main") == mac_sha        # the Mac's refresh stands

    proc, _ = _run(_step("run", "heartbeat after a failed run"), work, tmp_path, GITHUB_SHA=start)
    assert proc.returncode == 0 and "::warning::could not push the failed-run heartbeat" in proc.stdout
    assert _pushed(remote, "rev-parse", "main") == mac_sha        # nothing rewrites the Mac's commit

    jobs = _workflow()["jobs"]
    assert jobs["sync-web"]["needs"] == "run" and "if" not in jobs["sync-web"]   # a failed run opens no PR


def test_the_mac_job_steps_aside_while_the_manual_backup_runs():
    mac = (WORKFLOW.parents[2] / "scripts" / "mac" / "weekly-refresh.sh").read_text()
    check = mac.split('STEP="checking for another build"', 1)[1].split("attempt $(date", 1)[0]
    assert "tgh run list --repo \"$ETL_GH\" --workflow etl.yml" in check
    assert 'select(.status != "completed")' in check and 'step_aside "a GitHub run of etl.yml' in check
    assert 'fail "could not ask GitHub whether the backup workflow etl.yml is running"' in check
    # and the Mac's own push refuses a main that moved during its run, publishing nothing
    assert 'git push --quiet origin HEAD:main & wait $!' in mac and "did main move during the run?" in mac
    assert '--match-head-commit "$SHA"' in mac
