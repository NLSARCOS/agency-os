#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────
# Agency OS v3.0 — Auto-Setup & OpenClaw Connector
#
# This script:
# 1. Validates system requirements (Python, Node, git, gh)
# 2. Creates Python venv and installs dependencies
# 3. Auto-detects OpenClaw installation
# 4. Reads OpenClaw config (port, auth token, models)
# 5. Generates .env with all connections ready
# 6. Runs initial Agency OS setup
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
echo "  ║     🏢 Agency OS v3.0 Setup          ║"
echo "  ║     Auto-Connect & Bootstrap         ║"
echo "  ╚══════════════════════════════════════╝"
echo -e "${NC}"

# ── 1. System Requirements ───────────────────────────────
header "1/5  System Requirements"

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
header "2/5  Python Environment"

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
header "3/5  OpenClaw Detection"

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

else
    warn "No OpenClaw config at $OPENCLAW_CONFIG"
    OPENCLAW_URL="http://localhost:3000"
fi

# ── 4. Generate .env ─────────────────────────────────────
header "4/5  Environment Configuration"

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

cat > "$ENV_FILE" << EOF
# Agency OS v3.0 — Auto-generated by setup.sh
# Generated: $(date -u '+%Y-%m-%d %H:%M UTC')

# ── OpenClaw Gateway (Auto-detected) ────────────────────
OPENCLAW_URL=${OPENCLAW_URL}
OPENCLAW_API_KEY=${OPENCLAW_API_KEY}

# ── AI Providers (Fallback when OpenClaw is offline) ─────
OPENROUTER_API_KEY=${EXISTING_OPENROUTER}
OPENAI_API_KEY=${EXISTING_OPENAI}
ANTHROPIC_API_KEY=${EXISTING_ANTHROPIC}
GEMINI_API_KEY=${EXISTING_GEMINI}

# ── Tools & Services ────────────────────────────────────
GITHUB_TOKEN=${EXISTING_GITHUB}
BRAVE_API_KEY=${EXISTING_BRAVE}
PERPLEXITY_API_KEY=${EXISTING_PERPLEXITY}

# ── Settings ────────────────────────────────────────────
AGENCY_OS_ROOT=${PROJECT_ROOT}
AGENCY_OS_LOG_LEVEL=INFO
EOF

ok ".env generated with OpenClaw connection"
info "  OPENCLAW_URL=$OPENCLAW_URL"
info "  OPENCLAW_API_KEY=${OPENCLAW_API_KEY:0:8}..."

# ── 5. Verify Installation ──────────────────────────────
header "5/5  Verification"

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
" 2>&1 | while IFS= read -r line; do
    ok "$line"
done

# ── Done ─────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}══════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  🎉 Agency OS v3.0 Ready!${NC}"
echo -e "${BOLD}${GREEN}══════════════════════════════════════${NC}"
echo ""
echo -e "  ${CYAN}Run:${NC}     source .venv/bin/activate && agency-os status"
echo -e "  ${CYAN}Studios:${NC} agency-os mission add dev 'Build feature X'"
echo -e "  ${CYAN}Auto:${NC}    agency-os auto discover"
echo ""

if [ "$OPENCLAW_FOUND" = true ]; then
    echo -e "  ${GREEN}🐙 OpenClaw connected on port $OPENCLAW_PORT${NC}"
    echo -e "  ${CYAN}Channels:${NC} $CHANNELS"
else
    echo -e "  ${YELLOW}⚠️  OpenClaw not found — using direct API fallback${NC}"
    echo -e "  ${CYAN}Install:${NC} curl -fsSL https://openclaw.ai/install | bash"
fi
echo ""
