#!/usr/bin/env bash
# Bundled Linux installer (ADR-026). Runs from a self-extracting download: it installs a
# PRE-BUILT agent binary (no Go, no repo) and sets up the systemd service, asking the pairing
# code in a graphical window (zenity/kdialog) with a terminal fallback. The server URL is baked
# in by the release build. This is the download-site path; the source build stays in
# ../install-linux.sh for developers.
set -euo pipefail

# These three are filled in by the self-extracting wrapper / release build.
BUNDLE_DIR="${AVAL_BUNDLE_DIR:-$(cd "$(dirname "$0")" && pwd)}"
SERVER="${AVAL_SERVER:-}"
AGENT_BIN="${AVAL_AGENT_BIN:-$BUNDLE_DIR/aval-agent}"
ACTIONS="${AVAL_ACTIONS:-lock_screen,webcam_photo,network_scan}"
SENSORS="${AVAL_SENSORS:-failed_login_photo}"

case "$SERVER" in https://*) ;; *) echo "Servidor invalido (esperado https://...): $SERVER" >&2; exit 1;; esac
SERVER="${SERVER%/}"
[ -f "$AGENT_BIN" ] || { echo "Binario do agente nao encontrado: $AGENT_BIN" >&2; exit 1; }

say() { command -v zenity >/dev/null && zenity --info --no-wrap --text="$1" 2>/dev/null || echo "$1"; }
fail() {
  if command -v zenity >/dev/null; then zenity --error --no-wrap --text="$1" 2>/dev/null || true; else echo "ERRO: $1" >&2; fi
  exit 1
}

# A graphical password-less sudo (pkexec) lets the person install with a click, no terminal.
if [ "$(id -u)" -ne 0 ]; then
  if command -v pkexec >/dev/null; then
    exec pkexec env AVAL_SERVER="$SERVER" AVAL_AGENT_BIN="$AGENT_BIN" AVAL_ACTIONS="$ACTIONS" \
      AVAL_SENSORS="$SENSORS" AVAL_GUI_USER="${SUDO_USER:-$USER}" DISPLAY="${DISPLAY:-}" \
      XAUTHORITY="${XAUTHORITY:-}" bash "$0"
  elif command -v sudo >/dev/null; then
    echo "Precisa de administrador. Digite sua senha se for pedida."
    exec sudo -E AVAL_SERVER="$SERVER" AVAL_AGENT_BIN="$AGENT_BIN" AVAL_ACTIONS="$ACTIONS" \
      AVAL_SENSORS="$SENSORS" bash "$0"
  else
    fail "Nao foi possivel obter permissao de administrador (sem pkexec nem sudo)."
  fi
fi

# ---- Running as root from here ----
ask_pairing() {
  # Prefer a graphical prompt; fall back to the terminal only if no GUI is available.
  if command -v zenity >/dev/null; then
    zenity --entry --hide-text --title="Aval" \
      --text="Cole o codigo de pareamento que aparece no painel (Adicionar computador):" 2>/dev/null
  elif command -v kdialog >/dev/null; then
    kdialog --password "Cole o codigo de pareamento do painel:" 2>/dev/null
  else
    read -rsp "Codigo de pareamento: " _t; echo >&2; printf '%s' "$_t"
  fi
}

echo "==> Instalando o binario"
install -m 0755 "$AGENT_BIN" /usr/local/bin/aval-agent
id aval-agent >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin aval-agent
install -d -m 0700 -o aval-agent -g aval-agent /var/lib/aval-agent
install -d -m 0755 /etc/aval-agent
install -d -m 2770 -o root -g aval-agent /srv/aval-compartilhado

# Only actions this build knows about; unknown ones are dropped (defensive, matches the agent).
actions_json=""
IFS=',' read -ra _acts <<< "$ACTIONS"
for a in "${_acts[@]+"${_acts[@]}"}"; do
  case "$a" in lock_screen|webcam_photo|network_scan) actions_json="$actions_json${actions_json:+, }\"$a\"";; esac
done
sensors_json=""
case ",$SENSORS," in *,failed_login_photo,*) sensors_json="\"failed_login_photo\"";; esac
cat > /etc/aval-agent/config.json <<JSON
{
  "state_dir": "/var/lib/aval-agent",
  "backend_base_url": "$SERVER",
  "heartbeat_interval": "30s",
  "transport_timeout": "10s",
  "backoff_initial": "1s",
  "backoff_max": "1m",
  "shared_dir": "/srv/aval-compartilhado",
  "allowed_actions": [$actions_json],
  "sensors": [$sensors_json]
}
JSON
chmod 0644 /etc/aval-agent/config.json

ENROLLED=/var/lib/aval-agent/device-enrollment-v1.json
if [ ! -e "$ENROLLED" ]; then
  TOKEN="$(ask_pairing)"
  [ -n "$TOKEN" ] || fail "Nenhum codigo informado. Rode de novo e cole o codigo do painel."
  set +e
  printf '%s\n' "$TOKEN" | runuser -u aval-agent -- /usr/local/bin/aval-agent \
    -config /etc/aval-agent/config.json -pairing-token-stdin &
  PID=$!
  unset TOKEN
  for _ in $(seq 1 60); do [ -e "$ENROLLED" ] && break; kill -0 "$PID" 2>/dev/null || break; sleep 1; done
  sleep 2; kill "$PID" 2>/dev/null; wait "$PID" 2>/dev/null
  set -e
  [ -e "$ENROLLED" ] || fail "Pareamento falhou (codigo expirado ou servidor fora). Gere outro codigo e tente de novo."
fi

# Extra privileges per action (same shape as the source installer).
DROPIN=/etc/systemd/system/aval-agent.service.d
rm -f "$DROPIN/webcam.conf" "$DROPIN/scan.conf" "$DROPIN/journal.conf" /etc/polkit-1/rules.d/49-aval-agent-lock.rules
case ",$ACTIONS," in *,lock_screen,*)
  install -d -m 0755 /etc/polkit-1/rules.d
  cat > /etc/polkit-1/rules.d/49-aval-agent-lock.rules <<'RULE'
polkit.addRule(function (action, subject) {
  if (action.id == "org.freedesktop.login1.lock-sessions" && subject.user == "aval-agent") {
    return polkit.Result.YES;
  }
});
RULE
  ;;
esac
case ",$ACTIONS,$SENSORS," in *,webcam_photo,*|*,failed_login_photo,*)
  command -v fswebcam >/dev/null || (command -v apt-get >/dev/null && apt-get install -y fswebcam) || true
  install -d -m 0755 "$DROPIN"
  printf '[Service]\nPrivateDevices=no\nDevicePolicy=closed\nDeviceAllow=char-video4linux rw\nSupplementaryGroups=video\n' > "$DROPIN/webcam.conf"
  ;;
esac
case ",$ACTIONS," in *,network_scan,*)
  command -v nmap >/dev/null || (command -v apt-get >/dev/null && apt-get install -y nmap) || true
  install -d -m 0755 "$DROPIN"
  printf '[Service]\nAmbientCapabilities=CAP_NET_RAW\nCapabilityBoundingSet=CAP_NET_RAW\n' > "$DROPIN/scan.conf"
  ;;
esac
case ",$SENSORS," in *,failed_login_photo,*)
  install -d -m 0755 "$DROPIN"
  printf '[Service]\nSupplementaryGroups=systemd-journal\n' > "$DROPIN/journal.conf"
  ;;
esac

install -m 0644 "$BUNDLE_DIR/aval-agent.service" /etc/systemd/system/aval-agent.service
systemctl daemon-reload
systemctl enable aval-agent
systemctl restart aval-agent
# Report the real state: the agent validates its config a moment after starting.
sleep 3
if systemctl is-active --quiet aval-agent; then
  say "Aval instalado. O computador vai aparecer no painel como aguardando seu aval; aprove por la."
else
  fail "O agente nao ficou ativo. Veja: journalctl -u aval-agent -n 20"
fi
