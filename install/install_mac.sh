#!/usr/bin/env bash
#
# Agency OS — macOS Installer
# Uses Homebrew for system dependencies
# Usage: bash install/install_mac.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$ROOT/.venv"

echo '╔══════════════════════════════════════╗'
echo '║     🏢 AGENCY OS — macOS Setup       ║'
echo '╚══════════════════════════════════════╝'
echo

# ── Check Homebrew ──────────────────────────────────────────

if ! command -v brew &>/dev/null; then
    echo "🍺 Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# ── Install deps ────────────────────────────────────────────

echo "📦 Checking dependencies..."

if ! command -v python3 &>/dev/null; then
    echo "  Installing python3..."
    brew install python
fi

if ! command -v git &>/dev/null; then
    echo "  Installing git..."
    xcode-select --install 2>/dev/null || brew install git
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

source "$VENV_DIR/bin/activate"
pip install --quiet --upgrade pip
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

# ── Optional: Create launchd plist ──────────────────────────

PLIST_PATH="$HOME/Library/LaunchAgents/com.agencyos.scheduler.plist"
if [ ! -f "$PLIST_PATH" ]; then
    cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.agencyos.scheduler</string>
    <key>ProgramArguments</key>
    <array>
        <string>${VENV_DIR}/bin/agency-os</string>
        <string>start</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${ROOT}</string>
    <key>RunAtLoad</key>
    <false/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>${ROOT}/logs/scheduler.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>${ROOT}/logs/scheduler.stderr.log</string>
</dict>
</plist>
PLIST
    echo "  📋 Created launchd plist (not loaded)"
    echo "     Load with: launchctl load $PLIST_PATH"
fi

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
echo "   agency-os start               # Start scheduler daemon"
echo "   agency-os report              # Generate report"
echo
echo "📝 Don't forget to add your API keys to .env!"
