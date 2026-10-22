#!/usr/bin/env bash
# Install the Aval agent for the logged-in macOS user (LaunchAgent, no sudo).
# Usage: ./install-macos.sh https://SEU_SERVIDOR.tailXXXX.ts.net
# Optional ADR-016 actions (each still needs your e-mail code every time):
#   AVAL_ACTIONS=lock_screen,webcam_photo ./install-macos.sh https://...
#   (webcam_photo needs: brew install imagesnap)
set -euo pipefail
SERVER="${1:-}"
case "$SERVER" in https://*) ;; *) echo "Usage: $0 https://SERVER.tailXXXX.ts.net" >&2; exit 1;; esac
SERVER="${SERVER%/}"
HERE="$(cd "$(dirname "$0")" && pwd)"
AGENT_DIR="$(cd "$HERE/.." && pwd)"
command -v go >/dev/null || { echo "Go not found: brew install go" >&2; exit 1; }
ACTIONS_JSON=""
IFS=',' read -ra ACTIONS <<< "${AVAL_ACTIONS:-}"
for action in "${ACTIONS[@]+"${ACTIONS[@]}"}"; do
  case "$action" in
    lock_screen|webcam_photo) ACTIONS_JSON="$ACTIONS_JSON${ACTIONS_JSON:+, }\"$action\"";;
    "") ;;
    *) echo "Unknown action: $action (use lock_screen,webcam_photo)" >&2; exit 1;;
  esac
done

BASE="$HOME/Library/Application Support/Aval"
BIN="$BASE/aval-agent"
CONFIG="$BASE/config.json"
STATE="$BASE/state"
LOGS="$HOME/Library/Logs/Aval"
PLIST="$HOME/Library/LaunchAgents/br.app.aval.agent.plist"
SHARED="$HOME/Aval-Compartilhado"

echo "==> Building"
mkdir -p "$BASE" "$LOGS" "$SHARED"
chmod 0700 "$SHARED"
(cd "$AGENT_DIR" && CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o "$BIN" ./cmd/bots-central-agent)
chmod 0755 "$BIN"
cat > "$CONFIG" <<JSON
{
  "state_dir": "$STATE",
  "backend_base_url": "$SERVER",
  "heartbeat_interval": "30s",
  "transport_timeout": "10s",
  "backoff_initial": "1s",
  "backoff_max": "1m",
  "shared_dir": "$SHARED",
  "allowed_actions": [$ACTIONS_JSON]
}
JSON
chmod 0600 "$CONFIG"

launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true

ENROLLED="$STATE/device-enrollment-v1.json"
if [ ! -e "$ENROLLED" ]; then
  echo
  echo "==> Pairing. In the Aval panel click 'Adicionar dispositivo' and paste the code here."
  read -rsp "Pairing code (hidden): " TOKEN; echo
  set +e
  printf '%s\n' "$TOKEN" | "$BIN" -config "$CONFIG" -pairing-token-stdin &
  PID=$!
  unset TOKEN
  # Wait (max 60 s) until the enrollment is persisted, then stop the foreground run.
  for _ in $(seq 1 60); do [ -e "$ENROLLED" ] && break; kill -0 "$PID" 2>/dev/null || break; sleep 1; done
  sleep 2
  kill "$PID" 2>/dev/null; wait "$PID" 2>/dev/null
  [ -e "$ENROLLED" ] || { echo "Pairing failed (expired code or server unreachable). Run the script again." >&2; exit 1; }
  set -e
  echo "Compare the fingerprint printed above with the one shown in the panel, then approve it there."
fi

echo "==> LaunchAgent"
mkdir -p "$(dirname "$PLIST")"
cat > "$PLIST" <<XML
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>br.app.aval.agent</string>
  <key>ProgramArguments</key>
  <array><string>$BIN</string><string>-config</string><string>$CONFIG</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$LOGS/agent.log</string>
  <key>StandardErrorPath</key><string>$LOGS/agent.log</string>
</dict>
</plist>
XML
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Done. Logs: tail -f \"$LOGS/agent.log\""
echo "Files you allow Aval to send (after e-mail approval) go in: $SHARED"
