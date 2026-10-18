#!/bin/bash
# Called every 60s by the nohup loop. Generates status.json from projects.json and publishes it.
cd /workspace/alight-status || exit 1
exec 9>/tmp/mission-control.lock; flock -n 9 || exit 0   # never overlap runs
timeout 50 python3 gen.py || exit 0
git add status.json && git commit -qm status >/dev/null 2>&1 && git push -q 2>/dev/null
