#!/usr/bin/env bash
# setup.sh — Install dependencies and register the launchd background agent.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_LABEL="com.reminders-gtasks-sync"
AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$AGENTS_DIR/$PLIST_LABEL.plist"
LOG_PATH="$HOME/Library/Logs/reminders-gtasks-sync.log"
VENV_DIR="$SCRIPT_DIR/.venv"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[setup]${NC} $*"; }
warn()  { echo -e "${YELLOW}[setup]${NC} $*"; }
error() { echo -e "${RED}[setup]${NC} $*" >&2; }

# ── Preflight ──────────────────────────────────────────────────────────────

if [[ ! -f "$SCRIPT_DIR/config.json" ]]; then
    error "config.json not found."
    echo "       cp config.example.json config.json"
    echo "       # then edit config.json with your list names and interval"
    exit 1
fi

if [[ ! -f "$SCRIPT_DIR/credentials.json" ]]; then
    error "credentials.json not found."
    echo "       Download it from the Google Cloud Console:"
    echo "       APIs & Services → Credentials → OAuth 2.0 Client IDs → Download JSON"
    echo "       Save it as credentials.json in this directory."
    exit 1
fi

# ── Virtual environment ────────────────────────────────────────────────────

if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtual environment at .venv/ …"
    python3 -m venv "$VENV_DIR"
else
    info "Using existing virtual environment at .venv/"
fi

PYTHON="$VENV_DIR/bin/python3"

info "Installing Python dependencies …"
"$PYTHON" -m pip install --quiet --upgrade pip
"$PYTHON" -m pip install --quiet -r "$SCRIPT_DIR/requirements.txt"
info "Dependencies installed."

# ── Read poll interval from config ────────────────────────────────────────

INTERVAL_SECS=$(CONFIG_PATH="$SCRIPT_DIR/config.json" "$PYTHON" - <<'EOF'
import json, os
with open(os.environ["CONFIG_PATH"]) as f:
    c = json.load(f)
print(int(float(c.get("poll_interval_minutes", 10)) * 60))
EOF
)

info "Poll interval: $((INTERVAL_SECS / 60)) minute(s) (${INTERVAL_SECS}s)"

# ── First-run Google auth ──────────────────────────────────────────────────

if [[ ! -f "$SCRIPT_DIR/token.json" ]]; then
    info "Running first-time Google OAuth2 authorization …"
    info "Your browser will open — log in and grant access to Google Tasks."
    "$PYTHON" "$SCRIPT_DIR/main.py"
    info "Authorization complete."
fi

# ── launchd plist ─────────────────────────────────────────────────────────

mkdir -p "$AGENTS_DIR"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON}</string>
        <string>${SCRIPT_DIR}/main.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>${SCRIPT_DIR}</string>

    <key>StartInterval</key>
    <integer>${INTERVAL_SECS}</integer>

    <key>RunAtLoad</key>
    <true/>

    <key>StandardOutPath</key>
    <string>${LOG_PATH}</string>

    <key>StandardErrorPath</key>
    <string>${LOG_PATH}</string>
</dict>
</plist>
PLIST

info "LaunchAgent plist written to $PLIST_PATH"

# ── Load (or reload) the agent ────────────────────────────────────────────

if launchctl list "$PLIST_LABEL" &>/dev/null; then
    info "Unloading existing launch agent …"
    launchctl unload "$PLIST_PATH"
fi

launchctl load "$PLIST_PATH"
info "Launch agent loaded — sync will run every $((INTERVAL_SECS / 60)) minute(s)."

# ── Summary ───────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}✓ Setup complete!${NC}"
echo ""
echo "  Logs  : $LOG_PATH"
echo "  State : $SCRIPT_DIR/state.json"
echo "  Plist : $PLIST_PATH"
echo ""
echo "Useful commands:"
echo "  Run a manual sync:      $PYTHON $SCRIPT_DIR/main.py"
echo "  Tail live logs:         tail -f $LOG_PATH"
echo "  Stop background agent:  launchctl unload $PLIST_PATH"
echo "  Restart agent:          launchctl unload $PLIST_PATH && launchctl load $PLIST_PATH"
