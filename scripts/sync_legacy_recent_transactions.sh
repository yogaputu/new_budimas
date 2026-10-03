#!/bin/bash
set -euo pipefail

export PYTHONPATH=/usr/local/lib/python3.12/site-packages
PY=/www/server/panel/pyenv/bin/python
LOG=/www/wwwlogs/legacy_sync_cron.log

echo "===== legacy sync start $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$LOG"
"$PY" /root/sync_legacy_recent_transactions.py --days "${SYNC_DAYS:-7}" >> "$LOG" 2>&1
echo "===== legacy sync done $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$LOG"
