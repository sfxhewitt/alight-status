#!/bin/bash
# Starts the Mission Control update loop (singleton) in the background.
# Usage: /workspace/alight-status/start-mc-loop.sh        (safe to re-run; no-op if already running)
#        /workspace/alight-status/start-mc-loop.sh restart (kill the running loop and start fresh)
# Loop: run update.sh, THEN sleep 30s (90s after 3+ consecutive failures). Heartbeat every ~10 min.
LOG=/tmp/mc-update.log
PIDF=/tmp/mc-loop.pid
SELF=$(readlink -f "$0")
if [ "$1" = restart ] && [ -s "$PIDF" ]; then
  kill "$(cat "$PIDF")" 2>/dev/null; sleep 1
fi
if [ "$1" != _loop ]; then
  if [ -s "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then echo "already running: pid $(cat "$PIDF")"; exit 0; fi
  nohup setsid "$SELF" _loop >/dev/null 2>&1 < /dev/null &
  sleep 0.5; echo "started: pid $(cat "$PIDF" 2>/dev/null)"; exit 0
fi
# ---- loop body ----
exec 8>/tmp/mc-loop.lock
flock -n 8 || exit 0                     # another loop already owns it
echo $$ > "$PIDF"
trap 'echo "$(date "+%F %T") loop: stopped pid $$" >> "$LOG"; exit 0' TERM INT
echo "$(date '+%F %T') loop: started pid $$" >> "$LOG"
fails=0; n=0
while true; do
  /workspace/alight-status/update.sh 8>&-; rc=$?
  case $rc in 0|3) fails=0 ;; *) fails=$((fails + 1)) ;; esac
  if [ $fails -ge 3 ]; then delay=90; else delay=30; fi
  [ $fails -eq 3 ] && echo "$(date '+%F %T') loop: $fails consecutive failures, backing off to ${delay}s" >> "$LOG"
  n=$((n + 1)); [ $((n % 20)) -eq 0 ] && echo "$(date '+%F %T') loop: heartbeat pid $$ runs=$n fails=$fails" >> "$LOG"
  sleep "$delay" & wait $!
done
