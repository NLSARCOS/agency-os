#!/usr/bin/env bash
set -euo pipefail
BASE="/home/nelson/.openclaw/workspace/agency-os"
LOG="$BASE/reports/agency_build_cycle.log"
STATE="$BASE/kernel/system_state.md"
QUEUE="$BASE/kernel/mission_queue.md"

mkdir -p "$BASE/reports" "$BASE/kernel"

echo "[$(date)] build:start" >> "$LOG"

# Current build focus: kernel, docs, portability, routing
python3 "$BASE/kernel/task_router.py" >> "$LOG" 2>&1 || true
python3 "$BASE/kernel/mission_engine.py" >> "$LOG" 2>&1 || true
{
  echo "## Build Tick $(date)"
  echo "- Review kernel docs and structure"
  echo "- Ensure portability docs for Mac/Linux"
  echo "- Keep mission queue/state current"
  echo
} >> "$BASE/reports/build_journal.md"

cat > "$STATE" <<EOF
# System State — Agency OS

Last build cycle: $(date)

## Build lane
- kernel refinement
- docs completion
- install portability
- role/model routing

## Queue snapshot
$(sed -n '1,120p' "$QUEUE" 2>/dev/null)
EOF

echo "[$(date)] build:end" >> "$LOG"
