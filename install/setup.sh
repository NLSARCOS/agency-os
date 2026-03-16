#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────
# Agency OS v4.0 — Auto-Setup & Provider Connector
#
# This script:
# 1. Validates system requirements (Python, Node, git, gh)
# 2. Creates Python venv and installs dependencies
# 3. Auto-detects OpenClaw installation
# 4. Auto-detects Ollama (local models)
# 5. Auto-detects LM Studio (local OpenAI-compatible)
# 6. Reads configs and extracts API keys/models
# 7. Generates .env with all connections ready
# 8. Runs initial Agency OS setup
#
# Usage: bash install/setup.sh
# ─────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_ROOT/.env"
OPENCLAW_CONFIG="$HOME/.openclaw/openclaw.json"

# ── Colors ────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}ℹ${NC}  $1"; }
ok()    { echo -e "${GREEN}✅${NC} $1"; }
warn()  { echo -e "${YELLOW}⚠️${NC}  $1"; }
fail()  { echo -e "${RED}❌${NC} $1"; }
header(){ echo -e "\n${BOLD}$1${NC}"; echo "─────────────────────────────────────"; }

# ── Banner ────────────────────────────────────────────────
echo -e "${BOLD}"
echo "  ╔══════════════════════════════════════╗"
echo "  ║     🏢 Agency OS v4.0 Setup          ║"
echo "  ║     Multi-Provider Auto-Connect      ║"
echo "  ╚══════════════════════════════════════╝"
echo -e "${NC}"

# ── 1. System Requirements ───────────────────────────────
header "1/7  System Requirements"

check_cmd() {
    if command -v "$1" &>/dev/null; then
        local ver
        ver=$("$1" --version 2>&1 | head -1)
        ok "$1 → $ver"
        return 0
    else
        fail "$1 not found"
        return 1
    fi
}

MISSING=0
check_cmd python3  || MISSING=$((MISSING + 1))
check_cmd git      || MISSING=$((MISSING + 1))
check_cmd node     || MISSING=$((MISSING + 1))
check_cmd npm      || MISSING=$((MISSING + 1))

# Optional but nice
check_cmd gh       || warn "gh CLI not found (optional, for git push)"
check_cmd ollama   || warn "ollama not found (optional, for local models)"

if [ "$MISSING" -gt 0 ]; then
    fail "Missing $MISSING required tools. Install them first."
    exit 1
fi

# ── 2. Python Environment ────────────────────────────────
header "2/7  Python Environment"

cd "$PROJECT_ROOT"

if [ ! -d ".venv" ]; then
    info "Creating virtual environment..."
    python3 -m venv .venv
    ok "Virtual environment created"
else
    ok "Virtual environment exists"
fi

info "Activating venv..."
source .venv/bin/activate

info "Installing dependencies..."
pip install -q -e ".[dev]" 2>/dev/null || pip install -q -e . 2>/dev/null || {
    warn "pip install failed, trying requirements..."
    [ -f requirements.txt ] && pip install -q -r requirements.txt
}
ok "Python dependencies ready"

# ── 3. OpenClaw Detection ────────────────────────────────
header "3/7  OpenClaw Detection"

OPENCLAW_FOUND=false
OPENCLAW_URL=""
OPENCLAW_API_KEY=""
OPENCLAW_PORT=""
OPENCLAW_MODELS=""

# Check if openclaw binary exists
if command -v openclaw &>/dev/null; then
    OPENCLAW_VER=$(openclaw --version 2>&1 | head -1)
    ok "OpenClaw installed → $OPENCLAW_VER"
    OPENCLAW_FOUND=true
else
    warn "OpenClaw not installed"
    info "Install with: curl -fsSL https://openclaw.ai/install | bash"
    info "Agency OS will use direct API fallback instead"
fi

# Check if openclaw.json config exists
if [ -f "$OPENCLAW_CONFIG" ]; then
    ok "OpenClaw config found → $OPENCLAW_CONFIG"

    # Extract gateway port
    OPENCLAW_PORT=$(python3 -c "
import json
with open('$OPENCLAW_CONFIG') as f:
    cfg = json.load(f)
port = cfg.get('gateway', {}).get('port', 3000)
print(port)
" 2>/dev/null || echo "3000")
    ok "Gateway port → $OPENCLAW_PORT"

    # Extract auth token
    OPENCLAW_API_KEY=$(python3 -c "
import json
with open('$OPENCLAW_CONFIG') as f:
    cfg = json.load(f)
token = cfg.get('gateway', {}).get('auth', {}).get('token', '')
print(token)
" 2>/dev/null || echo "")

    if [ -n "$OPENCLAW_API_KEY" ]; then
        ok "Auth token → ${OPENCLAW_API_KEY:0:8}..."
    else
        warn "No auth token found (gateway may be open)"
    fi

    OPENCLAW_URL="http://localhost:$OPENCLAW_PORT"

    # Extract configured models
    OPENCLAW_MODELS=$(python3 -c "
import json
with open('$OPENCLAW_CONFIG') as f:
    cfg = json.load(f)
providers = cfg.get('models', {}).get('providers', {})
models = []
for prov, pcfg in providers.items():
    for m in pcfg.get('models', []):
        models.append(f'{prov}/{m[\"id\"]}')
print(', '.join(models[:8]))
" 2>/dev/null || echo "none")
    info "Models available → $OPENCLAW_MODELS"

    # Check if gateway is actually running
    if curl -s --max-time 2 "http://localhost:$OPENCLAW_PORT/health" &>/dev/null; then
        ok "Gateway is RUNNING on port $OPENCLAW_PORT"
        
        # Test if gateway can actually process chat models (avoids the silent 404 issue)
        TEST_HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "http://localhost:$OPENCLAW_PORT/v1/chat/completions" \
          -H "Content-Type: application/json" \
          -H "Authorization: Bearer $OPENCLAW_API_KEY" \
          -d '{"messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}' --max-time 5)
        
        if [ "$TEST_HTTP_CODE" = "200" ]; then
            ok "Gateway AI Models are RESPONDING properly"
        elif [ "$TEST_HTTP_CODE" = "404" ]; then
            info "Gateway is WebSocket-only (no REST /v1/chat/completions) — this is NORMAL"
            info "Agency OS will auto-route via 'openclaw agent' CLI or direct API fallback"
        else
            warn "Gateway AI Models test returned HTTP $TEST_HTTP_CODE. Check your provider keys in openclaw.json."
        fi
        
    else
        warn "Gateway is not responding (start with: openclaw)"
    fi

    # Check enabled channels
    CHANNELS=$(python3 -c "
import json
with open('$OPENCLAW_CONFIG') as f:
    cfg = json.load(f)
channels = cfg.get('channels', {})
enabled = [ch for ch, ccfg in channels.items() if ccfg.get('enabled')]
print(', '.join(enabled) if enabled else 'none')
" 2>/dev/null || echo "none")
    info "Channels enabled → $CHANNELS"

    # Auto-extract Telegram config if available
    OPENCLAW_TG_TOKEN=$(python3 -c "
import json
with open('$OPENCLAW_CONFIG') as f:
    cfg = json.load(f)
token = cfg.get('channels', {}).get('telegram', {}).get('botToken', '')
print(token)
" 2>/dev/null || echo "")

    # Try to extract Telegram chat ID from OpenClaw sessions (where real user data lives)
    OPENCLAW_SESSIONS="$HOME/.openclaw/agents/main/sessions/sessions.json"
    OPENCLAW_TG_CHAT=""
    if [ -f "$OPENCLAW_SESSIONS" ]; then
        OPENCLAW_TG_CHAT=$(python3 -c "
import json, re
with open('$OPENCLAW_SESSIONS') as f:
    data = json.load(f)
for key in data:
    m = re.search(r'telegram:direct:(\d+)', key)
    if m:
        print(m.group(1))
        break
" 2>/dev/null || echo "")
    fi

    if [ -n "$OPENCLAW_TG_TOKEN" ] && [ -n "$OPENCLAW_TG_CHAT" ]; then
        ok "Extracted Telegram bot token + chat ID from OpenClaw"
    elif [ -n "$OPENCLAW_TG_TOKEN" ]; then
        ok "Extracted Telegram bot token from OpenClaw"
        info "Chat ID not found yet — send a message to your bot, then re-run setup"
    fi

else
    warn "No OpenClaw config at $OPENCLAW_CONFIG"
    OPENCLAW_URL="http://localhost:3000"
fi

# ── 4. Ollama Detection ──────────────────────────────────
header "4/7  Ollama Detection (Local Models)"

OLLAMA_FOUND=false
OLLAMA_HOST="http://localhost:11434"
OLLAMA_MODELS=""

if command -v ollama &>/dev/null; then
    OLLAMA_VER=$(ollama --version 2>&1 | head -1)
    ok "Ollama installed → $OLLAMA_VER"
    OLLAMA_FOUND=true

    # Check custom host
    if [ -n "${OLLAMA_HOST_ENV:-}" ]; then
        OLLAMA_HOST="$OLLAMA_HOST_ENV"
    fi

    # Check if running
    if curl -s --max-time 3 "$OLLAMA_HOST/api/tags" &>/dev/null; then
        ok "Ollama server RUNNING on $OLLAMA_HOST"

        # Get models
        OLLAMA_MODELS=$(python3 -c "
import urllib.request, json
try:
    resp = urllib.request.urlopen('$OLLAMA_HOST/api/tags', timeout=3)
    data = json.loads(resp.read())
    models = [m['name'] for m in data.get('models', [])]
    print(', '.join(models[:8]))
except: print('none')
" 2>/dev/null || echo "none")
        info "Models available → $OLLAMA_MODELS"
    else
        warn "Ollama installed but server not running"
        info "Start with: ollama serve"
    fi
else
    warn "Ollama not installed (optional, for local models)"
    info "Install with: curl -fsSL https://ollama.com/install.sh | sh"
fi

# ── 5. LM Studio Detection ──────────────────────────────
header "5/7  LM Studio Detection"

LMSTUDIO_FOUND=false
LMSTUDIO_URL="http://localhost:1234"
LMSTUDIO_MODELS=""

# Check lms CLI
if command -v lms &>/dev/null; then
    LMSTUDIO_VER=$(lms version 2>&1 | head -1)
    ok "LM Studio CLI → $LMSTUDIO_VER"
    LMSTUDIO_FOUND=true
fi

# Check common install paths
for lms_path in "$HOME/.cache/lm-studio" "$HOME/lm-studio" "$HOME/.lmstudio"; do
    if [ -d "$lms_path" ]; then
        ok "LM Studio found → $lms_path"
        LMSTUDIO_FOUND=true
        break
    fi
done

# Check if API server is running (OpenAI-compatible)
if curl -s --max-time 3 "$LMSTUDIO_URL/v1/models" &>/dev/null; then
    ok "LM Studio API RUNNING on $LMSTUDIO_URL"
    LMSTUDIO_FOUND=true

    LMSTUDIO_MODELS=$(python3 -c "
import urllib.request, json
try:
    resp = urllib.request.urlopen('$LMSTUDIO_URL/v1/models', timeout=3)
    data = json.loads(resp.read())
    models = [m['id'] for m in data.get('data', [])]
    print(', '.join(models[:8]))
except: print('none')
" 2>/dev/null || echo "none")
    info "Models available → $LMSTUDIO_MODELS"
else
    if [ "$LMSTUDIO_FOUND" = false ]; then
        warn "LM Studio not detected (optional)"
        info "Download from: https://lmstudio.ai"
    else
        warn "LM Studio installed but API server not running"
        info "Start the server from LM Studio → Local Server tab"
    fi
fi

# ── 6. Generate .env ─────────────────────────────────────
header "6/7  Environment Configuration"

if [ -f "$ENV_FILE" ]; then
    warn ".env already exists → backing up to .env.bak"
    cp "$ENV_FILE" "$ENV_FILE.bak"
fi

# Try to preserve existing API keys from current .env
EXISTING_OPENROUTER=""
EXISTING_OPENAI=""
EXISTING_ANTHROPIC=""
EXISTING_GEMINI=""
EXISTING_GITHUB=""
EXISTING_BRAVE=""
EXISTING_PERPLEXITY=""

if [ -f "$ENV_FILE" ]; then
    EXISTING_OPENROUTER=$(grep -oP 'OPENROUTER_API_KEY=\K.*' "$ENV_FILE" 2>/dev/null || true)
    EXISTING_OPENAI=$(grep -oP 'OPENAI_API_KEY=\K.*' "$ENV_FILE" 2>/dev/null || true)
    EXISTING_ANTHROPIC=$(grep -oP 'ANTHROPIC_API_KEY=\K.*' "$ENV_FILE" 2>/dev/null || true)
    EXISTING_GEMINI=$(grep -oP 'GEMINI_API_KEY=\K.*' "$ENV_FILE" 2>/dev/null || true)
    EXISTING_GITHUB=$(grep -oP 'GITHUB_TOKEN=\K.*' "$ENV_FILE" 2>/dev/null || true)
    EXISTING_BRAVE=$(grep -oP 'BRAVE_API_KEY=\K.*' "$ENV_FILE" 2>/dev/null || true)
    EXISTING_PERPLEXITY=$(grep -oP 'PERPLEXITY_API_KEY=\K.*' "$ENV_FILE" 2>/dev/null || true)
    EXISTING_WEBHOOK=$(grep -oP 'AGENCY_WEBHOOK_URL=\K.*' "$ENV_FILE" 2>/dev/null || true)
    EXISTING_TG_TOKEN=$(grep -oP 'TELEGRAM_BOT_TOKEN=\K.*' "$ENV_FILE" 2>/dev/null || true)
    EXISTING_TG_CHAT=$(grep -oP 'TELEGRAM_CHAT_ID=\K.*' "$ENV_FILE" 2>/dev/null || true)
fi

# Also try to extract OpenRouter key from openclaw.json
if [ -z "$EXISTING_OPENROUTER" ] && [ -f "$OPENCLAW_CONFIG" ]; then
    EXISTING_OPENROUTER=$(python3 -c "
import json
with open('$OPENCLAW_CONFIG') as f:
    cfg = json.load(f)
key = cfg.get('models',{}).get('providers',{}).get('openrouter',{}).get('apiKey','')
if key and key != '__OPENCLAW_REDACTED__':
    print(key)
" 2>/dev/null || true)
    if [ -n "$EXISTING_OPENROUTER" ]; then
        ok "Extracted OpenRouter key from OpenClaw config"
    fi
fi

# Fallback: Prefer OpenClaw auto-extracted TG config if nothing in existing .env
FINAL_TG_TOKEN="${EXISTING_TG_TOKEN:-${OPENCLAW_TG_TOKEN:-}}"
FINAL_TG_CHAT="${EXISTING_TG_CHAT:-${OPENCLAW_TG_CHAT:-}}"

cat > "$ENV_FILE" <<EOF
# Agency OS v4.0 — Auto-generated by setup.sh
# Generated: $(date -u '+%Y-%m-%d %H:%M UTC')

# ── OpenClaw Gateway (Auto-detected) ────────────────────
OPENCLAW_URL=${OPENCLAW_URL}
OPENCLAW_API_KEY=${OPENCLAW_API_KEY}

# ── Ollama (Local Models — Auto-detected) ───────────────
OLLAMA_HOST=${OLLAMA_HOST}
OLLAMA_DEFAULT_MODEL=${OLLAMA_MODELS%%,*}

# ── LM Studio (Local OpenAI-compatible — Auto-detected) ─
LM_STUDIO_URL=${LMSTUDIO_URL}
LM_STUDIO_DEFAULT_MODEL=${LMSTUDIO_MODELS%%,*}

# ── Cloud AI Providers (Fallback) ──────────────────────
OPENROUTER_API_KEY=${EXISTING_OPENROUTER}
OPENAI_API_KEY=${EXISTING_OPENAI}
ANTHROPIC_API_KEY=${EXISTING_ANTHROPIC}
GEMINI_API_KEY=${EXISTING_GEMINI}

# ── Tools & Services ────────────────────────────────────
GITHUB_TOKEN=${EXISTING_GITHUB}
BRAVE_API_KEY=${EXISTING_BRAVE}
PERPLEXITY_API_KEY=${EXISTING_PERPLEXITY}

# ── Notifications (Agency → Owner) ──────────────────────
AGENCY_WEBHOOK_URL=${EXISTING_WEBHOOK}

# ── Telegram (Bidirectional: Owner ↔ Agency) ────────────
TELEGRAM_BOT_TOKEN=${FINAL_TG_TOKEN}
TELEGRAM_CHAT_ID=${FINAL_TG_CHAT}

# ── Deployments (Multi-Provider) ────────────────────────
# Contabo / Custom VPS
DEPLOY_VPS_USER=
DEPLOY_VPS_HOST=
DEPLOY_VPS_KEY_PATH=

# Serverless & Frontend Platforms
VERCEL_TOKEN=
NETLIFY_AUTH_TOKEN=

# AWS / Cloud
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=

# ── Settings ────────────────────────────────────────────
AGENCY_OS_ROOT=${PROJECT_ROOT}
AGENCY_OS_LOG_LEVEL=INFO
AGENCY_LANGUAGE=en
EOF

ok ".env generated with all provider connections"
info "  OPENCLAW_URL=$OPENCLAW_URL"
info "  OLLAMA_HOST=$OLLAMA_HOST"
info "  LM_STUDIO_URL=$LMSTUDIO_URL"

# ── 7. OpenClaw ↔ Agency OS Integration ──────────────────
header "7/8  OpenClaw Integration (Bidirectional Communication)"

OPENCLAW_WORKSPACE="$HOME/.openclaw/workspace"
OPENCLAW_SKILLS="$OPENCLAW_WORKSPACE/skills"
SOUL_FILE="$OPENCLAW_WORKSPACE/SOUL.md"
SKILL_SOURCE="$PROJECT_ROOT/install/openclaw/AGENCY_OS_SKILL.md"
SOUL_PATCH="$PROJECT_ROOT/install/openclaw/SOUL_PATCH.md"

if [ -d "$OPENCLAW_WORKSPACE" ]; then
    # 1. Copy Agency OS Skill (detailed reference)
    mkdir -p "$OPENCLAW_SKILLS"
    if [ -f "$SKILL_SOURCE" ]; then
        cp "$SKILL_SOURCE" "$OPENCLAW_SKILLS/AGENCY_OS_SKILL.md"
        ok "Installed AGENCY_OS_SKILL.md into OpenClaw workspace"
    else
        warn "AGENCY_OS_SKILL.md not found in install/openclaw/"
    fi

    # 2. Embed Agency OS directly into SOUL.md (idempotent)
    if [ -f "$SOUL_FILE" ]; then
        if grep -q "Agency OS" "$SOUL_FILE" 2>/dev/null; then
            info "SOUL.md already has Agency OS integration — skipping"
        else
            # Append Agency OS block to existing SOUL.md (works with any structure)
            cat >> "$SOUL_FILE" <<'AGENCY_BLOCK'

## ── AGENCY OS (Auto-injected by setup) ──────────────────

### Herramientas de Agencia
- **Agency OS**: `shell` → `cd AGENCY_ROOT && source .venv/bin/activate && agency <cmd>`
  - `agency status` → Dashboard completo
  - `agency auto discover` → Buscar oportunidades/leads
  - `agency auto evolve` → Auto-mejorar código
  - `agency studio run <studio>` → Ejecutar departamento (dev, marketing, sales, leadops, abm, analytics, creative)
  - `agency report` → Generar reporte
  - `agency health` → Diagnóstico del sistema
  - Studios en paralelo: `agency studio run dev & agency studio run marketing & wait && agency report`

### 🏢 Reglas de Operación
- Agency OS es tu **cuerpo operativo**. Tú eres la **voz e inteligencia**.
- Cuando el usuario pida algo de negocio → ejecuta los comandos de Agency OS directamente.
- **Trabaja en silencio. Solo escribe cuando hay resultados o necesitas autorización.**
- ✅ Escribe cuando: oportunidades encontradas, tareas completadas, necesita autorización
- ❌ NUNCA para: "estoy activa", "heartbeat OK", confirmaciones rutinarias

### Ejecución Paralela
Para tareas complejas, delega a sub-agentes y fusiona resultados.
Lee `AGENCY_OS_SKILL.md` para referencia avanzada de comandos y protocolos.
AGENCY_BLOCK
            # Replace placeholder with actual project root
            sed -i "s|AGENCY_ROOT|$PROJECT_ROOT|g" "$SOUL_FILE"
            ok "Embedded Agency OS into SOUL.md (appended)"
        fi
    else
        # No SOUL.md exists — create a minimal one with Agency OS
        cat > "$SOUL_FILE" <<NEWSOUL
# SOUL.md — AI Agent + Agency OS

Eres un agente de IA con una agencia autónoma de desarrollo y marketing integrada.

## Herramientas Rápidas
- **Agency OS**: \`cd $PROJECT_ROOT && source .venv/bin/activate && agency <cmd>\`
  - \`agency status\` → Dashboard completo
  - \`agency auto discover\` → Buscar oportunidades/leads
  - \`agency studio run <studio>\` → Ejecutar departamento
  - \`agency report\` → Generar reporte
  - \`agency health\` → Diagnóstico del sistema

## Reglas
- Trabaja en silencio. Solo escribe cuando hay resultados o necesitas autorización.
- Lee \`AGENCY_OS_SKILL.md\` para referencia avanzada.
NEWSOUL
        ok "Created new SOUL.md with Agency OS embedded"
    fi
else
    info "OpenClaw workspace not found — skipping integration"
    info "Install OpenClaw first, then re-run setup to integrate"
fi

# ── 8. Verify Installation ──────────────────────────────
header "8/8  Verification"

info "Testing Agency OS..."

python3 -c "
from kernel.config import get_config
cfg = get_config()
print(f'  Project root: {cfg.root}')

from studios.base_studio import load_all_studios
studios = load_all_studios()
print(f'  Studios loaded: {len(studios)}')

from kernel.workflow_engine import get_workflow_engine
we = get_workflow_engine()
wfs = we.list_workflows()
print(f'  Workflows loaded: {len(wfs)}')

from kernel.openclaw_bridge import get_openclaw
oc = get_openclaw()
status = oc.get_status()
print(f'  OpenClaw: {\"CONNECTED\" if status[\"available\"] else \"offline (fallback mode)\"}')
print(f'  Gateway URL: {status[\"gateway_url\"]}')

from kernel.provider_detector import get_provider_detector
pd = get_provider_detector()
summary = pd.detect_all()
local_running = sum(1 for s in summary.values() if s.running and s.name in ('openclaw','ollama','lmstudio'))
cloud_configured = sum(1 for s in summary.values() if s.installed and s.name not in ('openclaw','ollama','lmstudio'))
print(f'  Providers: {local_running} local running, {cloud_configured} cloud configured')
for name, s in summary.items():
    if s.installed or s.running:
        emoji = '🟢' if s.running else '🟡'
        print(f'    {emoji} {name}: {len(s.models)} models')
" 2>&1 | while IFS= read -r line; do
    ok "$line"
done

# ── Done ─────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}══════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  🎉 Agency OS v4.0 Ready!${NC}"
echo -e "${BOLD}${GREEN}══════════════════════════════════════${NC}"
echo ""
echo -e "  ${CYAN}Run:${NC}     source .venv/bin/activate && agency-os status"
echo -e "  ${CYAN}Studios:${NC} agency-os mission add dev 'Build feature X'"
echo -e "  ${CYAN}Auto:${NC}    agency-os auto discover"
echo -e "  ${CYAN}API:${NC}     agency-os serve --port 8080"
echo ""

# Provider status summary
if [ "$OPENCLAW_FOUND" = true ]; then
    echo -e "  ${GREEN}🐙 OpenClaw connected on port $OPENCLAW_PORT${NC}"
    echo -e "  ${CYAN}Channels:${NC} $CHANNELS"
else
    echo -e "  ${YELLOW}⚠️  OpenClaw not found — using direct API fallback${NC}"
    echo -e "  ${CYAN}Install:${NC} curl -fsSL https://openclaw.ai/install | bash"
fi

if [ "$OLLAMA_FOUND" = true ]; then
    echo -e "  ${GREEN}🦙 Ollama connected → $OLLAMA_MODELS${NC}"
fi

if [ "$LMSTUDIO_FOUND" = true ]; then
    echo -e "  ${GREEN}🖥️  LM Studio connected → $LMSTUDIO_MODELS${NC}"
fi

if [ "$OLLAMA_FOUND" = false ] && [ "$LMSTUDIO_FOUND" = false ] && [ "$OPENCLAW_FOUND" = false ]; then
    echo -e "  ${YELLOW}⚠️  No local providers found — using cloud APIs only${NC}"
    echo -e "  ${CYAN}Try:${NC} curl -fsSL https://ollama.com/install.sh | sh"
fi
echo ""
