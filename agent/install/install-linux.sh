#!/usr/bin/env bash
# Install the Aval agent as a hardened systemd service (Kali/Debian/Ubuntu).
# Usage: sudo ./install-linux.sh https://SEU_SERVIDOR.tailXXXX.ts.net
# Optional ADR-016 actions (each still needs your e-mail code every time):
#   sudo AVAL_ACTIONS=lock_screen,webcam_photo ./install-linux.sh https://...
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Run with sudo." >&2; exit 1; }
SERVER="${1:-}"
case "$SERVER" in https://*) ;; *) echo "Usage: sudo $0 https://SERVER.tailXXXX.ts.net" >&2; exit 1;; esac
SERVER="${SERVER%/}"
HERE="$(cd "$(dirname "$0")" && pwd)"
AGENT_DIR="$(cd "$HERE/.." && pwd)"
command -v go >/dev/null || { echo "Go not found: sudo apt install -y golang" >&2; exit 1; }

ACTIONS_JSON=""
IFS=',' read -ra ACTIONS <<< "${AVAL_ACTIONS:-}"
for action in "${ACTIONS[@]+"${ACTIONS[@]}"}"; do
  case "$action" in
    lock_screen|webcam_photo) ACTIONS_JSON="$ACTIONS_JSON${ACTIONS_JSON:+, }\"$action\"";;
    "") ;;
    *) echo "Unknown action: $action (use lock_screen,webcam_photo)" >&2; exit 1;;
  esac
done

echo "==> Building"
(cd "$AGENT_DIR" && CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o /tmp/aval-agent ./cmd/bots-central-agent)
install -m 0755 /tmp/aval-agent /usr/local/bin/aval-agent && rm -f /tmp/aval-agent

echo "==> User and folders"
id aval-agent >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin aval-agent
install -d -m 0700 -o aval-agent -g aval-agent /var/lib/aval-agent
install -d -m 0755 /etc/aval-agent
# Folder whose files may be sent after e-mail approval (ADR-015). Add yourself to the
# aval-agent group to drop files here:  sudo usermod -aG aval-agent "$SUDO_USER"
install -d -m 2770 -o root -g aval-agent /srv/aval-compartilhado
cat > /etc/aval-agent/config.json <<JSON
{
  "state_dir": "/var/lib/aval-agent",
  "backend_base_url": "$SERVER",
  "heartbeat_interval": "30s",
  "transport_timeout": "10s",
  "backoff_initial": "1s",
  "backoff_max": "1m",
  "shared_dir": "/srv/aval-compartilhado",
  "allowed_actions": [$ACTIONS_JSON]
}
JSON
chmod 0644 /etc/aval-agent/config.json

ENROLLED=/var/lib/aval-agent/device-enrollment-v1.json
if [ ! -e "$ENROLLED" ]; then
  echo
  echo "==> Pairing. In the Aval panel click 'Adicionar dispositivo' and paste the code here."
  read -rsp "Pairing code (hidden): " TOKEN; echo
  # The token goes through a pipe (bash builtin printf): never in argv, history or files.
  set +e
  printf '%s\n' "$TOKEN" | runuser -u aval-agent -- /usr/local/bin/aval-agent \
    -config /etc/aval-agent/config.json -pairing-token-stdin &
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

echo "==> Actions: ${AVAL_ACTIONS:-none}"
DROPIN=/etc/systemd/system/aval-agent.service.d
rm -f "$DROPIN/webcam.conf" /etc/polkit-1/rules.d/49-aval-agent-lock.rules
case ",${AVAL_ACTIONS:-}," in *,lock_screen,*)
  # Let only the aval-agent user ask logind to lock the sessions (nothing else).
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
case ",${AVAL_ACTIONS:-}," in *,webcam_photo,*)
  command -v fswebcam >/dev/null || apt-get install -y fswebcam
  install -d -m 0755 "$DROPIN"
  cat > "$DROPIN/webcam.conf" <<'CONF'
# webcam_photo (ADR-016): expose only video devices to the agent.
[Service]
PrivateDevices=no
DevicePolicy=closed
DeviceAllow=char-video4linux rw
SupplementaryGroups=video
CONF
  ;;
esac

echo "==> Service"
install -m 0644 "$HERE/aval-agent.service" /etc/systemd/system/aval-agent.service
systemctl daemon-reload
systemctl enable aval-agent
systemctl restart aval-agent
systemctl --no-pager --lines=5 status aval-agent || true
echo "Done. Logs: journalctl -u aval-agent -f"
echo "Files you allow Aval to send (after e-mail approval) go in: /srv/aval-compartilhado"
