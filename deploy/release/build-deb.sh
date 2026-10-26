#!/usr/bin/env bash
# Build ONE .deb for the Aval agent (ADR-028), from a pre-built binary. Double-clicking the .deb
# opens the system's graphical installer -> Install -> password -> done, with no terminal and no
# "file full of code". Pairing is a GUI step afterwards: the package adds a "Parear Aval" menu
# entry that shows a window asking for the panel's pairing code.
#
# Called by build-downloads.sh (which cross-compiles the binary and bakes the server URL).
# Usage:
#   AVAL_SERVER=https://... AVAL_ACTIONS=lock_screen,webcam_photo,network_scan \
#   AVAL_SENSORS=failed_login_photo AVAL_VERSION=0.1.0+... \
#   build-deb.sh <deb_arch:amd64|arm64> <binary_path> <out_dir> <repo_dir>
set -euo pipefail

ARCH="${1:?arch (amd64|arm64)}"
BIN="${2:?binary path}"
OUT="${3:?out dir}"
REPO="${4:?repo dir}"

SERVER="${AVAL_SERVER:?defina AVAL_SERVER=https://...}"
case "$SERVER" in https://*) ;; *) echo "Servidor invalido: $SERVER" >&2; exit 1;; esac
SERVER="${SERVER%/}"
ACTIONS="${AVAL_ACTIONS:-lock_screen,webcam_photo,network_scan}"
SENSORS="${AVAL_SENSORS:-failed_login_photo}"
VERSION="${AVAL_VERSION:-0.1.0}"
[ -f "$BIN" ] || { echo "Binario nao encontrado: $BIN" >&2; exit 1; }
command -v dpkg-deb >/dev/null || { echo "dpkg-deb nao encontrado (apt-get install -y dpkg)." >&2; exit 1; }

friendly="x86_64"; [ "$ARCH" = arm64 ] && friendly="arm64"
OUT_DEB="$OUT/aval-instalar-linux-$friendly.deb"

# allowed_actions / sensors as JSON arrays — only values this project knows.
actions_json=""
IFS=',' read -ra _a <<< "$ACTIONS"
for a in "${_a[@]+"${_a[@]}"}"; do
  case "$a" in lock_screen|webcam_photo|network_scan) actions_json="$actions_json${actions_json:+, }\"$a\"";; esac
done
sensors_json=""
case ",$SENSORS," in *,failed_login_photo,*) sensors_json="\"failed_login_photo\"";; esac

# Recommends depend on which actions are baked (installed by apt/GNOME-Software automatically).
recommends="policykit-1 | polkit"
case ",$ACTIONS,$SENSORS," in *,webcam_photo,*|*,failed_login_photo,*) recommends="$recommends, fswebcam";; esac
case ",$ACTIONS," in *,network_scan,*) recommends="$recommends, nmap";; esac

root="$(mktemp -d)"; trap 'rm -rf "$root"' EXIT
chmod 0755 "$root"

install -D -m 0755 "$BIN" "$root/usr/bin/aval-agent"

# Hardened service unit (reused from the repo), pointed at /usr/bin (a .deb must not use /usr/local).
sed 's#/usr/local/bin/aval-agent#/usr/bin/aval-agent#' \
  "$REPO/agent/install/aval-agent.service" > /tmp/_unit.$$
install -D -m 0644 /tmp/_unit.$$ "$root/etc/systemd/system/aval-agent.service"; rm -f /tmp/_unit.$$

# Baked config (server + actions decided at build time).
install -d "$root/etc/aval-agent"
cat > "$root/etc/aval-agent/config.json" <<JSON
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
chmod 0644 "$root/etc/aval-agent/config.json"

# Per-action privileges (same shape as the installer), shipped as package files.
dropin="$root/etc/systemd/system/aval-agent.service.d"
case ",$ACTIONS," in *,lock_screen,*)
  install -d "$root/etc/polkit-1/rules.d"
  cat > "$root/etc/polkit-1/rules.d/49-aval-agent-lock.rules" <<'RULE'
polkit.addRule(function (action, subject) {
  if (action.id == "org.freedesktop.login1.lock-sessions" && subject.user == "aval-agent") {
    return polkit.Result.YES;
  }
});
RULE
  ;;
esac
case ",$ACTIONS,$SENSORS," in *,webcam_photo,*|*,failed_login_photo,*)
  install -d "$dropin"
  printf '[Service]\nPrivateDevices=no\nDevicePolicy=closed\nDeviceAllow=char-video4linux rw\nSupplementaryGroups=video\n' > "$dropin/webcam.conf"
  ;;
esac
case ",$ACTIONS," in *,network_scan,*)
  install -d "$dropin"
  printf '[Service]\nAmbientCapabilities=CAP_NET_RAW\nCapabilityBoundingSet=CAP_NET_RAW\n' > "$dropin/scan.conf"
  ;;
esac
case ",$SENSORS," in *,failed_login_photo,*)
  install -d "$dropin"
  printf '[Service]\nSupplementaryGroups=systemd-journal\n' > "$dropin/journal.conf"
  ;;
esac

# Root helper: does the pairing + enables the service. Reads the code from stdin (never argv).
install -d "$root/usr/lib/aval"
cat > "$root/usr/lib/aval/aval-pair-root" <<'SH'
#!/bin/bash
set -euo pipefail
ENROLLED=/var/lib/aval-agent/device-enrollment-v1.json
CONFIG=/etc/aval-agent/config.json
BIN=/usr/bin/aval-agent
if [ ! -e "$ENROLLED" ]; then
  code="$(cat)"
  [ -n "$code" ] || { echo "sem codigo" >&2; exit 2; }
  set +e
  printf '%s\n' "$code" | runuser -u aval-agent -- "$BIN" -config "$CONFIG" -pairing-token-stdin &
  pid=$!
  for _ in $(seq 1 60); do [ -e "$ENROLLED" ] && break; kill -0 "$pid" 2>/dev/null || break; sleep 1; done
  sleep 2; kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
  set -e
  [ -e "$ENROLLED" ] || { echo "pareamento falhou" >&2; exit 3; }
fi
systemctl enable --now aval-agent
SH
chmod 0755 "$root/usr/lib/aval/aval-pair-root"

# User-facing pairing: graphical window (zenity/kdialog), terminal fallback; re-elevates via pkexec.
cat > "$root/usr/bin/aval-parear" <<'SH'
#!/bin/bash
set -euo pipefail
ENROLLED=/var/lib/aval-agent/device-enrollment-v1.json
PAIR_ROOT=/usr/lib/aval/aval-pair-root
HAVE_GUI=""; [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && command -v zenity >/dev/null && HAVE_GUI=1

info()  { [ -n "$HAVE_GUI" ] && zenity --info  --no-wrap --text="$1" 2>/dev/null || echo "$1"; }
errbox(){ [ -n "$HAVE_GUI" ] && zenity --error --no-wrap --text="$1" 2>/dev/null || echo "ERRO: $1" >&2; }

if [ -e "$ENROLLED" ]; then info "Este computador ja esta pareado com o Aval."; exit 0; fi

if [ -n "$HAVE_GUI" ]; then
  code="$(zenity --entry --hide-text --title="Aval" \
    --text="Cole o codigo de pareamento do painel (Adicionar computador):" 2>/dev/null)" || exit 0
elif command -v kdialog >/dev/null; then
  code="$(kdialog --password "Cole o codigo de pareamento do painel:" 2>/dev/null)" || exit 0
else
  read -rsp "Codigo de pareamento: " code; echo
fi
[ -n "$code" ] || exit 0

run_root() {
  if [ "$(id -u)" -eq 0 ]; then printf '%s' "$code" | "$PAIR_ROOT"
  elif [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && command -v pkexec >/dev/null; then printf '%s' "$code" | pkexec "$PAIR_ROOT"
  elif command -v sudo >/dev/null; then printf '%s' "$code" | sudo "$PAIR_ROOT"
  else return 10; fi
}

if run_root; then
  info "Aval instalado e pareado. O computador vai aparecer no painel como aguardando seu aval; aprove por la."
else
  errbox "Pareamento falhou (codigo expirado ou servidor fora do ar). Gere outro codigo no painel e abra 'Parear Aval' de novo."
  exit 1
fi
SH
chmod 0755 "$root/usr/bin/aval-parear"

cat > "$root/usr/lib/aval/server" <<<"$SERVER"

install -d "$root/usr/share/applications"
cat > "$root/usr/share/applications/aval-parear.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=Parear Aval
Comment=Conectar este computador ao painel Aval
Exec=/usr/bin/aval-parear
Icon=network-vpn
Terminal=false
Categories=System;Settings;
DESK

# ---- control + maintainer scripts ----
install -d "$root/DEBIAN"
instsize="$(du -sk "$root" | cut -f1)"
cat > "$root/DEBIAN/control" <<CTRL
Package: aval-agent
Version: $VERSION
Section: admin
Priority: optional
Architecture: $ARCH
Maintainer: Aval <aval@localhost>
Installed-Size: $instsize
Depends: zenity
Recommends: $recommends
Description: Agente Aval - heartbeat assinado e telemetria
 Instala o agente Aval como servico systemd protegido. Apos instalar, abra
 "Parear Aval" no menu de aplicativos e cole o codigo de pareamento do painel;
 o computador aparece no painel aguardando a sua aprovacao.
CTRL

cat > "$root/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
if [ "$1" = configure ]; then
  id aval-agent >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin aval-agent
  install -d -m 0700 -o aval-agent -g aval-agent /var/lib/aval-agent
  install -d -m 2770 -o root -g aval-agent /srv/aval-compartilhado
  systemctl daemon-reload >/dev/null 2>&1 || true
  # O servico so sobe depois do pareamento: abra "Parear Aval" no menu.
fi
exit 0
POST
chmod 0755 "$root/DEBIAN/postinst"

cat > "$root/DEBIAN/prerm" <<'PRE'
#!/bin/sh
set -e
if [ "$1" = remove ] || [ "$1" = deconfigure ]; then
  systemctl disable --now aval-agent >/dev/null 2>&1 || true
fi
exit 0
PRE
chmod 0755 "$root/DEBIAN/prerm"

cat > "$root/DEBIAN/postrm" <<'PRM'
#!/bin/sh
set -e
systemctl daemon-reload >/dev/null 2>&1 || true
if [ "$1" = purge ]; then
  rm -rf /var/lib/aval-agent /etc/aval-agent
  deluser --system aval-agent >/dev/null 2>&1 || userdel aval-agent >/dev/null 2>&1 || true
fi
exit 0
PRM
chmod 0755 "$root/DEBIAN/postrm"

dpkg-deb --root-owner-group --build "$root" "$OUT_DEB" >/dev/null
if command -v sha256sum >/dev/null; then sha256sum "$OUT_DEB" | cut -d' ' -f1 > "$OUT_DEB.sha256"
else shasum -a 256 "$OUT_DEB" | cut -d' ' -f1 > "$OUT_DEB.sha256"; fi
echo "   gerado aval-instalar-linux-$friendly.deb ($(cut -c1-12 < "$OUT_DEB.sha256")...)"
