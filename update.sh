#!/bin/bash
# Called every 60s by the nohup loop. Generates status.json and publishes it to the 'data' branch
# (read via raw.githubusercontent.com) so GitHub Pages isn't rebuilt every minute.
cd /workspace/alight-status || exit 1
exec 9>/tmp/mission-control.lock; flock -n 9 || exit 0
timeout 50 python3 gen.py || exit 0
cp status.json /workspace/mc-data/status.json
cd /workspace/mc-data && git add status.json && git commit -q --amend -m status >/dev/null 2>&1 && timeout 30 git push -q -f origin data 2>/dev/null
