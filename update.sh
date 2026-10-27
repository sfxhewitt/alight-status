#!/bin/bash
# Generates status.json and publishes it to the single-commit 'data' branch
# (read via raw.githubusercontent.com) so GitHub Pages isn't rebuilt every run.
# Run by start-mc-loop.sh (or by hand). EVERY run logs one outcome line to $LOG.
# Exit codes: 0 ok, 1 gen-fail, 2 push-fail, 3 skip (lock held), 4 other error.
LOG=/tmp/mc-update.log
LOCK=/tmp/mission-control.lock
LAST=/tmp/mc-last-run
DATA=/workspace/mc-data
KEEP=1500                       # log lines kept (~12h at one line per run)
t0=$(date +%s)
log(){
  echo "$(date '+%F %T') $*" >> "$LOG"
  if [ "$(wc -l < "$LOG")" -gt $((KEEP + 100)) ]; then
    tail -n "$KEEP" "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
  fi
}
el(){ echo "$(( $(date +%s) - t0 ))s"; }
# Children must NOT inherit the lock FD (9>&-): an orphaned grandchild (gh, git-remote-https)
# left behind by a timeout used to keep the lock and cause cascading "skip: lock held".
# timeout -k 5: SIGTERM, then SIGKILL 5s later if it doesn't die.
run(){ local t=$1; shift; timeout -k 5 "$t" "$@" 9>&- 2>&1; }

cd /workspace/alight-status || { log "error: no site dir"; exit 4; }
exec 9>"$LOCK"
flock -n 9 || { log "skip: lock held ($(fuser "$LOCK" 2>/dev/null | xargs))"; exit 3; }

# Gap detection: make stalls (or the box being paused) visible in the log.
now=$(date +%s); prev=$(cat "$LAST" 2>/dev/null || echo "$now"); echo "$now" > "$LAST"
[ $((now - prev)) -gt 150 ] && log "warn: gap $((now - prev))s since previous run"

out=$(run 50 python3 gen.py); rc=$?
[ $rc -ne 0 ] && { log "gen-fail rc=$rc $(el): $(echo "$out" | tail -n 3 | tr '\n' ' ')"; exit 1; }

cd "$DATA" || { log "error: no $DATA"; exit 4; }
# Clear any half-finished git operation left by a killed run.
[ -d .git/rebase-merge ] || [ -d .git/rebase-apply ] && git rebase --abort >/dev/null 2>&1
[ -f .git/MERGE_HEAD ] && git merge --abort >/dev/null 2>&1
rm -f .git/index.lock .git/HEAD.lock .git/refs/heads/data.lock 2>/dev/null
[ "$(git symbolic-ref --short HEAD 2>/dev/null)" = data ] || git checkout -q data 9>&- || { log "error: checkout data failed"; exit 4; }

cp /workspace/alight-status/status.json "$DATA/status.json" || { log "error: cp failed"; exit 4; }
commit(){ git add status.json && git commit -q --amend -m status >/dev/null 2>&1; }
commit || { log "error: git commit failed"; exit 4; }

out=$(run 30 git push -q -f origin data); rc=$?
if [ $rc -ne 0 ]; then
  first="rc=$rc $(echo "$out" | tail -n 2 | tr '\n' ' ')"
  # Recover once: resync onto whatever the remote has, re-commit fresh, push again.
  if out=$(run 20 git fetch -q origin data) && git reset -q --soft origin/data && commit \
     && out=$(run 30 git push -q -f origin data); then
    log "ok (after retry; first push $first) $(git rev-parse --short HEAD) $(el)"
    exit 0
  fi
  log "push-fail $(el): first $first; retry: $(echo "$out" | tail -n 2 | tr '\n' ' ')"
  exit 2
fi
log "ok $(git rev-parse --short HEAD) $(el)"
exit 0
