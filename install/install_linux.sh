#!/usr/bin/env bash
set -euo pipefail

echo '[Agency OS] Linux bootstrap'
command -v python3 >/dev/null || echo 'Instalar python3'
command -v node >/dev/null || echo 'Instalar nodejs'
command -v npm >/dev/null || echo 'Instalar npm'
command -v git >/dev/null || echo 'Instalar git'
command -v gh >/dev/null || echo 'Instalar gh'
command -v openclaw >/dev/null || echo 'Instalar openclaw'

echo '1) Copia configs/env.example a tu .env o provider envs'
echo '2) Activa cron jobs desde agency-v1 o agency-os/jobs'
echo '3) Verifica modelos con openclaw models list'
