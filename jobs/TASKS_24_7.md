# Tareas 24/7 — Agency OS

## Job principal 24/7
### `agency_master_cycle.sh`
Frecuencia: cada 20 minutos

### Qué hace
1. Ejecuta el autonomy orchestrator.
2. Ejecuta quality gate.
3. Ejecuta delivery packager.
4. Actualiza `kernel/system_state.md`.
5. Escribe log de ciclo.

## Job de soporte
### `medical_runner.sh`
Frecuencia: cada 40 minutos
Función: mantener leadops médico en segundo plano.

### `autonomy_orchestrator.py`
Frecuencia: cada 2 horas
Función: medir KPI y, si no hay crecimiento, activar growth optimizer.

### `agency_report_4h.sh`
Frecuencia: cada 4 horas
Función: generar reporte ejecutivo del Agency OS.

## Cadena de continuidad
- Si un bloque termina -> el siguiente ciclo lo retoma automáticamente.
- Si no hay crecimiento -> growth optimizer cambia táctica.
- Si falla un job -> el siguiente cron vuelve a entrar.

## Prioridad actual
- 97% Agency OS
- 3% scraping médico Ecuador
