#!/usr/bin/env bash
set -euo pipefail
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$BASE/reports/agency_master_cycle.log"
STATUS="$BASE/kernel/system_state.md"
QUEUE="$BASE/kernel/mission_queue.md"

mkdir -p "$BASE/reports" "$BASE/kernel"

echo "[$(date)] cycle:start" >> "$LOG"

# Core continuous cycle
# In Agency OS v5.0, background loops run via heartbeat.py
# If you have custom external pipelines, call them here:
# python3 "$BASE/pipelines/custom_worker.py" >> "$LOG" 2>&1 || true

cat > "$STATUS" <<EOF
# System State — Agency OS

Last cycle: $(date)

## Active jobs
- heartbeat.py daemon (native Python background worker)
- cron cycles (external pipelines)

## Current mission queue
$(sed -n '1,120p' "$QUEUE" 2>/dev/null)
EOF

echo "[$(date)] cycle:end" >> "$LOG"
