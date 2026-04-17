#!/usr/bin/env bash
# agent-ledger install script
# Sets up autostart via launchd (macOS) or systemd (Linux)

set -e

INSTALL_DIR="$HOME/Documents/code/agent-ledger"
DATA_DIR="$HOME/Documents/agent-ledger"

echo "agent-ledger installer"
echo "  Code: $INSTALL_DIR"
echo "  Data: $DATA_DIR"
echo ""

# Verify Python 3.8+
PYTHON=$(command -v python3 || command -v python)
if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3 not found. Please install Python 3.8+."
    exit 1
fi
PY_VER=$($PYTHON -c 'import sys; print(sys.version_info >= (3, 8))')
if [ "$PY_VER" != "True" ]; then
    echo "ERROR: Python 3.8+ required. Found: $($PYTHON --version)"
    exit 1
fi
echo "Python: $($PYTHON --version)"

# Verify sqlite3 CLI
if command -v sqlite3 &>/dev/null; then
    echo "sqlite3: $(sqlite3 --version)"
else
    echo "WARNING: sqlite3 CLI not found (optional for direct queries)"
    echo "  macOS:  brew install sqlite"
    echo "  Ubuntu: sudo apt install sqlite3"
fi

chmod +x "$INSTALL_DIR/daemon.py"
chmod +x "$INSTALL_DIR/mcp_server.py"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── macOS launchd ──────────────────────────────────────────────────────────────
if [[ "$OSTYPE" == "darwin"* ]]; then
    PLIST="$HOME/Library/LaunchAgents/com.agent-ledger.daemon.plist"
    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.agent-ledger.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$INSTALL_DIR/daemon.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$DATA_DIR/daemon.log</string>
    <key>StandardErrorPath</key>
    <string>$DATA_DIR/daemon.log</string>
</dict>
</plist>
EOF
    echo ""
    echo "launchd plist written to:"
    echo "  $PLIST"
    echo ""
    echo "To start now and on every login:"
    echo "  launchctl load $PLIST"
    echo ""
    echo "To stop:"
    echo "  launchctl unload $PLIST"
fi

# ── Linux systemd ──────────────────────────────────────────────────────────────
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    SYSTEMD_DIR="$HOME/.config/systemd/user"
    mkdir -p "$SYSTEMD_DIR"
    cat > "$SYSTEMD_DIR/agent-ledger.service" << EOF
[Unit]
Description=Agent Ledger Daemon
After=network.target

[Service]
ExecStart=$PYTHON $INSTALL_DIR/daemon.py
Restart=always
RestartSec=10
StandardOutput=append:$DATA_DIR/daemon.log
StandardError=append:$DATA_DIR/daemon.log

[Install]
WantedBy=default.target
EOF
    echo ""
    echo "systemd unit written to:"
    echo "  $SYSTEMD_DIR/agent-ledger.service"
    echo ""
    echo "To start now and on every login:"
    echo "  systemctl --user enable agent-ledger"
    echo "  systemctl --user start agent-ledger"
    echo ""
    echo "To stop:"
    echo "  systemctl --user stop agent-ledger"
fi

# ── MCP registration ───────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "MCP Registration"
echo ""
echo "Run:"
echo ""
echo "  claude mcp add agent-ledger -- $PYTHON $INSTALL_DIR/mcp_server.py"
echo ""
echo "Or add manually to ~/.claude/settings.json:"
echo ""
echo '  {'
echo '    "mcpServers": {'
echo '      "agent-ledger": {'
echo "        \"command\": \"$PYTHON\","
echo "        \"args\": [\"$INSTALL_DIR/mcp_server.py\"]"
echo '      }'
echo '    }'
echo '  }'
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Done."
