#!/bin/bash
# MoleculeFinder's drawing-truth review, run every day on Garrett's Mac mini (trust review 3, 2026-11-27; brief
# ../TRUST-2-DRAWING-TRUTH-PROMPT.md; plan ../TRUST-REVIEWS-PLAN.md). Runbook: docs/MAC-TRUST-REVIEWS.md.
#
# WHAT IT DOES: reads every drawing in the snapshot main holds, the seeds and about 70 pages of the live site, and
# writes its report to ~/137/moleculefinder/trust-reports/ (drawings-<date>.md and .json, the heartbeat
# drawings-last-run.json, and QUEUE.md for a finding class seen on two consecutive runs). That is ALL it writes. It
# commits nothing, pushes nothing, deploys nothing, loads no database key and asks PubChem nothing.
#
# IT NEVER GETS IN ANYONE'S WAY. It takes only its own lock (trust-drawings.lock); no other job reads it. It runs the
# review as `python -m moleculefinder_etl.review.drawings`, never through `mfetl`, so the weekly refresh's check for
# another build (pgrep 'moleculefinder_etl\.cli|bin/mfetl ') never sees it and never steps aside for it. If the
# weekly refresh (running.lock) or the news job (news.lock) is running, it WAITS, up to an hour, then runs; still
# busy after the hour, it records "did not run" and the reason in the heartbeat and stops. A failure raises no alarm
# and blocks nothing: the report and the heartbeat say what happened (the morning email, later, reads them).
#
# WHEN: launchd (com.137finder.moleculefinder.trust-drawings, scripts/mac/com.137finder.moleculefinder.trust-drawings.plist)
# starts it every day at 06:30 Eastern: after Monday's 03:10 refresh, clear of the 07:50 news slot.
#
# WHICH CODE AND SNAPSHOT: its own shallow clone of the public repository's main (origin/main: the code and the
# snapshot that were published), under ~/Library/Application Support/MoleculeFinder/trust-checkout, never the
# interactive checkout and never the other jobs'. Until origin/main carries the review (the days between a merge and
# Garrett's push), it runs the interactive repository's local `main` instead and says so in the log.
# PYTHON: the weekly job's environment (~/Library/Application Support/MoleculeFinder/venv, built from uv.lock).
#
# EXIT: 0 when the review ran, whatever it found; 2 when it could not run (the heartbeat says why); 3 when it did not
# run because another job held the Mac for the whole hour.
#
# MANUAL:  scripts/mac/trust-drawings.sh                  a real run now (it only reads, so a manual run is safe)
#          scripts/mac/trust-drawings.sh --no-live        skip the live site (check 9)
#          scripts/mac/trust-drawings.sh --out DIR        write the report elsewhere (a test)
set -uo pipefail

MF="$HOME/137/moleculefinder"
ETL_REPO="$MF/moleculefinder-etl"
STATE_DIR="${MF_TRUST_STATE_DIR:-$HOME/Library/Application Support/MoleculeFinder}"
LOG_DIR="${MF_TRUST_LOG_DIR:-$HOME/Library/Logs/MoleculeFinder}"
OUT="${MF_TRUST_OUT:-$MF/trust-reports}"
CHECKOUT="$STATE_DIR/trust-checkout"                       # this job's own clone of origin/main
VENV="$STATE_DIR/venv"                                     # the weekly job's uv.lock environment (rdkit, yaml)
ETL_URL="https://github.com/Trommsdorff/moleculefinder-etl.git"
LOCK="$STATE_DIR/trust-drawings.lock"                      # this job's alone
WEEKLY_LOCK="$STATE_DIR/running.lock"                      # weekly-refresh.sh
NEWS_LOCK="$STATE_DIR/news.lock"                           # news.sh
WAIT_SECONDS="${MF_TRUST_WAIT_SECONDS:-3600}"              # how long it waits for the other jobs
POLL_SECONDS="${MF_TRUST_POLL_SECONDS:-60}"
LIMIT_SECONDS=1800                                         # the review itself: about a minute; stopped at 30
NET_SECONDS=120
LOG_KEEP_DAYS=30
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export HOME LANG="${LANG:-en_US.UTF-8}" LC_ALL="${LC_ALL:-en_US.UTF-8}"
export TZ="America/New_York"                               # the report's date and the log's times are Eastern
export GIT_TERMINAL_PROMPT=0 GIT_CONFIG_NOSYSTEM=1
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0="credential.helper" GIT_CONFIG_VALUE_0=""   # public repo: no keychain

LIVE=(); while [ $# -gt 0 ]; do
  case "$1" in
    --no-live) LIVE=(--no-live) ;;
    --out) OUT="${2:?--out needs a folder}"; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
  shift
done

umask 022
mkdir -p "$STATE_DIR" "$LOG_DIR" "$OUT"
STAMP=$(date +%Y%m%d-%H%M%S)
LOG="$LOG_DIR/trust-drawings-$STAMP.log"
say() { echo "[$(date '+%F %T') ET] $*"; }
alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }
tilde() { sed "s#$HOME#~#g"; }
# heartbeat "<state>" "<reason>" <exit>: only when the review itself could not write one
heartbeat() {
  /usr/bin/perl -MPOSIX -e '
    my ($state, $why, $rc, $f) = @ARGV; $why =~ s/(["\\])/\\$1/g; $why =~ s/[\r\n]+/ /g;
    my $t = POSIX::strftime("%Y-%m-%dT%H:%M:%S%z", localtime); $t =~ s/(\d\d)$/:$1/;
    open(my $h, ">", $f) or exit 1;
    my $v = uc($state) . ": $why";
    print $h "{\n  \"time\": \"$t\",\n  \"state\": \"$state\",\n  \"verdict\": \"$v\",\n  \"exit\": $rc,\n  \"reason\": \"$why\"\n}\n";
  ' "$1" "$2" "$3" "$OUT/drawings-last-run.json"
}

# one at a time (its own lock; nobody else reads it)
if ! mkdir "$LOCK" 2>/dev/null; then
  pid=$(cat "$LOCK/pid" 2>/dev/null || true)
  if alive "$pid"; then echo "[$(date '+%F %T') ET] a review is already running (pid $pid)" >> "$LOG_DIR/trust-drawings-skipped.log"; exit 0; fi
  rm -rf "$LOCK" && mkdir "$LOCK" || exit 0
fi
echo $$ > "$LOCK/pid"
exec >>"$LOG" 2>&1
STATE="could not run"; REASON="it stopped before the review ran"; RC=2; RAN=0
finish() {
  local rc=$?
  trap - EXIT TERM INT HUP
  [ "$RAN" = 1 ] || { heartbeat "$STATE" "$REASON" "$RC"; rc=$RC; }
  find "$LOG_DIR" -type f -name 'trust-drawings-*.log' -mtime +"$LOG_KEEP_DAYS" -delete 2>/dev/null
  rm -rf "$LOCK"
  say "DONE: exit $rc"
  exit "$rc"
}
trap finish EXIT
trap 'REASON="stopped by a signal"; exit 2' TERM INT HUP
fail() { REASON="$*"; say "COULD NOT RUN: $*"; exit 2; }

say "MoleculeFinder drawing-truth review (trust review 3): host $(hostname -s), pid $$"
for v in $(compgen -e); do case "$v" in MFETL_*|SUPABASE_*|GITHUB_*) unset "$v" ;; esac; done

# ── wait for the weekly refresh and the news job (never alongside either; up to an hour) ──
waited=0
while :; do
  busy=""
  wpid=$(cat "$WEEKLY_LOCK/pid" 2>/dev/null || true); alive "$wpid" && busy="the weekly refresh (pid $wpid)"
  npid=$(cat "$NEWS_LOCK/pid" 2>/dev/null || true); alive "$npid" && busy="${busy:+$busy and }the news job (pid $npid)"
  [ -z "$busy" ] && break
  if [ "$waited" -ge "$WAIT_SECONDS" ]; then
    STATE="did not run"; RC=3
    REASON="$busy still running after $((WAIT_SECONDS / 60)) min of waiting; the next start (06:30 tomorrow) runs it"
    say "DID NOT RUN: $REASON"; exit 3
  fi
  [ "$waited" = 0 ] && say "waiting: $busy is running"
  sleep "$POLL_SECONDS" & wait $!
  waited=$((waited + POLL_SECONDS))
done
[ "$waited" -gt 0 ] && say "waited $((waited / 60)) min for the other jobs"

# ── the code and the snapshot: origin/main (its own clone); local main until origin/main carries the review ──
if [ ! -d "$CHECKOUT/.git" ]; then
  rm -rf "$CHECKOUT"
  say "── clone origin/main (public, shallow)"
  /usr/bin/perl -e 'alarm shift; exec @ARGV' "$NET_SECONDS" \
    git clone --quiet --depth 1 --single-branch --branch main --no-tags "$ETL_URL" "$CHECKOUT" \
    || fail "could not clone $ETL_URL"
else
  say "── fetch origin/main"
  /usr/bin/perl -e 'alarm shift; exec @ARGV' "$NET_SECONDS" \
    git -C "$CHECKOUT" fetch --quiet --depth 1 --no-tags origin "+refs/heads/main:refs/remotes/origin/main" \
    || say "WARNING: could not fetch origin/main; running the one fetched last"
fi
REF="origin/main"
if ! git -C "$CHECKOUT" cat-file -e "origin/main:moleculefinder_etl/review/drawings.py" 2>/dev/null; then
  git -C "$CHECKOUT" fetch --quiet --depth 1 --no-tags "$ETL_REPO" "+refs/heads/main:refs/remotes/local/main" \
    || fail "origin/main has no review yet and the local repository's main could not be read"
  REF="local/main"
  say "origin/main does not carry the review yet (not pushed): running the interactive repository's local main"
fi
git -C "$CHECKOUT" checkout --quiet --force --detach "$REF" || fail "could not check out $REF"
git -C "$CHECKOUT" clean -fdxq
[ -z "$(git -C "$CHECKOUT" status --porcelain)" ] || fail "the checkout is not clean"
say "code and snapshot: $REF $(git -C "$CHECKOUT" log -1 --format='%h %cd %s' --date=format:'%F %H:%M' | cut -c1-110)"

# ── the review (read only; no database key; not through mfetl) ──
[ -x "$VENV/bin/python" ] || fail "no Python environment at $(echo "$VENV" | tilde) (the weekly job builds it from uv.lock)"
cd "$CHECKOUT" || fail "cannot enter the checkout"
say "── the review: python -m moleculefinder_etl.review.drawings ${LIVE[*]:-} --out $(echo "$OUT" | tilde)"
env SUPABASE_URL= SUPABASE_SERVICE_KEY= SUPABASE_DB_URL= PYTHONDONTWRITEBYTECODE=1 \
  /usr/bin/perl -e 'alarm shift; exec @ARGV' "$LIMIT_SECONDS" \
  "$VENV/bin/python" -m moleculefinder_etl.review.drawings ${LIVE[@]+"${LIVE[@]}"} --out "$OUT" &
pid=$!; wait "$pid"; rc=$?
git -C "$CHECKOUT" clean -fdxq
case "$rc" in
  0) RAN=1; say "the review ran: $(head -1 "$OUT/drawings-$(date +%F).md" 2>/dev/null)" ;;
  2) RAN=1; say "the review could not run (its heartbeat says why)"; exit 2 ;;
  *) fail "the review stopped with exit $rc$([ "$rc" = 142 ] && echo " (over $LIMIT_SECONDS s)")" ;;
esac
exit 0
