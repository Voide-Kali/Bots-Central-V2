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
VERSION="${AVAL_VERSION:-0.1.0+$(date -u +%Y%m%d%H%M)}"
command -v go >/dev/null || { echo "Go nao encontrado." >&2; exit 1; }

mkdir -p "$OUT"
# Remove only what this script generates; keep a macOS .pkg dropped here by fazer-pkg.sh.
rm -f "$OUT"/aval-instalar-linux-*.deb "$OUT"/aval-instalar-linux-*.deb.sha256 \
  "$OUT"/aval-instalar-linux-*.run "$OUT"/aval-instalar-linux-*.run.sha256 \
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

# Linux ships as a .deb: double-click opens the graphical installer (no terminal, no "file full of
# code"), and pairing is the "Parear Aval" menu entry. See deploy/release/build-deb.sh / ADR-028.
build_linux_deb() { # goarch, deb_arch
  local goarch="$1" deb_arch="$2"
  local stage="$work/linux-$goarch"; mkdir -p "$stage"
  echo "==> compilando linux/$goarch"
  (cd "$AGENT_DIR" && GOOS=linux GOARCH="$goarch" CGO_ENABLED=0 \
    go build -trimpath -ldflags "-s -w" -o "$stage/aval-agent" ./cmd/bots-central-agent)
  AVAL_SERVER="$SERVER" AVAL_ACTIONS="$ACTIONS" AVAL_SENSORS="$SENSORS" AVAL_VERSION="$VERSION" \
    bash "$HERE/build-deb.sh" "$deb_arch" "$stage/aval-agent" "$OUT" "$REPO"
}

build_one macos darwin arm64 "aval-instalar-macos-apple-silicon.command"
build_one macos darwin amd64 "aval-instalar-macos-intel.command"
build_linux_deb amd64 amd64
build_linux_deb arm64 arm64

# ---- Download page (ADR-029) ----
# The landing is a static, animated site in deploy/release/site/ (hero 3D, explainer, contact).
# Only the download cards depend on the build (filenames + SHA-256), so they are generated here
# and injected into the page placeholder; the rest of the page ships as-is.
SITE="$HERE/site"
card() { # title, file, note
  local title="$1" file="$2" note="$3" digest; digest="$(cat "$OUT/$file.sha256")"
  cat <<HTML
        <article class="card">
          <h3>$title</h3>
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

cards="$(cat <<HTML
$pkg_card
$(card "macOS — Apple Silicon (M1/M2/M3)" "aval-instalar-macos-apple-silicon.command" "Macs novos, com chip Apple.")
$(card "macOS — Intel" "aval-instalar-macos-intel.command" "Macs mais antigos, com Intel.")
$(card "Linux — x86-64 (.deb)" "aval-instalar-linux-x86_64.deb" "Debian, Ubuntu, Kali (PC comum). Clique duplo e Instalar.")
$(card "Linux — ARM64 (.deb)" "aval-instalar-linux-arm64.deb" "Placas ARM (ex.: Raspberry Pi 64-bit). Clique duplo e Instalar.")
HTML
)"

# Copy the static assets and inject the cards into the placeholder (awk: no python dependency).
cp "$SITE/styles.css" "$SITE/app.js" "$SITE/three.min.js" "$OUT/"
cards_file="$(mktemp)"; printf '%s\n' "$cards" > "$cards_file"
awk -v cf="$cards_file" '
  /<!--DOWNLOAD_CARDS-->/ { while ((getline line < cf) > 0) print line; next }
  { print }
' "$SITE/index.html" > "$OUT/index.html"
rm -f "$cards_file"

echo "==> pronto em $OUT"
ls -1 "$OUT"
