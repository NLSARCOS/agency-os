#!/usr/bin/env bash
set -euo pipefail

echo '[Agency OS] macOS bootstrap'
command -v brew >/dev/null || echo 'Instala Homebrew primero'
command -v python3 >/dev/null || echo 'brew install python'
command -v node >/dev/null || echo 'brew install node'
command -v git >/dev/null || echo 'xcode-select --install o brew install git'
command -v gh >/dev/null || echo 'brew install gh'
command -v openclaw >/dev/null || echo 'Instalar openclaw via npm/pnpm'

echo '1) Copia configs/env.example a tus vars de entorno'
echo '2) Ajusta launchd/cron para jobs continuos'
echo '3) Verifica modelos con openclaw models list'
