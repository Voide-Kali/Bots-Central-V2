#!/usr/bin/env bash
# Install the Aval agent as a hardened systemd service (Kali/Debian/Ubuntu).
# Usage: sudo ./install-linux.sh https://SEU_SERVIDOR.tailXXXX.ts.net
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Run with sudo." >&2; exit 1; }
SERVER="${1:-}"
case "$SERVER" in https://*) ;; *) echo "Usage: sudo $0 https://SERVER.tailXXXX.ts.net" >&2; exit 1;; esac
SERVER="${SERVER%/}"
HERE="$(cd "$(dirname "$0")" && pwd)"
AGENT_DIR="$(cd "$HERE/.." && pwd)"
command -v go >/dev/null || { echo "Go not found: sudo apt install -y golang" >&2; exit 1; }

echo "==> Building"
(cd "$AGENT_DIR" && CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o /tmp/aval-agent ./cmd/bots-central-agent)
install -m 0755 /tmp/aval-agent /usr/local/bin/aval-agent && rm -f /tmp/aval-agent

echo "==> User and folders"
id aval-agent >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin aval-agent
install -d -m 0700 -o aval-agent -g aval-agent /var/lib/aval-agent
install -d -m 0755 /etc/aval-agent
cat > /etc/aval-agent/config.json <<JSON
{
  "state_dir": "/var/lib/aval-agent",
  "backend_base_url": "$SERVER",
  "heartbeat_interval": "30s",
  "transport_timeout": "10s",
  "backoff_initial": "1s",
  "backoff_max": "1m"
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

echo "==> Service"
install -m 0644 "$HERE/aval-agent.service" /etc/systemd/system/aval-agent.service
systemctl daemon-reload
systemctl enable --now aval-agent
systemctl --no-pager --lines=5 status aval-agent || true
echo "Done. Logs: journalctl -u aval-agent -f"
