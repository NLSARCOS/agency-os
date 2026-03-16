#!/usr/bin/env bash
set -euo pipefail
BASE="/home/nelson/.openclaw/workspace/agency-os"
LOG="$BASE/reports/agency_execution_cycle.log"
QUEUE="$BASE/kernel/mission_queue.md"
mkdir -p "$BASE/reports"

echo "[$(date)] exec:start" >> "$LOG"

# Execution lane: real agency tasks via current live pipelines
bash /home/nelson/.openclaw/workspace/leads/medical_runner.sh >> "$LOG" 2>&1 || true
python3 /home/nelson/.openclaw/workspace/agency-v1/pipelines/lead_quality_gate.py >> "$LOG" 2>&1 || true
python3 /home/nelson/.openclaw/workspace/agency-v1/pipelines/delivery_packager.py >> "$LOG" 2>&1 || true

echo "[$(date)] exec:end" >> "$LOG"
