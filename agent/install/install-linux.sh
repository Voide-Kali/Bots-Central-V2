#!/usr/bin/env bash
# Instalador do agente Aval para Linux (Debian/Ubuntu/Kali).
#
# Uso:
#   sudo ./install-linux.sh https://SEU_SERVIDOR.tailXXXX.ts.net
#
# Acoes opcionais (cada uma ainda pede seu PIN ou codigo por e-mail):
#   sudo AVAL_ACTIONS=lock_screen,webcam_photo,network_scan,power ./install-linux.sh https://...
#
# Sensores opcionais (desligados por padrao):
#   failed_login_photo — foto pro Telegram quando alguem erra a senha (ADR-019)
#   network_location   — reporta o IP publico/local no heartbeat (ADR-036)
#   sudo AVAL_SENSORS=network_location ./install-linux.sh https://...
#
set -euo pipefail

# --------------------------------------------------------------------------
# Funcoes auxiliares
# --------------------------------------------------------------------------
_ok()   { echo "  [OK] $*"; }
_info() { echo ""; echo ">>> $*"; }
_erro() { echo "  [ERRO] $*" >&2; }
_passo() { echo ""; echo "========================================"; echo "  $*"; echo "========================================"; }

# --------------------------------------------------------------------------
# Validacoes iniciais
# --------------------------------------------------------------------------
_passo "Instalador do Agente Aval"

echo ""
echo "Este script instala o agente Aval neste computador."
echo "Ele permite que voce monitore e controle esta maquina"
echo "pelo painel web ou pelo Telegram."
echo ""

if [ "$(id -u)" -ne 0 ]; then
  _erro "Execute com sudo:"
  echo "  sudo $0 https://SEU_SERVIDOR.tailXXXX.ts.net"
  exit 1
fi

SERVER="${1:-}"
if [ -z "$SERVER" ]; then
  _erro "Faltou o endereco do servidor."
  echo ""
  echo "Uso:"
  echo "  sudo $0 https://SEU_SERVIDOR.tailXXXX.ts.net"
  echo ""
  echo "Voce encontra o endereco no painel do Aval ou no Tailscale."
  exit 1
fi

case "$SERVER" in
  https://*) ;;
  http://*)
    _erro "O endereco precisa comecar com https://, nao http://."
    echo "  Exemplo: sudo $0 https://meu-servidor.tailXXXX.ts.net"
    exit 1
    ;;
  *)
    _erro "Endereco invalido: $SERVER"
    echo "  O endereco precisa comecar com https://"
    echo "  Exemplo: sudo $0 https://meu-servidor.tailXXXX.ts.net"
    exit 1
    ;;
esac
SERVER="${SERVER%/}"

HERE="$(cd "$(dirname "$0")" && pwd)"
AGENT_DIR="$(cd "$HERE/.." && pwd)"

# --------------------------------------------------------------------------
# Verificar dependencias
# --------------------------------------------------------------------------
_info "Verificando dependencias..."

if ! command -v go >/dev/null 2>&1; then
  _erro "Go nao esta instalado."
  echo ""
  echo "Instale com:"
  echo "  sudo apt update && sudo apt install -y golang"
  echo ""
  echo "Depois execute este script de novo."
  exit 1
fi
_ok "Go encontrado: $(go version | cut -d' ' -f3)"

# --------------------------------------------------------------------------
# Acoes e sensores
# --------------------------------------------------------------------------
ACTIONS_JSON=""
IFS=',' read -ra ACTIONS <<< "${AVAL_ACTIONS:-}"
for action in "${ACTIONS[@]+"${ACTIONS[@]}"}"; do
  case "$action" in
    lock_screen|webcam_photo|network_scan|power|unlock_screen)
      ACTIONS_JSON="$ACTIONS_JSON${ACTIONS_JSON:+, }\"$action\""
      ;;
    "") ;;
    *)
      _erro "Acao desconhecida: $action"
      echo "  Acoes disponiveis: lock_screen, unlock_screen, webcam_photo, network_scan, power"
      exit 1
      ;;
  esac
done

SENSORS_JSON=""
IFS=',' read -ra SENSORS <<< "${AVAL_SENSORS:-}"
for sensor in "${SENSORS[@]+"${SENSORS[@]}"}"; do
  case "$sensor" in
    failed_login_photo|network_location)
      [ -n "$SENSORS_JSON" ] && SENSORS_JSON="$SENSORS_JSON, "
      SENSORS_JSON="$SENSORS_JSON\"$sensor\""
      ;;
    "") ;;
    *)
      _erro "Sensor desconhecido: $sensor"
      echo "  Sensores disponiveis: failed_login_photo, network_location"
      exit 1
      ;;
  esac
done

# --------------------------------------------------------------------------
# 1. Compilar o agente
# --------------------------------------------------------------------------
_passo "Passo 1/4 — Compilando o agente"

echo "Compilando... (pode levar alguns segundos)"
(cd "$AGENT_DIR" && CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o /tmp/aval-agent ./cmd/bots-central-agent)
install -m 0755 /tmp/aval-agent /usr/local/bin/aval-agent && rm -f /tmp/aval-agent
_ok "Agente compilado e instalado em /usr/local/bin/aval-agent"

# --------------------------------------------------------------------------
# 2. Usuario, pastas e configuracao
# --------------------------------------------------------------------------
_passo "Passo 2/4 — Criando usuario e pastas"

id aval-agent >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin aval-agent
_ok "Usuario do sistema: aval-agent"

install -d -m 0700 -o aval-agent -g aval-agent /var/lib/aval-agent
_ok "Pasta de dados: /var/lib/aval-agent"

install -d -m 0755 /etc/aval-agent
_ok "Pasta de configuracao: /etc/aval-agent"

install -d -m 2770 -o root -g aval-agent /srv/aval-compartilhado
_ok "Pasta compartilhada: /srv/aval-compartilhado"
echo "  (Coloque aqui os arquivos que voce quer poder buscar pelo Aval)"

cat > /etc/aval-agent/config.json <<JSON
{
  "state_dir": "/var/lib/aval-agent",
  "backend_base_url": "$SERVER",
  "heartbeat_interval": "30s",
  "transport_timeout": "10s",
  "backoff_initial": "1s",
  "backoff_max": "1m",
  "shared_dir": "/srv/aval-compartilhado",
  "allowed_actions": [$ACTIONS_JSON],
  "sensors": [$SENSORS_JSON]
}
JSON
chmod 0644 /etc/aval-agent/config.json
_ok "Configuracao salva em /etc/aval-agent/config.json"

if [ -n "${AVAL_ACTIONS:-}" ]; then
  echo ""
  echo "  Acoes habilitadas: ${AVAL_ACTIONS}"
  echo "  (Cada acao ainda precisa do seu PIN para ser executada)"
else
  echo ""
  echo "  Nenhuma acao habilitada. Para habilitar, reinstale com:"
  echo "  sudo AVAL_ACTIONS=lock_screen,webcam_photo,network_scan,power $0 $SERVER"
fi

if [ -n "${AVAL_SENSORS:-}" ]; then
  echo "  Sensores habilitados: ${AVAL_SENSORS}"
fi

# --------------------------------------------------------------------------
# 3. Pareamento
# --------------------------------------------------------------------------
ENROLLED=/var/lib/aval-agent/device-enrollment-v1.json
if [ ! -e "$ENROLLED" ]; then
  _passo "Passo 3/4 — Pareamento com o servidor"

  echo "Para parear este computador:"
  echo ""
  echo "  1. Abra o painel do Aval no navegador"
  echo "  2. Clique em 'Adicionar dispositivo'"
  echo "  3. Copie o codigo que aparece"
  echo "  4. Cole aqui embaixo"
  echo ""
  read -rsp "Codigo de pareamento (nao aparece na tela): " TOKEN; echo
  echo ""

  if [ -z "$TOKEN" ]; then
    _erro "Codigo vazio. Execute o script de novo."
    exit 1
  fi

  echo "Conectando ao servidor..."
  set +e
  printf '%s\n' "$TOKEN" | runuser -u aval-agent -- /usr/local/bin/aval-agent \
    -config /etc/aval-agent/config.json -pairing-token-stdin &
  PID=$!
  unset TOKEN
  for _ in $(seq 1 60); do [ -e "$ENROLLED" ] && break; kill -0 "$PID" 2>/dev/null || break; sleep 1; done
  sleep 2
  kill "$PID" 2>/dev/null; wait "$PID" 2>/dev/null

  if [ ! -e "$ENROLLED" ]; then
    _erro "Pareamento falhou."
    echo ""
    echo "Possiveis causas:"
    echo "  - Codigo expirado (gere um novo no painel)"
    echo "  - Servidor fora do ar ou inacessivel"
    echo "  - Este computador nao esta na rede Tailscale"
    echo ""
    echo "Execute este script de novo para tentar outra vez."
    exit 1
  fi
  set -e

  echo ""
  _ok "Pareamento concluido."
  echo ""
  echo "  IMPORTANTE: Compare o fingerprint mostrado acima com o que"
  echo "  aparece no painel do Aval. Se forem iguais, aprove o"
  echo "  computador la. Se forem diferentes, recuse — pode ser"
  echo "  outra maquina tentando se passar por esta."
else
  echo ""
  _info "Este computador ja esta pareado. Pulando o passo 3."
fi

# --------------------------------------------------------------------------
# 4. Permissoes de acoes e servico
# --------------------------------------------------------------------------
_passo "Passo 4/4 — Configurando servico"

DROPIN=/etc/systemd/system/aval-agent.service.d
rm -f "$DROPIN/webcam.conf" "$DROPIN/journal.conf" "$DROPIN/scan.conf" \
  /etc/polkit-1/rules.d/49-aval-agent-lock.rules \
  /etc/polkit-1/rules.d/49-aval-agent-power.rules

case ",${AVAL_ACTIONS:-}," in *,lock_screen,*|*,unlock_screen,*)
  install -d -m 0755 /etc/polkit-1/rules.d
  cat > /etc/polkit-1/rules.d/49-aval-agent-lock.rules <<'RULE'
polkit.addRule(function (action, subject) {
  if ((action.id == "org.freedesktop.login1.lock-sessions" ||
       action.id == "org.freedesktop.login1.allow-multiple-sessions") &&
      subject.user == "aval-agent") {
    return polkit.Result.YES;
  }
});
RULE
  _ok "Permissao: bloquear/desbloquear tela"
  ;;
esac

case ",${AVAL_ACTIONS:-}," in *,power,*)
  install -d -m 0755 /etc/polkit-1/rules.d
  cat > /etc/polkit-1/rules.d/49-aval-agent-power.rules <<'RULE'
polkit.addRule(function (action, subject) {
  if (subject.user == "aval-agent" && (
      action.id == "org.freedesktop.login1.power-off" ||
      action.id == "org.freedesktop.login1.power-off-multiple-sessions" ||
      action.id == "org.freedesktop.login1.reboot" ||
      action.id == "org.freedesktop.login1.reboot-multiple-sessions" ||
      action.id == "org.freedesktop.login1.suspend" ||
      action.id == "org.freedesktop.login1.suspend-multiple-sessions")) {
    return polkit.Result.YES;
  }
});
RULE
  _ok "Permissao: desligar, reiniciar e suspender (com aval)"
  ;;
esac

case ",${AVAL_ACTIONS:-},${AVAL_SENSORS:-}," in *,webcam_photo,*|*,failed_login_photo,*)
  command -v fswebcam >/dev/null || { echo "  Instalando fswebcam..."; apt-get install -y fswebcam > /dev/null 2>&1; }
  install -d -m 0755 "$DROPIN"
  cat > "$DROPIN/webcam.conf" <<'CONF'
[Service]
PrivateDevices=no
DevicePolicy=closed
DeviceAllow=char-video4linux rw
SupplementaryGroups=video
CONF
  _ok "Webcam configurada"
  ;;
esac

case ",${AVAL_ACTIONS:-}," in *,network_scan,*)
  command -v nmap >/dev/null || { echo "  Instalando nmap..."; apt-get install -y nmap > /dev/null 2>&1; }
  install -d -m 0755 "$DROPIN"
  cat > "$DROPIN/scan.conf" <<'CONF'
[Service]
AmbientCapabilities=CAP_NET_RAW
CapabilityBoundingSet=CAP_NET_RAW
CONF
  _ok "Scan de rede configurado"
  ;;
esac

case ",${AVAL_SENSORS:-}," in *,failed_login_photo,*)
  install -d -m 0755 "$DROPIN"
  cat > "$DROPIN/journal.conf" <<'CONF'
[Service]
SupplementaryGroups=systemd-journal
CONF
  _ok "Sensor de senha errada configurado"
  ;;
esac

echo ""
echo "Instalando e iniciando o servico..."
install -m 0644 "$HERE/aval-agent.service" /etc/systemd/system/aval-agent.service
systemctl daemon-reload
systemctl enable aval-agent
systemctl restart aval-agent

sleep 3
if systemctl is-active --quiet aval-agent; then
  _ok "Agente Aval esta rodando."
else
  _erro "O agente nao ficou ativo."
  echo ""
  echo "Ultimas linhas do log:"
  journalctl -u aval-agent -n 15 --no-pager 2>&1 || true
  echo ""
  echo "Tente corrigir o problema e execute este script de novo."
  exit 1
fi

# --------------------------------------------------------------------------
# Resumo final
# --------------------------------------------------------------------------
echo ""
echo "========================================"
echo "  Instalacao concluida!"
echo "========================================"
echo ""
echo "  Servidor: $SERVER"
echo "  Acoes: ${AVAL_ACTIONS:-nenhuma}"
echo "  Sensores: ${AVAL_SENSORS:-nenhum}"
echo ""
echo "  Proximos passos:"
echo "  1. Aprove o computador no painel do Aval (compare o fingerprint)"
echo "  2. Vincule o Telegram no painel para receber alertas"
echo "  3. Se quiser buscar arquivos, coloque-os em /srv/aval-compartilhado"
echo ""
echo "  Comandos uteis:"
echo "  - Ver logs: journalctl -u aval-agent -f"
echo "  - Parar:    sudo systemctl stop aval-agent"
echo "  - Iniciar:  sudo systemctl start aval-agent"
echo "  - Status:   sudo systemctl status aval-agent"
echo ""
echo "  Para compartilhar arquivos, adicione seu usuario ao grupo:"
echo "  sudo usermod -aG aval-agent \$USER"
echo ""
