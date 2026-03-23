# Cron plan — Agency OS

Este es un ejemplo de cómo configurar el sistema operativo de tu Agencia en tu crontab (`crontab -e`). Deberás reemplazar `/path/to/agency-os` por la ruta real donde clonaste el repositorio.

## Activos
```cron
# Ejemplo de ciclos principales
*/40 * * * * /path/to/agency-os/leads/medical_runner.sh
*/20 * * * * /path/to/agency-os/jobs/agency_master_cycle.sh
15 */2 * * * python3 /path/to/agency-os/pipelines/autonomy_orchestrator.py >> /path/to/agency-os/reports/autonomy.log 2>&1
0 */4 * * * /path/to/agency-os/jobs/agency_report_4h.sh >> /path/to/agency-os/reports/agency_report_4h.log 2>&1
```

## Nota
En Mac, esto se puede portar luego a `launchd`, pero cron sirve como baseline de referencia.
