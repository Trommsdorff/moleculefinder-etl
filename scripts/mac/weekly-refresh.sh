#!/bin/bash
# MoleculeFinder's weekly data refresh, run on Garrett's Mac mini (2026-11; the network's rule,
# network/137-Finder-Web-Standards.md section 14: "scheduled jobs run on the Mac mini, not on GitHub Actions,
# for every finder site; GitHub workflows stay only as manual backups"). It does everything
# .github/workflows/etl.yml does on its Monday cron (jobs run, sync-web, all-clear, alarm), and replaces that
# cron. etl.yml keeps only its manual "Run workflow" button, as the backup. The step-by-step table of what the
# workflow did and how this does each part is docs/MAC-WEEKLY-REFRESH.md.
#
# STANDING AUTHORISATION (company CLAUDE.md, 2026-08-08): a SCHEDULED data refresh publishes itself. This script
# is that cron; it is not an agent deploying. It publishes only origin/main's code, from a fresh checkout.
#
# WHAT IT DOES, in order:
#   the gate (has this ISO week already succeeded?) -> the lock -> disk, network, toolchain and keys checked ->
#   steps aside if another MoleculeFinder build or a GitHub run of etl.yml is going -> a clean checkout of
#   origin/main (a git worktree) -> the pinned Python environment (uv.lock, Python 3.12) ->
#   `mfetl all --target 10000` in refresh mode with the real database keys, every guard inside it ->
#   commit the snapshot to the ETL's main and push (or the no-change heartbeat) -> copy the snapshot WHOLE into
#   the web repo, open or update the ONE data pull request, wait for the web's `ci / verify` on that exact
#   commit, squash-merge it (the merge is the deploy) -> wait until Vercel's production deployment of the
#   merge commit succeeds -> close any open refresh-failure issue -> tidy up.
#
# WHEN: launchd (com.137finder.moleculefinder.weekly-refresh, scripts/mac/com.137finder.moleculefinder.weekly-
# refresh.plist) starts it Mondays 03:10 Eastern, retries Monday every two hours from 06:10 to 18:10, and
# catches up at 03:10 every other day. It runs only while this ISO week (Monday to Sunday, UTC: the same
# clock the snapshot's `refreshed` date and so the molecule of the week use) has no success and fewer than
# MAX_ATTEMPTS tries, so the extra starts are retries and catch-ups and cost nothing when the week is done.
#
# NO PROMPTS: every git call takes GitHub's credentials from `gh` (GIT_CONFIG_* below: no keychain helper, no
# "allow access?" dialog; GravityFinder's 2026-11-11 run waited five hours behind one), never prompts
# (GIT_TERMINAL_PROMPT=0, GH_PROMPT_DISABLED=1), and every network call has a time limit.
#
# NEVER OVERLAPS: a lock directory holds the running pid. It never touches the interactive checkouts
# (moleculefinder-etl/, moleculefinder-web/): it builds in its own worktrees of origin/main, with its own
# inputs cache and Python environment under ~/Library/Application Support/MoleculeFinder. It steps aside,
# quietly and without counting a try, while another session's `mfetl` build or a GitHub etl.yml run is going.
#
# ALARM: a run that fails, is cancelled (stopped, shut down, the agent unloaded), times out, or merges data that
# never goes live opens (or comments on) the GitHub issue labelled `refresh-failure` on
# Trommsdorff/moleculefinder-etl, as the workflow's `alarm` job did, and shows a Mac notification. It does so by
# dispatching .github/workflows/mac-alarm.yml, which files the issue as github-actions[bot] and fails, so GitHub
# emails Garrett (it emails nobody about an issue they opened themselves, which is what `gh` here would be).
# A week where nothing changed ends quietly. If the Mac is off, the GitHub watchdog (watchdog.yml) notices.
#
# KEYS: the real SUPABASE_URL and SUPABASE_SERVICE_KEY, read from the ETL's gitignored .env by
# scripts/mac/with_keys.py (python-dotenv): never sourced, never printed, never logged. A dry run blanks them.
#
# MANUAL:  scripts/mac/weekly-refresh.sh --force           ignore this week's state (still publishes)
#          scripts/mac/weekly-refresh.sh --dry-run         the whole run with the database load, the commit, the
#                                                          pushes, the pull request and the merge each replaced by
#                                                          a logged "would"; no state; the alarm it would file is
#                                                          printed, not filed. Builds from a throwaway copy of the
#                                                          inputs cache, so it never moves the real one.
#          scripts/mac/weekly-refresh.sh --dry-run --ref B  a local branch's code instead of origin/main (dry runs
#                                                          only: only origin/main is ever published)
#          scripts/mac/weekly-refresh.sh --seed-cache      fill the job's inputs cache with the inputs main was
#                                                          built from (once, at the switch), and stop
#          scripts/mac/weekly-refresh.sh --schedule-check EPOCH [STATE_DIR]   what a start then would do
set -uo pipefail

MF="$HOME/137/moleculefinder"
ETL_REPO="$MF/moleculefinder-etl"
WEB_REPO="$MF/moleculefinder-web"
ENV_FILE="$ETL_REPO/.env"                                  # the real keys (gitignored); read by with_keys.py only
WORK="$MF/mf-weekly-worktree"                              # this run's checkouts (etl/, web/); removed after
STATE_DIR="${MF_WEEKLY_STATE_DIR:-$HOME/Library/Application Support/MoleculeFinder}"
LOG_DIR="${MF_WEEKLY_LOG_DIR:-$HOME/Library/Logs/MoleculeFinder}"
CACHE="$STATE_DIR/raw_cache"                               # THE inputs: the canonical cache since the move
MAIN_INPUTS="$STATE_DIR/inputs-main"                       # the inputs main names (sync-inputs reads this)
VENV="$STATE_DIR/venv"                                     # built from uv.lock, Python 3.12
PY_BASE="/opt/homebrew/opt/python@3.12/bin/python3.12"     # the GitHub run used 3.12 too
ETL_GH="Trommsdorff/moleculefinder-etl"
WEB_GH="Trommsdorff/moleculefinder-web"
SITE="https://moleculefinder.com"
MAX_ATTEMPTS=8
WATCHDOG_SECONDS=$((2 * 3600))                             # the hard limit for one run
NETWORK_WAIT_SECONDS=$((60 * 60))
CI_APPEAR_SECONDS=300                                      # etl.yml: the ci run must appear within 5 min
CI_FINISH_SECONDS=1800                                     # and finish within 30
DEPLOY_WAIT_SECONDS=$((30 * 60))
CI_LOG_LINES=40                                            # a failed ci step's log lines quoted in the alarm
DISK_FLOOR_GIB=25                                          # refuse (and alarm) below this much free space
LOG_KEEP_DAYS=90
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export HOME LANG="${LANG:-en_US.UTF-8}" LC_ALL="${LC_ALL:-en_US.UTF-8}"
export TZ="America/New_York"                               # wall-clock times in the log are Eastern ("ET")
export GIT_TERMINAL_PROMPT=0 GH_PROMPT_DISABLED=1 GH_NO_UPDATE_NOTIFIER=1 GIT_CONFIG_COUNT=2
export GIT_CONFIG_KEY_0="credential.helper" GIT_CONFIG_VALUE_0=""
export GIT_CONFIG_KEY_1="credential.helper" GIT_CONFIG_VALUE_1="!/opt/homebrew/bin/gh auth git-credential"
export UV_PYTHON_DOWNLOADS=never UV_NO_PROGRESS=1
NET_SECONDS=300                                            # a git push or fetch that takes longer has hung
GH_SECONDS=120                                             # one gh call

# ── the week and the gate (also --schedule-check, for tests/test_mac_weekly.py) ──
# The ISO week in UTC: the snapshot's `refreshed` date is a UTC date and the molecule of the week is its ISO week.
week_of() { date -u -r "$1" +%G-W%V; }
gate() {
  grep -q '^success' "$1" 2>/dev/null && { echo "this week already succeeded"; return; }
  local tries; tries=$(grep -c '^attempt' "$1" 2>/dev/null || true)
  [ "${tries:-0}" -ge "$MAX_ATTEMPTS" ] && { echo "$tries tries this week"; return; }
  echo ""
}
if [ "${1:-}" = "--schedule-check" ]; then
  e="${2:?--schedule-check EPOCH [STATE_DIR]}"; sd="${3:-$STATE_DIR}"; w=$(week_of "$e"); why=$(gate "$sd/week-$w")
  echo "at=$(date -r "$e" '+%a %F %T %Z') week=$w run=$([ -z "$why" ] && echo yes || echo no)${why:+ reason=$why}"
  exit 0
fi

# Own process group, so the time limit (and a cancel) stops every child (python, git, gh) at once.
if [ -z "${MF_WEEKLY_SESSION:-}" ]; then
  export MF_WEEKLY_SESSION=1
  exec /usr/bin/perl -MPOSIX -e 'POSIX::setsid(); exec @ARGV' /bin/bash "$0" "$@"
fi

FORCE=0; DRY=0; SEED_ONLY=0; REF="origin/main"
while [ $# -gt 0 ]; do
  case "$1" in
    --force) FORCE=1 ;;
    --dry-run) DRY=1 ;;
    --seed-cache) SEED_ONLY=1 ;;
    --ref) REF="${2:?--ref needs a git ref}"; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
if [ "$DRY" = 0 ] && [ "$REF" != "origin/main" ]; then echo "--ref is for dry runs only: only origin/main is published" >&2; exit 2; fi

umask 077                                                  # the logs and state are Garrett's alone
mkdir -p "$STATE_DIR" "$LOG_DIR"
WEEK=$(week_of "$(date +%s)")
STATE="$STATE_DIR/week-$WEEK"
if [ "$FORCE" = 0 ] && [ "$DRY" = 0 ] && [ "$SEED_ONLY" = 0 ] && [ -n "$(gate "$STATE")" ]; then exit 0; fi

LOCK="$STATE_DIR/running.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  pid=$(cat "$LOCK/pid" 2>/dev/null || true)
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    echo "[$(date '+%F %T') ET] another weekly refresh is running (pid $pid): not starting a second one" >&2
    exit 0
  fi
  rm -rf "$LOCK" && mkdir "$LOCK"
fi
echo $$ > "$LOCK/pid"

STAMP=$(date +%Y%m%d-%H%M%S)
KIND=$([ "$DRY" = 1 ] && echo -dry-run; [ "$SEED_ONLY" = 1 ] && echo -seed-cache)
LOG="$LOG_DIR/weekly-$STAMP$KIND.log"
SUMMARY="$LOG_DIR/summary-$STAMP$KIND.md"
exec >>"$LOG" 2>&1
STEP="start"; WATCHDOG=""; CAUSE=""; PUBLISHED=0; HELD="unknown"; PRODUCTS_HELD="unknown"; LD50_HELD="unknown"
DRAWINGS_TEXT="unknown: the run failed before the drawing guard ran"
RUN_CACHE="$CACHE"; SCRATCH_CACHE=""; PR=""; PR_URL=""; SNAP_SHA=""; MERGE_SHA=""; CI_DETAIL=""
RUN_DIR="$STATE_DIR/run-$STAMP"                             # this run's report files, outside every checkout
mkdir -p "$RUN_DIR"

say() { echo "[$(date '+%F %T') ET] $*"; }
tilde() { sed "s#$HOME#~#g"; }                               # the public issue never carries the home path
tgh() { /usr/bin/perl -e 'alarm shift; exec @ARGV' "$GH_SECONDS" /opt/homebrew/bin/gh "$@"; }
# netgit "<step>" args...: a git command that talks to GitHub, stopped if it hangs
netgit() { local step="$1"; shift; run "$step" /usr/bin/perl -e 'alarm shift; exec @ARGV' "$NET_SECONDS" git "$@"; }
free_gib() { df -g / | awk 'NR==2 {print $4}'; }

# ── what broke on the website's check (2026-11-16) ──
# A red `ci / verify` used to alarm with "the check failed" and nothing else (2026-11-16, PR #15: the cause, a
# test reading the ETL's folder, was found only by opening the run). This reads the failed run itself: the name
# of every failed step (from the run's jobs; `gh --log-failed` labels each line "UNKNOWN STEP"), the test
# runner's FAIL lines (they name the broken test), and the last CI_LOG_LINES lines of the step's output, cut at
# the step's own "Process completed with exit code" line so the post-job cleanup is not what gets quoted.
# GitHub writes colour codes either as escapes or as literal "^[" text; both are stripped. Never a gate: if gh
# cannot read the run, the alarm says so and still goes out.
ci_failure_detail() {   # ci_failure_detail <ci run id>: sets CI_FAILED_STEPS and CI_DETAIL
  local id="$1" log
  CI_FAILED_STEPS=$(cd "$STATE_DIR" && tgh run view "$id" --repo "$WEB_GH" --json jobs --jq \
    '[.jobs[] | . as $j | .steps[]? | select(.conclusion == "failure") | "\($j.name) / \(.name)"] | join(", ")' 2>/dev/null)
  log=$( (cd "$STATE_DIR" && tgh run view "$id" --repo "$WEB_GH" --log-failed 2>/dev/null) | ci_log_clean)
  CI_DETAIL="ci run $id: https://github.com/$WEB_GH/actions/runs/$id
Failed step: ${CI_FAILED_STEPS:-unknown, gh could not read the jobs of the run}
Failed tests:
$(printf '%s\n' "$log" | grep -E '^ *(FAIL|×) ' | sed -E 's/^ */  /' | head -20 | grep . || echo '  (no FAIL line in the log; the step itself failed)')

Last $CI_LOG_LINES lines of the step's log:
$(printf '%s\n' "$log" | awk '/^##\[error\]Process completed with exit code/ {exit} {print}' | tail -n "$CI_LOG_LINES")"
  printf '%s\n' "$CI_DETAIL" > "$RUN_DIR/ci-failed.txt"
}
# gh's --log-failed lines are "job<TAB>step<TAB>timestamp text": keep the text, without the timestamp or colour.
ci_log_clean() { cut -f3- | /usr/bin/perl -pe 's/^\xEF\xBB\xBF//; s/^\d{4}-\d\d-\d\dT[\d:.]+Z ?//; s/(?:\e|\^\[)\[[0-9;]*[A-Za-z]//g'; }

# ── the alarm: the workflow's `alarm` job, from the Mac ──
alarm() {
  local why="$1" tail_text ci_text body existing title="MoleculeFinder ETL FAILED"
  ci_text=$(printf '%s\n' "$CI_DETAIL" | tilde | sed 's/```/` ` `/g' \
              | sed -E 's/(eyJ[A-Za-z0-9_-]{20,}|sb_secret_[A-Za-z0-9_-]+)/[redacted]/g')
  tail_text=$(tail -n 80 "$LOG" | tilde | sed 's/```/` ` `/g' \
                | sed -E 's/(eyJ[A-Za-z0-9_-]{20,}|sb_secret_[A-Za-z0-9_-]+)/[redacted]/g')
  body="The weekly MoleculeFinder refresh on the Mac mini did not finish with a deploy.

**What happened:** $(echo "$why" | tilde)
**Log on the Mac mini:** \`$(echo "$LOG" | tilde)\` (summary: \`$(echo "$SUMMARY" | tilde)\`)
**Week:** $WEEK (attempt $(n=$(grep -c '^attempt' "$STATE" 2>/dev/null || true); echo "${n:-0}") of at most $MAX_ATTEMPTS)
${PR_URL:+**Data PR:** $PR_URL
}${CI_DETAIL:+
**What broke on the website check (\`ci / verify\`):**

\`\`\`
$ci_text
\`\`\`
}
moleculefinder.com is still serving its last good build: the DATA is frozen, the site is not down.

Wikidata changes held this run (they ship once 7 days old): ${HELD}.
Product pages held live this run (see data/seed/products_held.json): ${PRODUCTS_HELD}.
LD50 values held this run (see data/seed/ld50_held.json): ${LD50_HELD}.

Drawings this run (the drawing guard, transform/drawing_guard.py; a STOPPED line names
each drawing that changed with nothing to explain it, and nothing was exported):

\`\`\`
${DRAWINGS_TEXT}
\`\`\`

If the data PR's check failed: re-running a failed check on the data PR
reuses the old merge and cannot pick up a fix on main; close and reopen
the PR to get a fresh check. Do not re-run a stopped refresh to make it go
green: read the log, find the input that moved, fix it on a branch.

The Mac retries every two hours on Monday (06:10 to 18:10 Eastern) and at 03:10 on the
following days until a run succeeds; the next green run closes this issue.

<details><summary>Last 80 log lines</summary>

\`\`\`
$tail_text
\`\`\`
</details>"
  printf '%s\n' "$body" > "$RUN_DIR/alarm.md"
  if [ "$DRY" = 1 ]; then
    say "ALARM (dry run: not filed). It would dispatch mac-alarm.yml, which opens (or comments on) the open '$ETL_GH' issue labelled refresh-failure as github-actions[bot], titled \"$title\", and fails so GitHub emails; this is the text:"
    echo "----- alarm text -----"; cat "$RUN_DIR/alarm.md"; echo "----- end of alarm text -----"
    return
  fi
  osascript -e "display notification \"$(echo "$why" | cut -c1-180 | tr '"' "'")\" with title \"MoleculeFinder refresh FAILED\"" 2>/dev/null || true
  # The relay first: an issue the Mac opened itself would be Garrett's own, and GitHub emails nobody about those.
  if jq -n --arg title "$title" --rawfile body "$RUN_DIR/alarm.md" '{title: $title, body: ($body | .[0:60000])}' \
       | (cd "$STATE_DIR" && tgh workflow run mac-alarm.yml --repo "$ETL_GH" --ref main --json) >/dev/null 2>&1; then
    say "alarm: dispatched mac-alarm.yml (GitHub opens or comments on the refresh-failure issue and emails)"
    return
  fi
  say "WARNING: could not dispatch mac-alarm.yml; filing the issue from the Mac instead (GitHub sends no email for it)"
  existing=$(cd "$STATE_DIR" && tgh issue list --repo "$ETL_GH" --label refresh-failure --state open --limit 1 \
               --json number --jq '.[0].number // empty' 2>/dev/null || true)
  if [ -n "$existing" ]; then
    (cd "$STATE_DIR" && tgh issue comment "$existing" --repo "$ETL_GH" --body-file "$RUN_DIR/alarm.md") \
      && say "alarm: commented on issue #$existing" || say "WARNING: the alarm comment could not be posted"
  else
    (cd "$STATE_DIR" && tgh label create refresh-failure --repo "$ETL_GH" --color B60205 \
       --description "Automated data refresh failed" >/dev/null 2>&1) || true
    (cd "$STATE_DIR" && tgh issue create --repo "$ETL_GH" --label refresh-failure --title "$title" \
       --body-file "$RUN_DIR/alarm.md") && say "alarm: opened an issue" || say "WARNING: the alarm issue could not be opened"
  fi
}

# ── the failed-run heartbeat: once a week, the timestamp only (etl.yml "heartbeat after a failed run") ──
# This repo is PUBLIC: GitHub switches off a public repo's scheduled workflows after 60 days with no repository
# activity, and the network watchdog lives here. A failing refresh still pushes one commit a week. It counts as
# activity but not as a success (watchdog: subject "etl: run failed").
failed_heartbeat() {
  [ "$DRY" = 1 ] && { say "dry run: would push the failed-run heartbeat (data/LAST_CHECK, \"etl: run failed $(date -u +%F) [heartbeat]\") if this is the week's first failure"; return; }
  grep -q '^heartbeat' "$STATE" 2>/dev/null && return
  [ -d "$WORK/etl/.git" ] || [ -f "$WORK/etl/.git" ] || return
  ( cd "$WORK/etl" \
    && /usr/bin/perl -e 'alarm shift; exec @ARGV' "$NET_SECONDS" git fetch --quiet origin main \
    && git reset --quiet --hard origin/main \
    && date -u +%FT%TZ > data/LAST_CHECK && git add data/LAST_CHECK \
    && git commit --quiet -m "etl: run failed $(date -u +%F) [heartbeat]" -m "Mac mini weekly refresh (scripts/mac/weekly-refresh.sh)." \
    && /usr/bin/perl -e 'alarm shift; exec @ARGV' "$NET_SECONDS" git push --quiet origin HEAD:main ) \
    && { echo "heartbeat $(date -u +%FT%TZ)" >> "$STATE"; say "pushed the failed-run heartbeat"; } \
    || say "WARNING: could not push the failed-run heartbeat, so this week did not reset the 60-day clock"
}

remove_worktree() {   # remove_worktree <repo> <path>
  local repo="$1" wt="$2" n=0
  if [ -e "$wt" ] || [ -L "$wt" ]; then
    git -C "$repo" worktree remove --force "$wt" 2>/dev/null
    while [ -e "$wt" ] && [ "$n" -lt 5 ]; do n=$((n + 1)); rm -rf "$wt" 2>/dev/null; sleep 1; done
  fi
  git -C "$repo" worktree prune 2>/dev/null
  [ ! -e "$wt" ]
}

tidy() {
  remove_worktree "$ETL_REPO" "$WORK/etl" || say "WARNING: could not remove $WORK/etl; delete it by hand"
  remove_worktree "$WEB_REPO" "$WORK/web" || say "WARNING: could not remove $WORK/web; delete it by hand"
  rm -f "$WORK/.DS_Store"; rmdir "$WORK" 2>/dev/null     # Finder drops a .DS_Store into an emptied folder
  [ -n "$SCRATCH_CACHE" ] && rm -rf "$SCRATCH_CACHE"
  rm -rf "$MAIN_INPUTS.new"
  rm -rf "$RUN_DIR"
  # old logs and summaries; old weeks' state files
  find "$LOG_DIR" -type f \( -name 'weekly-*.log' -o -name 'summary-*.md' \) -mtime +"$LOG_KEEP_DAYS" -delete 2>/dev/null
  find "$STATE_DIR" -maxdepth 1 -type f -name 'week-*' -mtime +"$LOG_KEEP_DAYS" -delete 2>/dev/null
  say "disk: $(free_gib) GiB free after the run (it started with ${DISK_START:-?} GiB)"
}

finish() {
  local rc=$?
  trap - EXIT TERM INT HUP
  [ -n "$WATCHDOG" ] && kill "$WATCHDOG" 2>/dev/null
  if [ -n "$CAUSE" ]; then rc=124; fi
  {
    echo ""
    echo "## Run"
    echo ""
    echo "- week $WEEK, ref $REF$([ "$DRY" = 1 ] && echo ', DRY RUN'), log \`$(echo "$LOG" | tilde)\`"
    echo "- Wikidata changes held this run (shipped once 7 days old): $HELD; product pages held live: $PRODUCTS_HELD; LD50 values held: $LD50_HELD"
    [ -n "$SNAP_SHA" ] && echo "- ETL commit: $SNAP_SHA"
    [ -n "$PR_URL" ] && echo "- data PR: $PR_URL"
    [ -n "$MERGE_SHA" ] && echo "- merged as $MERGE_SHA$([ "$PUBLISHED" = 1 ] && echo ', live')"
    echo "- ended: $([ "$rc" = 0 ] && echo "OK: $STEP" || echo "exit $rc at: $STEP")"
  } >> "$SUMMARY"
  if [ "$rc" = 0 ]; then
    [ "$DRY" = 0 ] && [ "$SEED_ONLY" = 0 ] && echo "success $(date -u +%FT%TZ) $STEP" >> "$STATE"
    say "DONE: $STEP"
  else
    local what="FAILED (exit $rc) at: $STEP"
    [ "$CAUSE" = "timed out" ] && what="TIMED OUT after $((WATCHDOG_SECONDS / 3600)) h, during: $STEP"
    [ "$CAUSE" = "cancelled" ] && what="CANCELLED (stopped or shut down), during: $STEP"
    say "$what"
    [ "$SEED_ONLY" = 0 ] && failed_heartbeat
    alarm "$what"
  fi
  say "summary: $SUMMARY"
  tidy
  rm -rf "$LOCK"
  exit "$rc"
}
on_signal() {
  trap '' TERM INT HUP
  if [ -e "$LOCK/timed-out" ]; then CAUSE="timed out"; else CAUSE="${CAUSE:-cancelled}"; fi
  kill -TERM -- -$$ 2>/dev/null
  exit 124
}
trap finish EXIT
trap on_signal TERM INT HUP

fail() { say "ERROR: $*"; STEP="$STEP ($*)"; exit 1; }
# run "<step>" cmd...: the command runs in the background and is waited for, so a stop is handled at once
run() {
  STEP="$1"; shift; say "── $STEP"
  "$@" & local pid=$!
  wait "$pid"; local rc=$?
  [ "$rc" = 0 ] || fail "exit $rc"
}
# step_aside "<why>": not a failure, not a try, no alarm; the next scheduled start tries again
step_aside() {
  say "stepping aside: $1. Not a failure and not a try; the next scheduled start tries again."
  [ "$DRY" = 0 ] && [ -f "$STATE" ] && [ "${ATTEMPT_RECORDED:-0}" = 1 ] && sed -i '' '$d' "$STATE"
  STEP="stepped aside: $1"; CAUSE=""
  trap - EXIT TERM INT HUP
  [ -n "$WATCHDOG" ] && kill "$WATCHDOG" 2>/dev/null
  tidy; rm -rf "$LOCK"; say "DONE: $STEP"; exit 0
}

case "$(readlink /etc/localtime 2>/dev/null)" in
  */America/New_York) ;;
  *) say "WARNING: this Mac's time zone is $(readlink /etc/localtime 2>/dev/null || echo unknown), not America/New_York: launchd's 03:10 is not 03:10 Eastern" ;;
esac
say "MoleculeFinder weekly refresh: ISO week $WEEK (UTC), ref $REF$([ "$DRY" = 1 ] && echo ', DRY RUN: no load, no commit, no push, no PR, no merge')$([ "$FORCE" = 1 ] && echo ', forced')$([ "$SEED_ONLY" = 1 ] && echo ', seeding the inputs cache only')"
say "host $(hostname -s), pid $$, macOS $(sw_vers -productVersion), $(uname -m)"
caffeinate -is -w $$ & disown

# ── the environment, all of it, before anything runs ──
STEP="checking the environment"
DISK_START=$(free_gib)
say "disk: $DISK_START GiB free on / (floor $DISK_FLOOR_GIB GiB)"
[ "${DISK_START:-0}" -ge "$DISK_FLOOR_GIB" ] || fail "only $DISK_START GiB free on /, under the $DISK_FLOOR_GIB GiB floor: refusing to build (free space, then run it by hand with --force)"
for tool in /opt/homebrew/bin/git /opt/homebrew/bin/gh /opt/homebrew/bin/uv /usr/bin/jq /usr/bin/perl /usr/bin/curl "$PY_BASE"; do
  [ -x "$tool" ] || fail "missing $tool"
done
say "tools: $(git --version), $(/opt/homebrew/bin/gh --version | head -1), $(/opt/homebrew/bin/uv --version), $("$PY_BASE" --version), jq $(jq --version)"
case "$("$PY_BASE" --version 2>&1)" in "Python 3.12."*) ;; *) fail "$PY_BASE is not Python 3.12" ;; esac
[ -d "$ETL_REPO/.git" ] || fail "no ETL repository at $ETL_REPO"
[ -d "$WEB_REPO/.git" ] || fail "no web repository at $WEB_REPO"
if [ "$DRY" = 0 ] && [ "$SEED_ONLY" = 0 ]; then
  "$PY_BASE" -c 'import dotenv' 2>/dev/null || true   # the venv has it; checked again with the venv below
fi
# Nothing from a session's shell leaks in: no MoleculeFinder override and no database key reaches the build
# except the two this script hands it. (MFETL_DRAWING_SEEDS_CHANGED, MFETL_ALLOW_REGRESSION and
# MFETL_ALLOW_STALE_WIKIDATA are the guards' release valves: the weekly run never sets them.)
for v in $(compgen -e); do
  case "$v" in MFETL_*|SUPABASE_*|GITHUB_*) unset "$v" ;; esac
done

# GitHub, as the job will use it: gh's own login, read without a prompt
STEP="GitHub login"
tgh auth status --hostname github.com >/dev/null 2>&1 || fail "gh is not logged in to github.com (run: gh auth login)"
say "gh: logged in as $(cd "$STATE_DIR" && tgh api user --jq .login 2>/dev/null || echo '?')"

# ── the network: wait for it rather than spend a try on an outage ──
STEP="waiting for the network"
deadline=$(( $(date +%s) + NETWORK_WAIT_SECONDS ))
until curl -fsS --max-time 20 -o /dev/null https://api.github.com/zen \
   && curl -fsS --max-time 30 -o /dev/null "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/2519/property/MolecularFormula/TXT" \
   && curl -fsS --max-time 30 -o /dev/null "https://query.wikidata.org/sparql?query=ASK%7B%7D&format=json"; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    step_aside "the network (GitHub, PubChem or Wikidata) was still unreachable after $((NETWORK_WAIT_SECONDS / 60)) min"
  fi
  say "network not reachable (GitHub, PubChem or Wikidata); retrying in 5 min"
  sleep 300 & wait $!
done

# ── never overlap another MoleculeFinder build, here or on GitHub ──
STEP="checking for another build"
others=$(pgrep -f 'moleculefinder_etl\.cli|bin/mfetl ' 2>/dev/null | while read -r p; do
           [ "$(ps -o pgid= -p "$p" 2>/dev/null | tr -d ' ')" = "$$" ] || echo "$p"; done | tr '\n' ' ')
[ -z "${others// /}" ] || step_aside "another MoleculeFinder build is running on this Mac (pid ${others% })"
gh_running=$(cd "$STATE_DIR" && tgh run list --repo "$ETL_GH" --workflow etl.yml --limit 10 \
               --json status,databaseId --jq '[.[] | select(.status != "completed")] | length' 2>/dev/null || echo "?")
[ "$gh_running" = "?" ] && fail "could not ask GitHub whether the backup workflow etl.yml is running"
[ "$gh_running" = 0 ] || step_aside "a GitHub run of etl.yml (the manual backup) is in progress"

[ "$DRY" = 0 ] && [ "$SEED_ONLY" = 0 ] && { echo "attempt $(date -u +%FT%TZ) $LOG" >> "$STATE"; ATTEMPT_RECORDED=1; }

# ── the time limit: a run that hangs is stopped, and alarmed as a timeout ──
( sleep "$WATCHDOG_SECONDS"; touch "$LOCK/timed-out"; kill -TERM $$ ) 2>/dev/null &
WATCHDOG=$!
disown "$WATCHDOG"

# ── a clean checkout of what is published ──
netgit "fetch the ETL" -C "$ETL_REPO" fetch --quiet origin main
remove_worktree "$ETL_REPO" "$WORK/etl" || fail "an earlier run's checkout at $WORK/etl could not be removed"
mkdir -p "$WORK"
run "checkout of $REF (ETL)" git -C "$ETL_REPO" worktree add --quiet --detach "$WORK/etl" "$REF"
cd "$WORK/etl" || fail "no checkout"
START_SHA=$(git rev-parse HEAD)
say "$REF is ${START_SHA:0:7}: $(git log -1 --format=%s | cut -c1-140)"
[ -z "$(git status --porcelain)" ] || fail "the fresh checkout is not clean"
if [ "$DRY" = 0 ]; then
  [ "$START_SHA" = "$(git rev-parse origin/main)" ] || fail "the checkout is not origin/main"
fi
touch "$RUN_DIR/started"                                  # a stage that rewrites a file is newer than this

# ── the Python environment, pinned: uv.lock exactly, Python 3.12 ──
export UV_PROJECT_ENVIRONMENT="$VENV"
run "python environment (uv.lock, frozen)" uv sync --quiet --frozen --no-dev --no-install-project --python "$PY_BASE"
PY="$VENV/bin/python"
say "python: $("$PY" --version 2>&1); $("$PY" -c 'import rdkit, numpy, pyarrow; print(f"rdkit {rdkit.__version__}, numpy {numpy.__version__}, pyarrow {pyarrow.__version__}")')"
case "$("$PY" --version 2>&1)" in "Python 3.12."*) ;; *) fail "the job's environment is not Python 3.12" ;; esac
if [ "$DRY" = 0 ] && [ "$SEED_ONLY" = 0 ]; then
  run "the real database keys (present; values not shown)" "$PY" scripts/mac/with_keys.py "$ENV_FILE" --check
fi

# ── the inputs cache: the canonical one, or a throwaway copy of it for a dry run ──
seed_cache() {   # seed_cache <dir>: the inputs main was built from (GitHub's artifact, or the Mac's cache)
  STEP="seeding the inputs cache"; say "── $STEP into $(echo "$1" | tilde)"
  MFETL_RAW_CACHE="$1" "$PY" -m moleculefinder_etl.cli sync-inputs & wait $!
}
if [ "$SEED_ONLY" = 1 ]; then
  [ -d "$CACHE" ] && fail "the job's cache already exists at $CACHE; move it aside first if you mean to reseed it"
  seed_cache "$CACHE" || fail "could not fetch the inputs main was built from"
  STEP="seeded the job's inputs cache from main's inputs ($(jq -r .fingerprint data/seed/inputs.json | cut -c1-16))"
  exit 0
fi
if [ "$DRY" = 1 ]; then
  if [ -n "${MF_DRY_CACHE:-}" ]; then
    RUN_CACHE="$MF_DRY_CACHE"                              # a proof session's own reusable scratch cache
    [ -d "$RUN_CACHE" ] || { seed_cache "$RUN_CACHE" || fail "could not seed the dry-run cache"; }
  else
    SCRATCH_CACHE="$STATE_DIR/dry-run-cache-$STAMP"; RUN_CACHE="$SCRATCH_CACHE"
    if [ -d "$CACHE" ]; then
      run "a throwaway copy of the inputs cache (copy-on-write)" cp -cR "$CACHE" "$SCRATCH_CACHE"
    else
      seed_cache "$SCRATCH_CACHE" || fail "could not seed the dry-run cache"
    fi
  fi
elif [ ! -d "$CACHE" ]; then
  say "the job's inputs cache is missing: seeding it from the inputs main was built from"
  seed_cache "$CACHE" || { say "WARNING: could not seed it; starting from an EMPTY cache: every input is fetched fresh (slower, and more molecule files move; every guard holds)"; mkdir -p "$CACHE"; }
fi
say "inputs cache: $(echo "$RUN_CACHE" | tilde) ($(du -sh "$RUN_CACHE" 2>/dev/null | cut -f1))"

# ── the refresh itself: `mfetl all --target 10000`, every guard inside it ──
DRAWINGS_JSON="$RUN_DIR/drawings.json"
ETL_ENV=(env MFETL_INPUTS=refresh MFETL_WEEKLY=1 MFETL_RAW_CACHE="$RUN_CACHE" MFETL_STEP_SUMMARY="$SUMMARY"
         MFETL_DRAWINGS_REPORT="$DRAWINGS_JSON" MFETL_GIT_SHA="$START_SHA" PYTHONUNBUFFERED=1)
echo "# MoleculeFinder weekly refresh, $(date '+%F %H:%M') ET (ISO week $WEEK)" > "$SUMMARY"
if [ "$DRY" = 1 ]; then
  say "dry run: the database keys are BLANKED, so the load stage logs that it skipped; a real run loads Supabase here with the real keys"
  run "mfetl all --target 10000 (refresh)" "${ETL_ENV[@]}" SUPABASE_URL= SUPABASE_SERVICE_KEY= \
      "$PY" -m moleculefinder_etl.cli all --target 10000
else
  run "mfetl all --target 10000 (refresh, with the real keys)" "$PY" scripts/mac/with_keys.py "$ENV_FILE" -- \
      "${ETL_ENV[@]}" "$PY" -m moleculefinder_etl.cli all --target 10000
fi
STEP="after the build"

# counts for the summaries and the alarm (etl.yml: "Count held ..." and "Count drawings")
count_held() { [ -n "$(find "$1" -newer "$RUN_DIR/started" 2>/dev/null)" ] && jq length "$1" || echo unknown; }
read_counts() {
  HELD=$(count_held data/seed/wikidata_held.json); PRODUCTS_HELD=$(count_held data/seed/products_held.json)
  LD50_HELD=$(count_held data/seed/ld50_held.json)
  [ -s "$DRAWINGS_JSON" ] && DRAWINGS_TEXT=$(jq -r .text "$DRAWINGS_JSON")
}
read_counts
say "Wikidata changes held this run: $HELD; product pages held: $PRODUCTS_HELD; LD50 values held: $LD50_HELD"
say "Drawings this run:"; echo "$DRAWINGS_TEXT"

# ── commit the snapshot to the ETL's main (etl.yml "commit snapshot", with the heartbeat) ──
STEP="commit the snapshot"; say "── $STEP"
TODAY=$(date -u +%F)
git add data/snapshots data/seed || fail "git add"
if git diff --cached --quiet; then
  NO_CHANGE=1; MSG="etl: no changes $TODAY [heartbeat]"
else
  NO_CHANGE=0; MSG="etl: refresh $TODAY"
  CHANGED=$(git diff --cached --name-only --diff-filter=M -- data/snapshots/molecules | wc -l | tr -d ' ')
  ADDED=$(git diff --cached --name-only --diff-filter=A -- data/snapshots/molecules | wc -l | tr -d ' ')
  say "molecule files: $CHANGED changed, $ADDED added; $(git diff --cached --name-only | wc -l | tr -d ' ') files in all"
fi
# data/LAST_CHECK is stamped by every run that gets here: the watchdog reads the commits that touch it
date -u +%FT%TZ > data/LAST_CHECK && git add data/LAST_CHECK
if [ "$DRY" = 1 ]; then
  say "dry run: would commit \"$MSG\" as $(git config user.name) <$(git config user.email)> and push it to the ETL's main, then keep main's inputs ($(jq -r .fingerprint data/seed/inputs.json | cut -c1-16), built_on $(jq -r '.built_on // "github"' data/seed/inputs.json)) at $(echo "$MAIN_INPUTS" | tilde)"
  git reset --quiet
  SNAP_SHA="(dry run: not committed)"
else
  git commit --quiet -m "$MSG" -m "Scheduled weekly refresh on the Mac mini (scripts/mac/weekly-refresh.sh), built from ${START_SHA:0:7}." \
    || fail "git commit"
  SNAP_SHA=$(git rev-parse HEAD)
  STEP="push to the ETL's main"; say "── $STEP"
  /usr/bin/perl -e 'alarm shift; exec @ARGV' "$NET_SECONDS" git push --quiet origin HEAD:main & wait $!
  [ $? = 0 ] || fail "the push to the ETL's main was refused or timed out (did main move during the run? This run built ${START_SHA:0:7}; the next start rebuilds from the new main, nothing was published)"
  say "pushed ${SNAP_SHA:0:7} to the ETL's main"
  # The inputs main now names, kept as they are (the artifact GitHub used to upload): `mfetl sync-inputs` copies
  # from here. A copy-on-write clone, so it costs only what later runs change in the working cache.
  rm -rf "$MAIN_INPUTS.new"
  if cp -cR "$RUN_CACHE" "$MAIN_INPUTS.new"; then
    rm -rf "$MAIN_INPUTS" && mv "$MAIN_INPUTS.new" "$MAIN_INPUTS" \
      && say "inputs: main's inputs ($(jq -r .fingerprint data/seed/inputs.json | cut -c1-16)) kept at $(echo "$MAIN_INPUTS" | tilde)"
  else
    say "WARNING: could not keep a copy of main's inputs; sync-inputs will refuse until the next run"
  fi
fi
[ "$NO_CHANGE" = 1 ] && say "no data changes: the heartbeat commit keeps this public repo's crons alive"

# ── the web: copy the snapshot WHOLE, one data PR, ci / verify on that exact commit, squash-merge ──
netgit "fetch the web repo" -C "$WEB_REPO" fetch --quiet origin main
remove_worktree "$WEB_REPO" "$WORK/web" || fail "an earlier run's web checkout at $WORK/web could not be removed"
run "checkout of the web's origin/main" git -C "$WEB_REPO" worktree add --quiet --detach "$WORK/web" origin/main
STEP="find the open data PR"
BRANCH=$(cd "$STATE_DIR" && tgh pr list --repo "$WEB_GH" --state open --limit 50 --json number,headRefName --jq \
  '.[] | select(.headRefName | startswith("data/snapshot-")) | "\(.number) \(.headRefName)"' | sort -n | head -1 | cut -d' ' -f2)
[ $? = 0 ] || fail "could not list the web repo's pull requests"
cd "$WORK/web" || fail "no web checkout"
if [ -n "$BRANCH" ]; then
  say "reusing the open data PR on $BRANCH"
  netgit "fetch $BRANCH" fetch --quiet --no-tags origin "+refs/heads/${BRANCH}:refs/remotes/origin/${BRANCH}"
else
  BRANCH="data/snapshot-$TODAY"
fi
STEP="copy the snapshot into the web"
rm -rf data/snapshots && cp -R "$WORK/etl/data/snapshots" data/snapshots || fail "copy"
git add data/snapshots || fail "git add"
if git diff --cached --quiet; then
  STEP=$([ "$NO_CHANGE" = 1 ] && echo "nothing changed this week: the web's snapshot is already identical, no PR" \
                              || echo "the web's snapshot is already identical: no PR needed")
  say "$STEP"
  WEB_SAME=1; STEP_WEB="$STEP"
else
  WEB_SAME=0
  W_CHANGED=$(git diff --cached --name-only --diff-filter=M -- data/snapshots/molecules | wc -l | tr -d ' ')
  W_ADDED=$(git diff --cached --name-only --diff-filter=A -- data/snapshots/molecules | wc -l | tr -d ' ')
  W_REMOVED=$(git diff --cached --name-only --diff-filter=D -- data/snapshots/molecules | wc -l | tr -d ' ')
  say "against the web's main: molecule files $W_CHANGED changed, $W_ADDED added, $W_REMOVED removed; $(git diff --cached --name-only | wc -l | tr -d ' ') files in all"
fi

if [ "$WEB_SAME" = 0 ]; then
  BODY="Automated snapshot sync from the Mac mini's weekly refresh (moleculefinder-etl \`${SNAP_SHA:0:7}\`, scripts/mac/weekly-refresh.sh).

| | molecule files |
|---|---|
| changed | ${W_CHANGED} |
| added | ${W_ADDED} |
| removed | ${W_REMOVED} |

(Measured against the web repo's committed copy, which may have been several runs behind.)

Data only: nothing outside \`data/snapshots/\` is touched. CI runs
\`verify-snapshot\` on this branch. **This PR squash-merges itself when that
check goes green, and merging is what deploys the site.** If the check fails
it stays open and the refresh raises its alarm instead."
  if [ "$DRY" = 1 ]; then
    say "dry run: would commit \"data: weekly snapshot $TODAY\" and push it to $BRANCH, open or update the data PR, close any other data PR as superseded, wait for 'ci / verify' on that exact commit (up to $((CI_FINISH_SECONDS / 60)) min), squash-merge it with --match-head-commit, then wait up to $((DEPLOY_WAIT_SECONDS / 60)) min for Vercel's production deployment of the merge commit"
    git reset --quiet
    STEP="DRY RUN complete: the build passed every guard; nothing was loaded, committed, pushed, opened or merged"
    exit 0
  fi
  STEP="commit and push the data branch"; say "── $STEP"
  git commit --quiet -m "data: weekly snapshot $TODAY" || fail "git commit"
  SHA=$(git rev-parse HEAD)
  if git rev-parse --verify -q "refs/remotes/origin/${BRANCH}" >/dev/null; then
    netgit "push $BRANCH" push --quiet --force-with-lease="refs/heads/${BRANCH}:refs/remotes/origin/${BRANCH}" origin "HEAD:refs/heads/${BRANCH}"
  else
    netgit "push $BRANCH" push --quiet --force origin "HEAD:refs/heads/${BRANCH}"
  fi
  STEP="open or update the data PR"; say "── $STEP"
  printf '%s\n' "$BODY" > "$RUN_DIR/pr-body.md"
  cd "$STATE_DIR" || fail "state dir"
  if ! tgh pr create --repo "$WEB_GH" --base main --head "$BRANCH" --title "data: weekly snapshot $TODAY" \
         --body-file "$RUN_DIR/pr-body.md" > "$RUN_DIR/pr-create.out" 2>&1; then
    say "gh pr create said: $(cat "$RUN_DIR/pr-create.out")"
    tgh pr edit "$BRANCH" --repo "$WEB_GH" --title "data: weekly snapshot $TODAY" --body-file "$RUN_DIR/pr-body.md" >/dev/null \
      || fail "could not open or update the data PR"
  fi
  PR=$(tgh pr view "$BRANCH" --repo "$WEB_GH" --json number --jq .number) || fail "could not read the data PR"
  PR_URL="https://github.com/$WEB_GH/pull/$PR"
  say "opened/updated PR #$PR on $BRANCH at ${SHA:0:7}"
  # superseded data PRs: tidying, never a gate
  tgh pr list --repo "$WEB_GH" --state open --limit 50 --json number,headRefName --jq \
    '.[] | select(.headRefName | startswith("data/snapshot-")) | "\(.number) \(.headRefName)"' 2>/dev/null \
  | while read -r num br; do
      [ "$num" = "$PR" ] && continue
      say "closing superseded PR #$num ($br)"
      tgh pr close "$num" --repo "$WEB_GH" --delete-branch \
        --comment "Superseded by #$PR, which carries the whole snapshot including everything in this one." >/dev/null 2>&1 \
        || tgh pr close "$num" --repo "$WEB_GH" --delete-branch >/dev/null 2>&1 \
        || say "WARNING: could not close superseded PR #$num; close it by hand"
    done

  # 'ci / verify' on THIS sha, from the Actions API (etl.yml "Wait for the web repo's verify run")
  STEP="waiting for 'ci / verify' on ${SHA:0:7}"; say "── $STEP"
  appear_by=$(( $(date +%s) + CI_APPEAR_SECONDS )); finish_by=$(( $(date +%s) + CI_FINISH_SECONDS ))
  while :; do
    now=$(date +%s)
    runs=$(tgh run list --repo "$WEB_GH" --commit "$SHA" --limit 30 --json workflowName,status,conclusion,databaseId 2>/dev/null) || runs='[]'
    [ -n "$runs" ] || runs='[]'
    one=$(echo "$runs" | jq -c '[.[] | select(.workflowName == "ci")] | sort_by(.databaseId) | last // empty')
    if [ -z "$one" ]; then
      [ "$now" -gt "$appear_by" ] && fail "no 'ci' workflow run appeared for ${SHA:0:7} within $((CI_APPEAR_SECONDS / 60)) minutes; not merging (the web's ci.yml disabled or renamed, or the Actions minutes exhausted); PR $PR_URL stays open"
      sleep 15 & wait $!; continue
    fi
    st=$(echo "$one" | jq -r .status); con=$(echo "$one" | jq -r '.conclusion // ""'); id=$(echo "$one" | jq -r .databaseId)
    if [ "$st" != "completed" ]; then
      [ "$now" -gt "$finish_by" ] && fail "ci run $id was still '$st' after $((CI_FINISH_SECONDS / 60)) minutes; not merging; PR $PR_URL stays open"
      sleep 20 & wait $!; continue
    fi
    if [ "$con" != "success" ]; then
      ci_failure_detail "$id"
      say "what broke on the website's check:"; printf '%s\n' "$CI_DETAIL"
      fail "ci run $id for ${SHA:0:7} concluded '$con' at: ${CI_FAILED_STEPS:-an unknown step}; the PR is left OPEN ($PR_URL); read the failing check, never weaken it"
    fi
    job=$(tgh run view "$id" --repo "$WEB_GH" --json jobs --jq '.jobs[] | select(.name == "verify") | .conclusion' 2>/dev/null | head -1)
    [ "$job" = "success" ] || fail "ci run $id concluded success, but its 'verify' job is '${job:-absent}': not a verified snapshot; not merging; PR $PR_URL stays open"
    say "ci run $id (verify): SUCCESS on ${SHA:0:7}"
    break
  done

  STEP="squash-merge the data PR (the deploy)"; say "── $STEP"
  # --match-head-commit: merge only the commit that was verified (a push to the branch since then refuses)
  tgh pr merge "$PR" --repo "$WEB_GH" --squash --delete-branch --match-head-commit "$SHA" >/dev/null \
    || fail "the merge of PR #$PR was refused (did the branch move after ci passed?); PR $PR_URL stays open"
  MERGE_SHA=$(tgh pr view "$PR" --repo "$WEB_GH" --json mergeCommit --jq .mergeCommit.oid) || true
  [ -n "$MERGE_SHA" ] || fail "PR #$PR reports no merge commit"
  say "merged PR #$PR as ${MERGE_SHA:0:7}; Vercel builds from that push to main"

  # ── the deploy must go live, or this run alarms (etl.yml never checked this) ──
  STEP="waiting for Vercel's production deployment of ${MERGE_SHA:0:7}"; say "── $STEP"
  deadline=$(( $(date +%s) + DEPLOY_WAIT_SECONDS ))
  while :; do
    dep=$(tgh api "repos/$WEB_GH/deployments?sha=$MERGE_SHA&environment=Production&per_page=5" --jq '.[0].id // empty' 2>/dev/null || true)
    if [ -n "$dep" ]; then
      state=$(tgh api "repos/$WEB_GH/deployments/$dep/statuses?per_page=1" --jq '.[0].state // empty' 2>/dev/null || true)
      case "$state" in
        success) break ;;
        failure|error) fail "Vercel's production deployment of ${MERGE_SHA:0:7} ended '$state': the data is merged but NOT live; check Vercel" ;;
      esac
    fi
    [ "$(date +%s)" -ge "$deadline" ] && fail "the deploy of ${MERGE_SHA:0:7} was not live after $((DEPLOY_WAIT_SECONDS / 60)) min (deployment ${dep:-not created yet}, last state '${state:-none}'): the data is merged but not published; check Vercel"
    sleep 30 & wait $!
  done
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$SITE/?mfweekly=$(date +%s)")
  [ "$code" = 200 ] || fail "the deployment succeeded but $SITE answers HTTP $code"
  PUBLISHED=1
  say "live: Vercel's production deployment of ${MERGE_SHA:0:7} succeeded and $SITE answers 200"
else
  [ "$DRY" = 1 ] && { STEP="DRY RUN complete: every guard passed; nothing to sync (the web already matches)"; exit 0; }
fi

# ── all clear: close every open refresh-failure issue (etl.yml `all-clear`) ──
STEP="all clear"
open_issues=$(cd "$STATE_DIR" && tgh issue list --repo "$ETL_GH" --label refresh-failure --state open --limit 50 --json number --jq '.[].number' 2>/dev/null) \
  || { say "WARNING: could not list refresh-failure issues, so none were closed"; open_issues=""; }
for n in $open_issues; do
  (cd "$STATE_DIR" && tgh issue close "$n" --repo "$ETL_GH" --comment "The Mac mini's weekly refresh went green ($TODAY, ISO week $WEEK): the refresh$([ "$WEB_SAME" = 0 ] && echo ", the web sync and the deploy" || echo " and the web check") all succeeded. Closing." >/dev/null) \
    && say "closed refresh-failure issue #$n" || say "WARNING: could not close refresh-failure issue #$n; close it by hand"
done
if [ "$WEB_SAME" = 1 ]; then
  STEP="${STEP_WEB:-done}: nothing to publish (week $WEEK; ETL ${SNAP_SHA:0:7})"
else
  STEP="published: ETL ${SNAP_SHA:0:7}, web PR #$PR merged as ${MERGE_SHA:0:7} and live (Wikidata held $HELD, products held $PRODUCTS_HELD, LD50s held $LD50_HELD)"
fi
exit 0
