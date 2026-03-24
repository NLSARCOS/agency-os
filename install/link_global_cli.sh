#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# Agency OS — Global CLI Linker
#
# This script creates a global wrapper script for the `agency` command
# in your ~/.local/bin directory. This allows you and automated agents
# (like OpenClaw) to call `agency mission add ...` from anywhere
# without needing to constantly `cd` and `source .venv/bin/activate`.
# ─────────────────────────────────────────────────────────

set -e

# Define project root where this script lives
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_BIN="$HOME/.local/bin"
WRAPPER_SCRIPT="$LOCAL_BIN/agency"

echo -e "\n🏢 Agency OS — Global CLI Linker"
echo "─────────────────────────────────────"

# Ensure ~/.local/bin exists
if [ ! -d "$LOCAL_BIN" ]; then
    echo "Creating directory $LOCAL_BIN..."
    mkdir -p "$LOCAL_BIN"
fi

# Ensure virtual environment is built
if [ ! -f "$PROJECT_ROOT/.venv/bin/agency" ]; then
    echo "❌ Error: The Agency OS virtual environment seems incomplete."
    echo "Please run 'bash install/setup.sh' first."
    exit 1
fi

echo "Creating global wrapper script at $WRAPPER_SCRIPT..."

cat << EOF > "$WRAPPER_SCRIPT"
#!/usr/bin/env bash
# Auto-generated Agency OS wrapper script

# Set the project context 
export AGENCY_OS_ROOT="$PROJECT_ROOT"

# Always activate the secure environment and run the internal binary
if [ -f "$PROJECT_ROOT/.venv/bin/activate" ]; then
    source "$PROJECT_ROOT/.venv/bin/activate"
fi

exec "$PROJECT_ROOT/.venv/bin/agency" "\$@"
EOF

# Make it executable
chmod +x "$WRAPPER_SCRIPT"

echo "✅ Success! The 'agency' command is now available globally."
echo "If this is your first time using ~/.local/bin, you may need to restart your terminal or run:"
echo 'export PATH="$HOME/.local/bin:$PATH"'
echo "Now OpenClaw and you can just run 'agency mission add ...' from anywhere!"
