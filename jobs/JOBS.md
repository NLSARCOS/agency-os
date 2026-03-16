# Jobs continuos — Agency OS

## Jobs activos deseados
### 1. medical_runner.sh
Cada 40 min
- mantiene scraping médico Ecuador vivo

### 2. agency_master_cycle.sh
Cada 20 min
- corre el ciclo maestro del OS
- dispara quality gate y packaging
- actualiza state

### 3. autonomy_orchestrator.py
Cada 2h
- evalúa rendimiento
- dispara growth optimizer si estanca

### 4. agency_report_4h.sh
Cada 4h
- genera reporte ejecutivo de estado del Agency OS
- incluye jobs, KPIs y cola actual

## Regla crítica
Los jobs no deben quedarse esperando intervención manual. Si un bloque termina, el siguiente bloque debe entrar automáticamente por cola.
