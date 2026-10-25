#!/usr/bin/env bash
# Bundled macOS installer (ADR-026). Runs from a self-extracting download: installs a PRE-BUILT
# agent binary (no Go, no repo) as a per-user LaunchAgent (no sudo), asking the pairing code in a
# graphical window (osascript) with a terminal fallback. The server URL is baked in by the release
# build. The source build stays in ../install-macos.sh for developers.
set -euo pipefail

BUNDLE_DIR="${AVAL_BUNDLE_DIR:-$(cd "$(dirname "$0")" && pwd)}"
SERVER="${AVAL_SERVER:-}"
AGENT_BIN="${AVAL_AGENT_BIN:-$BUNDLE_DIR/aval-agent}"
ACTIONS="${AVAL_ACTIONS:-lock_screen,webcam_photo,network_scan}"

case "$SERVER" in https://*) ;; *) echo "Servidor invalido (esperado https://...): $SERVER" >&2; exit 1;; esac
SERVER="${SERVER%/}"
[ -f "$AGENT_BIN" ] || { echo "Binario do agente nao encontrado: $AGENT_BIN" >&2; exit 1; }

gui() { osascript -e "display dialog \"$1\" buttons {\"OK\"} default button 1 with title \"Aval\"" >/dev/null 2>&1 || true; }
fail() { gui "$1"; echo "ERRO: $1" >&2; exit 1; }

ask_pairing() {
  osascript -e 'try' \
    -e 'text returned of (display dialog "Cole o codigo de pareamento que aparece no painel (Adicionar computador):" default answer "" with hidden answer with title "Aval")' \
    -e 'on error' -e 'return ""' -e 'end try' 2>/dev/null
}

BASE="$HOME/Library/Application Support/Aval"
BIN="$BASE/aval-agent"
CONFIG="$BASE/config.json"
STATE="$BASE/state"
LOGS="$HOME/Library/Logs/Aval"
PLIST="$HOME/Library/LaunchAgents/br.app.aval.agent.plist"
SHARED="$HOME/Aval-Compartilhado"

echo "==> Instalando o binario"
mkdir -p "$BASE" "$LOGS" "$SHARED"; chmod 0700 "$SHARED"
install -m 0755 "$AGENT_BIN" "$BIN"
# Remove the Gatekeeper quarantine on our own freshly-copied binary (user-owned file).
xattr -d com.apple.quarantine "$BIN" 2>/dev/null || true

actions_json=""
IFS=',' read -ra _acts <<< "$ACTIONS"
for a in "${_acts[@]+"${_acts[@]}"}"; do
  case "$a" in lock_screen|webcam_photo|network_scan) actions_json="$actions_json${actions_json:+, }\"$a\"";; esac
done
cat > "$CONFIG" <<JSON
{
  "state_dir": "$STATE",
  "backend_base_url": "$SERVER",
  "heartbeat_interval": "30s",
  "transport_timeout": "10s",
  "backoff_initial": "1s",
  "backoff_max": "1m",
  "shared_dir": "$SHARED",
  "allowed_actions": [$actions_json]
}
JSON
chmod 0600 "$CONFIG"

launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true

ENROLLED="$STATE/device-enrollment-v1.json"
if [ ! -e "$ENROLLED" ]; then
  TOKEN="$(ask_pairing)"
  [ -n "$TOKEN" ] || fail "Nenhum codigo informado. Abra de novo e cole o codigo do painel."
  set +e
  printf '%s\n' "$TOKEN" | "$BIN" -config "$CONFIG" -pairing-token-stdin &
  PID=$!
  unset TOKEN
  for _ in $(seq 1 60); do [ -e "$ENROLLED" ] && break; kill -0 "$PID" 2>/dev/null || break; sleep 1; done
  sleep 2; kill "$PID" 2>/dev/null; wait "$PID" 2>/dev/null
  set -e
  [ -e "$ENROLLED" ] || fail "Pareamento falhou (codigo expirado ou servidor fora). Gere outro codigo e tente de novo."
fi

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
sleep 3
if tail -n 8 "$LOGS/agent.log" 2>/dev/null | grep -q '"message":"agent startup failed"'; then
  fail "O agente registrou falha ao subir. Veja: $LOGS/agent.log"
fi
gui "Aval instalado. O computador vai aparecer no painel como aguardando seu aval; aprove por la."
