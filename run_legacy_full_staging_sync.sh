#!/bin/bash
set -euo pipefail

LOG=/www/wwwlogs/legacy_full_staging_sync_$(date +%Y%m%d_%H%M%S).log
echo "===== legacy full staging start $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$LOG"
/www/server/panel/pyenv/bin/python /root/legacy_full_staging_sync.py \
  --days "${SYNC_DAYS:-30}" \
  --chunk-size 5000 \
  --max-full-rows "${MAX_FULL_ROWS:-50000}" \
  --replace >> "$LOG" 2>&1
echo "===== legacy full staging done $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$LOG"
echo "$LOG" > /root/legacy_full_staging_sync.lastlog
