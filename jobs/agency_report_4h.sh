#!/usr/bin/env bash
set -euo pipefail
BASE="/home/nelson/.openclaw/workspace"
OS="$BASE/agency-os"
RAW="$BASE/leads/medical_leads_ecuador.csv"
CLEAN="$BASE/leads/medical_leads_no_duplicates.csv"
TOP="$BASE/leads/medical_leads_top_priority.csv"
OUT="$OS/reports/agency_report_4h.md"

mkdir -p "$OS/reports"

raw_count=0
clean_count=0
top_count=0
if [[ -f "$RAW" ]]; then raw_count=$(python3 - <<'PY'
import csv
print(sum(1 for _ in csv.DictReader(open('/home/nelson/.openclaw/workspace/leads/medical_leads_ecuador.csv',encoding='utf-8'))))
PY
); fi
if [[ -f "$CLEAN" ]]; then clean_count=$(python3 - <<'PY'
import csv
print(sum(1 for _ in csv.DictReader(open('/home/nelson/.openclaw/workspace/leads/medical_leads_no_duplicates.csv',encoding='utf-8'))))
PY
); fi
if [[ -f "$TOP" ]]; then top_count=$(python3 - <<'PY'
import csv
print(sum(1 for _ in csv.DictReader(open('/home/nelson/.openclaw/workspace/leads/medical_leads_top_priority.csv',encoding='utf-8'))))
PY
); fi

cat > "$OUT" <<EOF
# Agency OS Report (cada 4h)

Fecha: $(date)

## Build lane
- kernel/docs/install/routing en progreso continuo

## Execution lane
- leadops médico Ecuador activo
- pipelines de calidad y packaging activos

## KPIs actuales
- raw leads: ${raw_count}
- clean unique leads: ${clean_count}
- top priority leads: ${top_count}

## Jobs activos
- medical_runner.sh cada 40 min
- agency_build_cycle.sh cada 20 min
- agency_execution_cycle.sh cada 20 min
- autonomy_orchestrator.py cada 2h
- agency_report_4h.sh cada 4h

## Próximo bloque
- seguir moviendo kernel/studios desde agency-v1 hacia agency-os
- mantener growth neto de leads Ecuador
EOF

echo "[$(date)] report:ok" >> "$OS/reports/agency_report_4h.log"
