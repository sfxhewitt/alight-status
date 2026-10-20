#!/bin/bash
# Called every 30s by the nohup loop. Generates status.json and publishes it to the 'data' branch
# (read via raw.githubusercontent.com) so GitHub Pages isn't rebuilt every minute.
# Failures are logged to /tmp/mc-update.log (trimmed) so stalls can be diagnosed.
LOG=/tmp/mc-update.log
log(){ echo "$(date '+%F %T') $*" >> "$LOG"; tail -n 200 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"; }
cd /workspace/alight-status || exit 1
exec 9>/tmp/mission-control.lock; flock -n 9 || { log "skip: lock held"; exit 0; }
out=$(timeout 50 python3 gen.py 2>&1); rc=$?
[ $rc -ne 0 ] && { log "gen.py failed rc=$rc: $(echo "$out" | tail -n 3 | tr '\n' ' ')"; exit 0; }
cp status.json /workspace/mc-data/status.json
cd /workspace/mc-data && git add status.json || { log "git add failed"; exit 0; }
git commit -q --amend -m status >/dev/null 2>&1 || { log "git commit failed"; exit 0; }
out=$(timeout 30 git push -q -f origin data 2>&1); rc=$?
[ $rc -ne 0 ] && log "push failed rc=$rc: $(echo "$out" | tail -n 2 | tr '\n' ' ')"
exit 0
