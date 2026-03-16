# Cron plan — Agency OS

## Activos
```cron
*/40 * * * * /home/nelson/.openclaw/workspace/leads/medical_runner.sh
*/20 * * * * /home/nelson/.openclaw/workspace/agency-v1/scripts/agency_master_cycle.sh
15 */2 * * * python3 /home/nelson/.openclaw/workspace/agency-v1/pipelines/autonomy_orchestrator.py >> /home/nelson/.openclaw/workspace/agency-v1/reports/autonomy.log 2>&1
0 */4 * * * /home/nelson/.openclaw/workspace/agency-os/jobs/agency_report_4h.sh >> /home/nelson/.openclaw/workspace/agency-os/reports/agency_report_4h.log 2>&1
```

## Nota
En Mac, esto se puede portar luego a `launchd`, pero cron sirve como baseline de referencia.
