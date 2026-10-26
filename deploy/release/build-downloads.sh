#!/usr/bin/env bash
# Build the download site (ADR-026). Cross-compiles the agent for macOS and Linux, wraps each
# build as a self-extracting installer with the server URL baked in, writes a SHA-256 next to
# each file, and generates the download page (index.html). Output goes to a served folder that is
# NOT committed to git (the repo keeps this script and the installer templates, never binaries).
#
# Run on the server at deploy time, where the public URL is known:
#   AVAL_SERVER=https://aval.SEU.ts.net ./deploy/release/build-downloads.sh
#
# Then Caddy serves the output at /baixar (see deploy/server/Caddyfile).
set -euo pipefail

SERVER="${AVAL_SERVER:-}"
case "$SERVER" in https://*) ;; *) echo "Defina AVAL_SERVER=https://seu-servidor.ts.net" >&2; exit 1;; esac
SERVER="${SERVER%/}"

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
AGENT_DIR="$REPO/agent"
BUNDLE_DIR="$AGENT_DIR/install/bundle"
OUT="${AVAL_OUT:-$REPO/deploy/server/downloads}"
ACTIONS="${AVAL_ACTIONS:-lock_screen,webcam_photo,network_scan}"
SENSORS="${AVAL_SENSORS:-failed_login_photo}"
command -v go >/dev/null || { echo "Go nao encontrado." >&2; exit 1; }

mkdir -p "$OUT"
# Remove only what this script generates; keep a macOS .pkg dropped here by fazer-pkg.sh.
rm -f "$OUT"/aval-instalar-linux-*.run "$OUT"/aval-instalar-linux-*.run.sha256 \
  "$OUT"/aval-instalar-macos-*.command "$OUT"/aval-instalar-macos-*.command.sha256 \
  "$OUT"/index.html
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT

sha() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }

# Build one self-extracting installer: header (server baked) + marker + raw tar.gz payload.
# os=linux|macos, arch=amd64|arm64, goos/goarch for the compiler, out_name=file to write.
build_one() {
  local os="$1" goos="$2" goarch="$3" out_name="$4"
  local stage="$work/$os-$goarch"; mkdir -p "$stage"
  echo "==> compilando $goos/$goarch"
  (cd "$AGENT_DIR" && GOOS="$goos" GOARCH="$goarch" CGO_ENABLED=0 \
    go build -trimpath -ldflags "-s -w" -o "$stage/aval-agent" ./cmd/bots-central-agent)
  if [ "$os" = linux ]; then
    cp "$BUNDLE_DIR/install-linux.sh" "$stage/install-linux.sh"
    cp "$AGENT_DIR/install/aval-agent.service" "$stage/aval-agent.service"
  else
    cp "$BUNDLE_DIR/install-macos.sh" "$stage/install-macos.sh"
  fi
  local payload="$work/$os-$goarch.tgz"
  tar -czf "$payload" -C "$stage" .
  local runner script
  if [ "$os" = linux ]; then runner='install-linux.sh'; else runner='install-macos.sh'; fi
  script="$OUT/$out_name"
  {
    printf '#!/usr/bin/env bash\n'
    printf 'set -euo pipefail\n'
    printf 'AVAL_SERVER=%q\n' "$SERVER"
    printf 'AVAL_ACTIONS=%q\n' "$ACTIONS"
    printf 'AVAL_SENSORS=%q\n' "$SENSORS"
    printf 'tmp="$(mktemp -d)"; trap '\''rm -rf "$tmp"'\'' EXIT\n'
    printf 'line=$(grep -an "^__AVAL_PAYLOAD__$" "$0" | head -1 | cut -d: -f1)\n'
    printf 'tail -n +$((line+1)) "$0" | tar -xz -C "$tmp"\n'
    printf 'AVAL_SERVER="$AVAL_SERVER" AVAL_ACTIONS="$AVAL_ACTIONS" AVAL_SENSORS="$AVAL_SENSORS" '
    printf 'AVAL_BUNDLE_DIR="$tmp" bash "$tmp/%s"\n' "$runner"
    printf 'exit 0\n'
    printf '__AVAL_PAYLOAD__\n'
    cat "$payload"
  } > "$script"
  chmod 0755 "$script"
  sha "$script" > "$script.sha256"
  echo "   gerado $out_name ($(sha "$script" | cut -c1-12)...)"
}

build_one macos darwin arm64 "aval-instalar-macos-apple-silicon.command"
build_one macos darwin amd64 "aval-instalar-macos-intel.command"
build_one linux linux  amd64 "aval-instalar-linux-x86_64.run"
build_one linux linux  arm64 "aval-instalar-linux-arm64.run"

# ---- Download page ----
card() { # title, file, note
  local title="$1" file="$2" note="$3" digest; digest="$(cat "$OUT/$file.sha256")"
  cat <<HTML
      <article class="card">
        <h2>$title</h2>
        <p class="note">$note</p>
        <a class="dl" href="./$file" download>Baixar</a>
        <p class="sum">SHA-256<br><code>$digest</code></p>
      </article>
HTML
}

# A macOS .pkg (clique duplo, sem terminal) so existe se fazer-pkg.sh foi rodado num Mac e o
# arquivo foi colocado aqui. Quando existe, aparece como opcao preferida no macOS.
pkg_card=""
if [ -f "$OUT/aval-instalar-macos.pkg" ]; then
  sha "$OUT/aval-instalar-macos.pkg" > "$OUT/aval-instalar-macos.pkg.sha256"
  pkg_card="$(card "macOS — instalador (.pkg)" "aval-instalar-macos.pkg" "Clique duplo, sem terminal. Universal (Apple Silicon e Intel).")"
fi

cat > "$OUT/index.html" <<HTML
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Aval — Baixar</title>
<style>
  :root { color-scheme: light dark; --bg:#0f1115; --fg:#e8eaed; --muted:#9aa0a6; --card:#171a21; --line:#272b33; --accent:#4f9cf9; }
  @media (prefers-color-scheme: light) { :root { --bg:#f5f6f8; --fg:#1b1d21; --muted:#5a6068; --card:#ffffff; --line:#e3e6ea; } }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.5 system-ui, sans-serif; }
  .wrap { max-width: 900px; margin: 0 auto; padding: 48px 16px 64px; }
  h1 { font-size: 30px; margin: 0 0 6px; }
  .lead { color: var(--muted); margin: 0 0 32px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 20px; }
  .card h2 { font-size: 18px; margin: 0 0 4px; }
  .note { color: var(--muted); font-size: 14px; margin: 0 0 16px; }
  .dl { display: inline-block; background: var(--accent); color: #fff; text-decoration: none; font-weight: 600; padding: 10px 18px; border-radius: 10px; }
  .sum { color: var(--muted); font-size: 12px; margin: 16px 0 0; word-break: break-all; }
  .sum code { color: var(--fg); }
  .steps { margin-top: 40px; border-top: 1px solid var(--line); padding-top: 24px; }
  .steps ol { padding-left: 20px; }
  .steps li { margin: 8px 0; }
</style>
</head>
<body>
  <div class="wrap">
    <h1>Baixar o Aval</h1>
    <p class="lead">Escolha o seu sistema, baixe e abra o instalador. Ele pede o codigo de pareamento numa janela e configura tudo sozinho.</p>
    <section class="grid">
$pkg_card
$(card "macOS — Apple Silicon (M1/M2/M3)" "aval-instalar-macos-apple-silicon.command" "Macs novos, com chip Apple.")
$(card "macOS — Intel" "aval-instalar-macos-intel.command" "Macs mais antigos, com Intel.")
$(card "Linux — x86-64" "aval-instalar-linux-x86_64.run" "Debian, Ubuntu, Kali (PC comum).")
$(card "Linux — ARM64" "aval-instalar-linux-arm64.run" "Placas ARM (ex.: Raspberry Pi 64-bit).")
    </section>
    <section class="steps">
      <h2>Como instalar</h2>
      <ol>
        <li>No painel, clique em <strong>Adicionar computador</strong> e deixe o codigo de pareamento a mao.</li>
        <li>Baixe o arquivo do seu sistema acima e abra. No macOS, se aparecer um aviso, clique com o botao direito no arquivo e escolha <strong>Abrir</strong>.</li>
        <li>Quando pedir, cole o <strong>codigo de pareamento</strong> do painel.</li>
        <li>O computador aparece no painel como <strong>aguardando seu aval</strong>; aprove comparando o codigo mostrado.</li>
      </ol>
      <p class="note">O arquivo roda codigo para instalar. Para conferir que ninguem o adulterou, compare o SHA-256 do download com o mostrado neste cartao. Os arquivos sao servidos pelo seu proprio servidor.</p>
    </section>
  </div>
</body>
</html>
HTML

echo "==> pronto em $OUT"
ls -1 "$OUT"
