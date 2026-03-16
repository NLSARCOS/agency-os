# Agency OS v3.0 — Bootstrap Guide

## Quick Install (One Command)

```bash
git clone https://github.com/NLSARCOS/agency-os.git
cd agency-os
bash install/setup.sh
```

The setup script **automatically**:
1. ✅ Validates system requirements (Python, Node, git)
2. ✅ Creates Python venv and installs dependencies
3. ✅ **Detects OpenClaw** if installed → reads port, auth token, models
4. ✅ Generates `.env` with all connections ready
5. ✅ Verifies Agency OS loads (7 studios, 7 workflows)

## Requirements

| Tool | Required | Purpose |
|------|----------|---------|
| Python 3.10+ | ✅ | Core runtime |
| Node.js 22+ | ✅ | OpenClaw gateway |
| git | ✅ | Version control |
| gh | Optional | GitHub CLI for push |
| OpenClaw | Optional | AI gateway (auto-detected) |
| ollama | Optional | Local models |

## OpenClaw Integration

If OpenClaw is installed, setup.sh will:
- Read `~/.openclaw/openclaw.json`
- Extract gateway port (default: 18789)
- Extract auth token
- List available models and channels
- Write correct `OPENCLAW_URL` and `OPENCLAW_API_KEY` to `.env`

If OpenClaw is NOT installed, Agency OS falls back to direct API calls.

### Install OpenClaw

```bash
curl -fsSL https://openclaw.ai/install | bash
openclaw        # Start the gateway + wizard
```

## Post-Install

```bash
source .venv/bin/activate

# Check status
agency-os status

# Run a mission
agency-os mission add dev "Build REST API for users"

# Autonomous discovery
agency-os auto discover

# Check OpenClaw connection
agency-os openclaw status
```
