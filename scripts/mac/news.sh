#!/bin/bash
# MoleculeFinder's "molecules in the news" job, run on Garrett's Mac mini (2026-11; the network's rule,
# network/137-Finder-Web-Standards.md section 14: "scheduled jobs run on the Mac mini, not on GitHub Actions,
# for every finder site; GitHub workflows stay only as manual backups"). It does what .github/workflows/news.yml
# did on its six-hourly cron (jobs news and alarm) and replaces that cron; news.yml keeps only its manual
# "Run workflow" button, as the backup. The step-by-step table of what the workflow did and how this does each
# part is docs/MAC-NEWS.md.
#
# STANDING AUTHORISATION (company CLAUDE.md, 2026-08-08): a SCHEDULED data refresh publishes itself. This is that
# cron. It builds nothing, deploys nothing and commits nothing: it runs `python -m moleculefinder_etl.news` from
# origin/main, which writes the names-only table molecule_news, the private audit table molecule_news_match and
# the one public feed (public-data/news/in-the-news.json), and pings IndexNow for pages new to the list.
#
# WHAT IT DOES, in order:
#   the lock -> steps aside (quietly, no alarm) while the weekly refresh runs, while a GitHub news.yml run is
#   going, or within two hours of its own last good run -> the network -> its own checkout of origin/main
#   (a shallow clone of the public repo, kept in ~/Library/Application Support/MoleculeFinder/news-checkout,
#   never the interactive checkout and never the weekly job's) -> the pinned Python 3.12, standard library only,
#   no install -> the news module with the real keys -> the alarm on a failure -> tidy.
#
# WHEN: launchd (com.137finder.moleculefinder.news, scripts/mac/com.137finder.moleculefinder.news.plist) starts it
# every day at 01:50, 07:50, 13:50 and 19:50 Eastern. No catch-up: a missed slot is covered by the next one, whose
# search looks seven days back.
#
# NO PROMPTS: its checkout is a clone of the PUBLIC repository over https with every credential helper switched
# off, so git never needs or asks for a password. The only GitHub calls that log in are gh's (the alarm relay and
# "is news.yml running?"), which never prompt (GH_PROMPT_DISABLED=1) and have a time limit.
#
# ALARM: a run that fails or times out opens (or comments on) the GitHub issue labelled `news-failure` on
# Trommsdorff/moleculefinder-etl, as news.yml's `alarm` job did ("Molecules-in-the-news run FAILED", one open
# issue at a time), and shows a Mac notification. It does so by dispatching .github/workflows/mac-alarm.yml with
# that label, which files the issue as github-actions[bot] and fails, so GitHub emails Garrett. What counts as a
# failure is news.yml's rule, unchanged: one failed search request is skipped and logged, and the run fails only
# when more than half of them fail, or a write or the IndexNow ping fails. A cancelled run (stopped, shut down)
# does not alarm, as a cancelled news.yml run did not. If the Mac is off, the GitHub watchdog sees the public
# feed go stale.
#
# KEYS: the real SUPABASE_URL and SUPABASE_SERVICE_KEY, read from the ETL's gitignored .env by
# scripts/mac/with_keys.py (python-dotenv): never sourced, never printed, never logged. A dry run blanks them.
#
# MANUAL:  scripts/mac/news.sh --dry-run            search and match only; write nothing, ping nothing, no
#                                                  state; the alarm it would file is printed, not filed
#          scripts/mac/news.sh --force              a real run now, even inside the two-hour spacing (it writes)
#          scripts/mac/news.sh --source DIR [--env-file F]   a PROOF run against the checkout DIR (never fetched):
#                                                  keys blank unless F names a test .env (never the real one);
#                                                  no state; the alarm printed, not filed
set -uo pipefail

MF="$HOME/137/moleculefinder"
ETL_REPO="$MF/moleculefinder-etl"
ENV_FILE="$ETL_REPO/.env"                                  # the real keys (gitignored); read by with_keys.py only
STATE_DIR="${MF_NEWS_STATE_DIR:-$HOME/Library/Application Support/MoleculeFinder}"
LOG_DIR="${MF_NEWS_LOG_DIR:-$HOME/Library/Logs/MoleculeFinder}"
CHECKOUT="$STATE_DIR/news-checkout"                        # this job's own clone of origin/main
VENV="$STATE_DIR/venv"                                     # the weekly job's uv.lock environment: python-dotenv
PY_BASE="/opt/homebrew/opt/python@3.12/bin/python3.12"     # news.yml used Python 3.12 too
GH="${MF_NEWS_GH:-/opt/homebrew/bin/gh}"                   # (a stand-in only in tests/test_mac_news.py)
ETL_GH="Trommsdorff/moleculefinder-etl"
ETL_URL="https://github.com/$ETL_GH.git"
WEEKLY_LOCK="$STATE_DIR/running.lock"                      # the weekly refresh's lock (weekly-refresh.sh)
LIMIT_SECONDS="${MF_NEWS_LIMIT_SECONDS:-600}"              # news.yml: timeout-minutes: 10
SPACING_SECONDS=$((2 * 3600))                              # never two good runs within two hours
NETWORK_TRIES=4                                            # 4 x 45 s: then the slot is left to the next one
NET_SECONDS=120                                            # a git fetch that takes longer has hung
GH_SECONDS=60                                              # one gh call
LOG_KEEP_DAYS=30
ALARM_LINES=40
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export HOME LANG="${LANG:-en_US.UTF-8}" LC_ALL="${LC_ALL:-en_US.UTF-8}"
export TZ="America/New_York"                               # wall-clock times in the log are Eastern ("ET")
export GIT_TERMINAL_PROMPT=0 GH_PROMPT_DISABLED=1 GH_NO_UPDATE_NOTIFIER=1 GIT_CONFIG_NOSYSTEM=1
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0="credential.helper" GIT_CONFIG_VALUE_0=""   # no keychain, ever

# Own process group, so the time limit stops every child (python, git, gh) at once.
if [ -z "${MF_NEWS_SESSION:-}" ]; then
  export MF_NEWS_SESSION=1
  exec /usr/bin/perl -MPOSIX -e 'POSIX::setsid(); exec @ARGV' /bin/bash "$0" "$@"
fi

DRY=0; FORCE=0; SOURCE=""; TEST_ENV=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --force) FORCE=1 ;;
    --source) SOURCE="${2:?--source needs a directory}"; shift ;;
    --env-file) TEST_ENV="${2:?--env-file needs a file}"; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
PROOF=$([ -n "$SOURCE" ] && echo 1 || echo 0)
[ -n "$TEST_ENV" ] && [ "$PROOF" = 0 ] && { echo "--env-file is for a --source proof run only" >&2; exit 2; }
if [ -n "$TEST_ENV" ] && [ "$(cd "$(dirname "$TEST_ENV")" 2>/dev/null && pwd -P)/$(basename "$TEST_ENV")" = "$(cd "$ETL_REPO" && pwd -P)/.env" ]; then
  echo "--env-file must be a test file, never the real keys" >&2; exit 2
fi
QUIET_ALARM=$([ "$DRY" = 1 ] || [ "$PROOF" = 1 ] && echo 1 || echo 0)   # print the alarm, file nothing

umask 077                                                  # the logs and state are Garrett's alone
mkdir -p "$STATE_DIR" "$LOG_DIR"
STAMP=$(date +%Y%m%d-%H%M%S)
KIND=$([ "$DRY" = 1 ] && echo -dry-run; [ "$PROOF" = 1 ] && echo -proof)
LOG="$LOG_DIR/news-$STAMP$KIND.log"
say() { echo "[$(date '+%F %T') ET] $*"; }
tilde() { sed "s#$HOME#~#g"; }                               # the public issue never carries the home path
tgh() { /usr/bin/perl -e 'alarm shift; exec @ARGV' "$GH_SECONDS" "$GH" "$@"; }
alive() { [ -n "$1" ] && kill -0 "$1" 2>/dev/null; }

# ── one at a time (news.yml: concurrency group molecule-news, never cancelling the one in progress) ──
LOCK="$STATE_DIR/news.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  pid=$(cat "$LOCK/pid" 2>/dev/null || true)
  if alive "$pid"; then
    echo "[$(date '+%F %T') ET] another news run is going (pid $pid): not starting a second one" >> "$LOG_DIR/news-skipped.log"
    exit 0
  fi
  rm -rf "$LOCK" && mkdir "$LOCK" || exit 0
fi
echo $$ > "$LOCK/pid"
exec >>"$LOG" 2>&1

STEP="start"; WATCHDOG=""; CAUSE=""; RUN_DIR="$STATE_DIR/news-run-$STAMP"; WORK="$CHECKOUT"
mkdir -p "$RUN_DIR"

# ── the alarm: news.yml's `alarm` job, from the Mac, relayed so it emails ──
alarm() {
  local why="$1" title="Molecules-in-the-news run FAILED" tail_text body existing
  tail_text=$(grep -v '^----- ' "$LOG" | tail -n "$ALARM_LINES" | tilde | sed 's/```/` ` `/g' \
                | sed -E 's/(eyJ[A-Za-z0-9_-]{20,}|sb_secret_[A-Za-z0-9_-]+)/[redacted]/g')
  body="The six-hourly molecules-in-the-news job on the Mac mini failed.

**What happened:** $(echo "$why" | tilde)
**Log on the Mac mini:** \`$(echo "$LOG" | tilde)\`

Nothing was deployed either way: this job only writes the molecule_news table and
its public feed, and submits IndexNow URLs. The site is unaffected; the home page keeps
the last feed and empties the block once its newest headline is a week old.

The Mac tries again at the next slot (01:50, 07:50, 13:50 and 19:50 Eastern). Close this
issue once a run goes green again.

<details><summary>Last $ALARM_LINES log lines (the job never prints a headline)</summary>

\`\`\`
$tail_text
\`\`\`
</details>"
  printf '%s\n' "$body" > "$RUN_DIR/alarm.md"
  if [ "$QUIET_ALARM" = 1 ]; then
    say "ALARM ($([ "$DRY" = 1 ] && echo 'dry run' || echo 'proof run'): not filed). It would dispatch mac-alarm.yml with label news-failure, which opens (or comments on) the open '$ETL_GH' issue labelled news-failure as github-actions[bot], titled \"$title\", and fails so GitHub emails; this is the text:"
    echo "----- alarm text -----"; cat "$RUN_DIR/alarm.md"; echo "----- end of alarm text -----"
    return
  fi
  osascript -e "display notification \"$(echo "$why" | cut -c1-180 | tr '"' "'")\" with title \"MoleculeFinder news FAILED\"" 2>/dev/null || true
  # The relay first: an issue the Mac opened itself would be Garrett's own, and GitHub emails nobody about those.
  if jq -n --arg title "$title" --rawfile body "$RUN_DIR/alarm.md" \
       '{title: $title, label: "news-failure", body: ($body | .[0:60000])}' \
       | (cd "$STATE_DIR" && tgh workflow run mac-alarm.yml --repo "$ETL_GH" --ref main --json) >/dev/null 2>&1; then
    say "alarm: dispatched mac-alarm.yml (GitHub opens or comments on the news-failure issue and emails)"
    return
  fi
  say "WARNING: could not dispatch mac-alarm.yml; filing the issue from the Mac instead (GitHub sends no email for it)"
  existing=$(cd "$STATE_DIR" && tgh issue list --repo "$ETL_GH" --label news-failure --state open --limit 1 \
               --json number --jq '.[0].number // empty' 2>/dev/null || true)
  if [ -n "$existing" ]; then
    (cd "$STATE_DIR" && tgh issue comment "$existing" --repo "$ETL_GH" --body-file "$RUN_DIR/alarm.md") \
      && say "alarm: commented on issue #$existing" || say "WARNING: the alarm comment could not be posted"
  else
    (cd "$STATE_DIR" && tgh label create news-failure --repo "$ETL_GH" --color B60205 \
       --description "Molecules-in-the-news run failed" >/dev/null 2>&1) || true
    (cd "$STATE_DIR" && tgh issue create --repo "$ETL_GH" --label news-failure --title "$title" \
       --body-file "$RUN_DIR/alarm.md") && say "alarm: opened an issue" || say "WARNING: the alarm issue could not be opened"
  fi
}

stop_watchdog() { [ -n "$WATCHDOG" ] && { pkill -P "$WATCHDOG" 2>/dev/null; kill "$WATCHDOG" 2>/dev/null; }; WATCHDOG=""; }

tidy() {
  [ "$PROOF" = 0 ] && [ -d "$CHECKOUT/.git" ] && git -C "$CHECKOUT" clean -fdxq 2>/dev/null   # nothing a run made stays
  rm -rf "$RUN_DIR"
  find "$LOG_DIR" -type f -name 'news-*.log' -mtime +"$LOG_KEEP_DAYS" -delete 2>/dev/null
}

finish() {
  local rc=$?
  trap - EXIT TERM INT HUP
  stop_watchdog
  [ "$CAUSE" = "timed out" ] && rc=124
  if [ "$rc" = 0 ]; then
    if [ "$DRY" = 0 ] && [ "$PROOF" = 0 ]; then date -u +%s > "$STATE_DIR/news-last-ok"
    else say "$([ "$DRY" = 1 ] && echo 'dry' || echo 'proof') run: would record this good run's time in news-last-ok (the two-hour spacing); not recorded"; fi
    say "DONE: $STEP"
  elif [ "$CAUSE" = "cancelled" ]; then
    say "CANCELLED (stopped or shut down) during: $STEP. No alarm (a cancelled news.yml run raised none); the next slot runs as usual."
  else
    local what="FAILED (exit $rc) at: $STEP"
    [ "$CAUSE" = "timed out" ] && what="TIMED OUT after $LIMIT_SECONDS s, during: $STEP"
    say "$what"
    alarm "$what"
  fi
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
# step_aside "<why>": not a failure, no alarm; the next slot runs as usual
step_aside() {
  say "stepping aside: $1. Not a failure; the next slot runs as usual."
  STEP="stepped aside: $1"; CAUSE=""
  trap - EXIT TERM INT HUP
  stop_watchdog
  tidy; rm -rf "$LOCK"; say "DONE: $STEP"; exit 0
}
# run "<step>" cmd...: the command runs in the background and is waited for, so a stop is handled at once
run() {
  STEP="$1"; shift; say "── $STEP"
  "$@" & local pid=$!
  wait "$pid"; local rc=$?
  [ "$rc" = 0 ] || fail "exit $rc"
}

say "MoleculeFinder news: $([ "$DRY" = 1 ] && echo 'DRY RUN: nothing written, nothing pinged' || { [ "$PROOF" = 1 ] && echo "PROOF RUN against $SOURCE" || echo 'the scheduled job'; })$([ "$FORCE" = 1 ] && echo ', forced')"
say "host $(hostname -s), pid $$, macOS $(sw_vers -productVersion), $(uname -m)"
case "$(readlink /etc/localtime 2>/dev/null)" in
  */America/New_York) ;;
  *) say "WARNING: this Mac's time zone is $(readlink /etc/localtime 2>/dev/null || echo unknown), not America/New_York: launchd's 01:50 is not 01:50 Eastern" ;;
esac

# ── the time limit: a run that hangs is stopped, and alarmed as a timeout (news.yml: timeout-minutes 10) ──
( trap - TERM; sleep "$LIMIT_SECONDS" & wait $!; touch "$LOCK/timed-out"; kill -TERM $$ ) 2>/dev/null &
WATCHDOG=$!
disown "$WATCHDOG" 2>/dev/null                             # no "Terminated" line in the log when it is stopped
caffeinate -is -w $$ & disown

# Nothing from a session's shell leaks in: no database key except the two with_keys.py hands the module, and no
# GITHUB_ variable (news.py writes a step summary when GITHUB_STEP_SUMMARY is set and keys a refusal on
# GITHUB_ACTIONS; neither belongs here).
for v in $(compgen -e); do
  case "$v" in MFETL_*|SUPABASE_*|GITHUB_*) unset "$v" ;; esac
done

# ── step aside: never alongside the weekly refresh, a GitHub run of news.yml, or a good run of its own ──
STEP="checking for the weekly refresh and other runs"
wpid=$(cat "$WEEKLY_LOCK/pid" 2>/dev/null || true)
if alive "$wpid"; then
  step_aside "the weekly refresh is running (pid $wpid)"
fi
if [ "$DRY" = 0 ] && [ "$PROOF" = 0 ] && [ "$FORCE" = 0 ] && [ -f "$STATE_DIR/news-last-ok" ]; then
  last=$(cat "$STATE_DIR/news-last-ok" 2>/dev/null || echo 0)
  if [ $(( $(date -u +%s) - ${last:-0} )) -lt "$SPACING_SECONDS" ]; then
    step_aside "the last good run ended $(( ($(date -u +%s) - last) / 60 )) min ago, inside the two-hour spacing (a start launchd held while the Mac slept, or one by hand)"
  fi
fi

# ── the network: a Mac with no connection leaves the slot to the next one (the watchdog sees a long outage) ──
STEP="waiting for the network"
n=0
until curl -sS --max-time 20 -o /dev/null https://news.google.com/ 2>/dev/null \
   && curl -sS --max-time 20 -o /dev/null https://api.github.com/zen 2>/dev/null; do
  n=$((n + 1))
  [ "$n" -ge "$NETWORK_TRIES" ] && step_aside "no connection to Google News or GitHub after $NETWORK_TRIES tries"
  say "no connection yet (Google News or GitHub); trying again in 45 s"
  sleep 45 & wait $!
done

if [ "$PROOF" = 0 ]; then                                  # read only: a dry run asks too
  gh_running=$(cd "$STATE_DIR" && tgh run list --repo "$ETL_GH" --workflow news.yml --limit 5 \
                 --json status --jq '[.[] | select(.status != "completed")] | length' 2>/dev/null || echo "?")
  if [ "$gh_running" = "?" ]; then
    say "WARNING: could not ask GitHub whether news.yml (the manual backup) is running; going ahead (two runs at once only rewrite the same rows)"
  elif [ "$gh_running" != 0 ]; then
    step_aside "a GitHub run of news.yml (the manual backup) is in progress"
  fi
fi

# ── the checkout: origin/main, clean (news.yml: actions/checkout) ──
STEP="the checkout"
if [ "$PROOF" = 1 ]; then
  WORK="$(cd "$SOURCE" 2>/dev/null && pwd -P)" || fail "no checkout at $SOURCE"
  say "proof run: the checkout is $(echo "$WORK" | tilde) (not fetched)"
else
  if [ ! -d "$CHECKOUT/.git" ]; then
    rm -rf "$CHECKOUT"
    run "clone origin/main (public, shallow)" /usr/bin/perl -e 'alarm shift; exec @ARGV' "$NET_SECONDS" \
      git clone --quiet --depth 1 --single-branch --branch main --no-tags "$ETL_URL" "$CHECKOUT"
  else
    say "── fetch origin/main"
    if ! /usr/bin/perl -e 'alarm shift; exec @ARGV' "$NET_SECONDS" \
         git -C "$CHECKOUT" fetch --quiet --depth 1 --no-tags origin "+refs/heads/main:refs/remotes/origin/main"; then
      age=$(( ( $(date -u +%s) - $(git -C "$CHECKOUT" log -1 --format=%ct origin/main 2>/dev/null || echo 0) ) / 86400 ))
      [ "$age" -le 8 ] || fail "could not fetch origin/main, and the last one fetched is $age days old"
      say "WARNING: could not fetch origin/main; running the one fetched last ($age days old)"
    fi
  fi
  run "checkout of origin/main" git -C "$CHECKOUT" reset --quiet --hard origin/main
  git -C "$CHECKOUT" clean -fdxq
  [ -z "$(git -C "$CHECKOUT" status --porcelain)" ] || fail "the checkout is not clean"
  [ "$(git -C "$CHECKOUT" rev-parse HEAD)" = "$(git -C "$CHECKOUT" rev-parse origin/main)" ] || fail "the checkout is not origin/main"
fi
say "code: $(git -C "$WORK" log -1 --format='%h %cd %s' --date=format:'%F %H:%M' 2>/dev/null | cut -c1-120)"

# ── the runtime: Python 3.12, standard library only, no install (news.yml: setup-python 3.12, no pip) ──
STEP="the runtime"
[ -x "$PY_BASE" ] || fail "missing $PY_BASE"
case "$("$PY_BASE" --version 2>&1)" in "Python 3.12."*) ;; *) fail "$PY_BASE is not Python 3.12" ;; esac
say "python: $("$PY_BASE" --version 2>&1) ($PY_BASE)"
# -E -s: no PYTHON* variable and no user site-packages reach it; -B: it writes no .pyc into the checkout.
# TZ=UTC as on GitHub's runner (the module's own times are UTC throughout; this rules out the Mac's zone).
NEWS=(env TZ=UTC "$PY_BASE" -E -s -B -m moleculefinder_etl.news)

# ── the run ──
cd "$WORK" || fail "cannot enter the checkout"
if [ "$DRY" = 1 ]; then
  say "dry run: the database keys are BLANKED"
  run "molecules in the news (--dry-run)" env SUPABASE_URL= SUPABASE_SERVICE_KEY= "${NEWS[@]}" --dry-run
elif [ "$PROOF" = 1 ]; then
  if [ -n "$TEST_ENV" ]; then
    run "molecules in the news (proof run, test keys)" "$VENV/bin/python" "$WORK/scripts/mac/with_keys.py" "$TEST_ENV" -- "${NEWS[@]}"
  else
    run "molecules in the news (proof run, keys blank)" env SUPABASE_URL= SUPABASE_SERVICE_KEY= "${NEWS[@]}"
  fi
else
  [ -x "$VENV/bin/python" ] || fail "no Python environment at $(echo "$VENV" | tilde) (the weekly job builds it from uv.lock)"
  run "the real database keys (present; values not shown)" "$VENV/bin/python" "$WORK/scripts/mac/with_keys.py" "$ENV_FILE" --check
  run "molecules in the news" "$VENV/bin/python" "$WORK/scripts/mac/with_keys.py" "$ENV_FILE" -- "${NEWS[@]}"
fi
STEP="molecules in the news: done"
