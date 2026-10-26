#!/usr/bin/env bash
# Monta o instalador de clique-duplo do macOS (.pkg) do agente Aval (ADR-026).
# RODE ESTE SCRIPT NUM MAC. Precisa de: macOS, Go e as Command Line Tools (pkgbuild).
#
#   AVAL_SERVER=https://aval.SEU.ts.net ./deploy/release/fazer-pkg.sh
#
# Gera um binario universal (Apple Silicon + Intel), embute a URL do servidor e monta um .pkg que,
# ao abrir, instala o agente para o usuario logado (LaunchAgent, sem root para o agente) e pede o
# codigo de pareamento numa janela. O .pkg sai em deploy/server/downloads/, de onde a pagina
# /baixar o oferece (build-downloads.sh mostra o cartao do .pkg quando ele existe).
#
# Observacao: sem conta de desenvolvedor Apple o .pkg nao e assinado/notarizado, entao o macOS
# mostra um aviso na primeira vez (botao direito no .pkg -> Abrir). Assinar e um passo futuro.
set -euo pipefail

SERVER="${AVAL_SERVER:-${1:-}}"
case "$SERVER" in https://*) ;; *) echo "Uso: AVAL_SERVER=https://seu-servidor.ts.net ./fazer-pkg.sh" >&2; exit 1;; esac
SERVER="${SERVER%/}"

[ "$(uname)" = "Darwin" ] || { echo "Rode num Mac: o pkgbuild so existe no macOS." >&2; exit 1; }
command -v go >/dev/null || { echo "Instale o Go primeiro: brew install go" >&2; exit 1; }
command -v pkgbuild >/dev/null || { echo "Instale as Command Line Tools: xcode-select --install" >&2; exit 1; }
command -v lipo >/dev/null || { echo "lipo nao encontrado (Command Line Tools)." >&2; exit 1; }

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
AGENT_DIR="$REPO/agent"
BUNDLE="$AGENT_DIR/install/bundle/install-macos.sh"
OUT="${AVAL_OUT:-$REPO/deploy/server/downloads}"
[ -f "$BUNDLE" ] || { echo "Instalador de pacote nao encontrado: $BUNDLE" >&2; exit 1; }
mkdir -p "$OUT"

work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
root="$work/root/usr/local/share/aval"
scripts="$work/scripts"
mkdir -p "$root" "$scripts"

echo "==> compilando binario universal (arm64 + x86_64)"
(cd "$AGENT_DIR" && GOOS=darwin GOARCH=arm64 CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o "$work/agent-arm64" ./cmd/bots-central-agent)
(cd "$AGENT_DIR" && GOOS=darwin GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o "$work/agent-amd64" ./cmd/bots-central-agent)
lipo -create -output "$root/aval-agent" "$work/agent-arm64" "$work/agent-amd64"
chmod 0755 "$root/aval-agent"
cp "$BUNDLE" "$root/install-macos.sh"

# O .pkg roda como root; o postinstall instala no contexto do usuario logado (LaunchAgent por
# usuario, sem root para o agente) reaproveitando o instalador de pacote ja testado. A URL do
# servidor fica embutida aqui.
cat > "$scripts/postinstall" <<POST
#!/bin/bash
set -e
user="\$(stat -f%Su /dev/console)"
uid="\$(id -u "\$user" 2>/dev/null || true)"
if [ -z "\$user" ] || [ "\$user" = "root" ] || [ -z "\$uid" ]; then
  echo "Nenhum usuario logado na tela para instalar o agente." >&2
  exit 1
fi
launchctl asuser "\$uid" sudo -u "\$user" env \
  HOME="/Users/\$user" \
  AVAL_SERVER="$SERVER" \
  AVAL_AGENT_BIN="/usr/local/share/aval/aval-agent" \
  AVAL_BUNDLE_DIR="/usr/local/share/aval" \
  /bin/bash "/usr/local/share/aval/install-macos.sh"
exit 0
POST
chmod 0755 "$scripts/postinstall"

echo "==> montando o .pkg"
pkgbuild \
  --root "$work/root" \
  --scripts "$scripts" \
  --identifier "br.app.aval.agent" \
  --version "1.0.0" \
  --install-location "/" \
  "$OUT/aval-instalar-macos.pkg"

if command -v shasum >/dev/null; then shasum -a 256 "$OUT/aval-instalar-macos.pkg" | cut -d' ' -f1 > "$OUT/aval-instalar-macos.pkg.sha256"; fi
echo "==> gerado $OUT/aval-instalar-macos.pkg (nao assinado)"
echo "   Coloque esta pasta no servidor e rode deploy/release/build-downloads.sh para a pagina"
echo "   /baixar passar a oferecer o .pkg automaticamente."
