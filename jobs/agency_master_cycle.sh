#!/usr/bin/env bash
set -euo pipefail
BASE="/home/nelson/.openclaw/workspace/agency-os"
LOG="$BASE/reports/agency_master_cycle.log"
STATUS="$BASE/kernel/system_state.md"
QUEUE="$BASE/kernel/mission_queue.md"

mkdir -p "$BASE/reports" "$BASE/kernel"

echo "[$(date)] cycle:start" >> "$LOG"

# Core continuous cycle
python3 /home/nelson/.openclaw/workspace/agency-v1/pipelines/autonomy_orchestrator.py >> "$LOG" 2>&1 || true
python3 /home/nelson/.openclaw/workspace/agency-v1/pipelines/lead_quality_gate.py >> "$LOG" 2>&1 || true
python3 /home/nelson/.openclaw/workspace/agency-v1/pipelines/delivery_packager.py >> "$LOG" 2>&1 || true

cat > "$STATUS" <<EOF
# System State — Agency OS

Last cycle: $(date)

## Active jobs
- medical_runner.sh every 40 minutes
- agency_master_cycle.sh every 20 minutes
- autonomy_orchestrator.py every 2 hours
- agency_report_4h.sh every 4 hours

## Current mission queue
$(sed -n '1,120p' "$QUEUE" 2>/dev/null)
EOF

echo "[$(date)] cycle:end" >> "$LOG"
