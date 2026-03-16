#!/usr/bin/env bash
#
# Agency OS — Linux Installer
# Supports: Ubuntu/Debian, Fedora/RHEL, Arch
# Usage: bash install/install_linux.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$ROOT/.venv"

echo '╔══════════════════════════════════════╗'
echo '║     🏢 AGENCY OS — Linux Setup       ║'
echo '╚══════════════════════════════════════╝'
echo

# ── Detect package manager ──────────────────────────────────

install_pkg() {
    if command -v apt-get &>/dev/null; then
        sudo apt-get update -qq && sudo apt-get install -y -qq "$@"
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y -q "$@"
    elif command -v pacman &>/dev/null; then
        sudo pacman -S --noconfirm "$@"
    else
        echo "⚠️  Unknown package manager. Install manually: $*"
        return 1
    fi
}

# ── Check and install dependencies ──────────────────────────

echo "📦 Checking dependencies..."

if ! command -v python3 &>/dev/null; then
    echo "  Installing python3..."
    install_pkg python3 python3-pip python3-venv
fi

if ! command -v git &>/dev/null; then
    echo "  Installing git..."
    install_pkg git
fi

if ! command -v node &>/dev/null; then
    echo "  ℹ️  Node.js not found (optional, for antigravity-kit updates)"
fi

echo "  ✅ python3 $(python3 --version 2>&1 | cut -d' ' -f2)"
echo "  ✅ git $(git --version | cut -d' ' -f3)"

# ── Create Python virtual environment ───────────────────────

echo
echo "🐍 Setting up Python environment..."

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo "  Created virtualenv: $VENV_DIR"
else
    echo "  Virtualenv exists: $VENV_DIR"
fi

# Activate
source "$VENV_DIR/bin/activate"

# Upgrade pip
pip install --quiet --upgrade pip

# Install Agency OS package
echo "  Installing Agency OS..."
pip install --quiet -e "$ROOT"

# ── Create .env if missing ──────────────────────────────────

echo
echo "⚙️  Configuring environment..."

if [ ! -f "$ROOT/.env" ]; then
    cp "$ROOT/configs/env.example" "$ROOT/.env"
    echo "  Created .env from template — edit with your API keys"
else
    echo "  .env already exists"
fi

# ── Create runtime directories ──────────────────────────────

mkdir -p "$ROOT/data" "$ROOT/logs" "$ROOT/reports"

# ── Initialize database ────────────────────────────────────

echo
echo "🗄️  Initializing database..."
python3 -c "from kernel.state_manager import get_state; get_state(); print('  ✅ SQLite database ready')"

# ── Test CLI ────────────────────────────────────────────────

echo
echo "🧪 Testing CLI..."
agency-os --version
echo "  ✅ CLI working"

# ── Print summary ──────────────────────────────────────────

echo
echo '╔══════════════════════════════════════╗'
echo '║       ✅ Installation Complete        ║'
echo '╚══════════════════════════════════════╝'
echo
echo "🚀 Quick Start:"
echo "   source $VENV_DIR/bin/activate"
echo "   agency-os status              # System dashboard"
echo "   agency-os mission add 'task'  # Add a mission"
echo "   agency-os mission list        # List missions"
echo "   agency-os studio list         # List studios"
echo "   agency-os start               # Start scheduler daemon"
echo "   agency-os report              # Generate report"
echo
echo "📝 Don't forget to add your API keys to .env!"
