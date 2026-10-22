#!/usr/bin/env bash
# Aval doctor: checks the home-server stack and says, in Portuguese, what is wrong
# and how to fix it. Never prints secrets (only lengths and yes/no).
# Usage (from deploy/server):  ./doctor.sh
set -uo pipefail
cd "$(dirname "$0")"
ok=0; bad=0
pass() { printf '  ✅ %s\n' "$1"; ok=$((ok+1)); }
fail() { printf '  ❌ %s\n     → %s\n' "$1" "$2"; bad=$((bad+1)); }
val() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2-; }

echo "== Arquivo .env"
if [ ! -f .env ]; then fail ".env não existe" "rode ./generate-env.sh"; exit 1; fi
[ "$(stat -c %a .env)" = "600" ] && pass ".env com permissão 600" || fail ".env com permissão $(stat -c %a .env)" "chmod 600 .env"
grep -q REPLACE_ME .env && fail "ainda há REPLACE_ME no .env" "nano .env e preencha" || pass "sem REPLACE_ME"
p="$(val SMTP_PASSWORD)"
case "${#p}" in
  16) pass "SMTP_PASSWORD com 16 caracteres (formato de senha de app)";;
  *) fail "SMTP_PASSWORD com ${#p} caracteres" "use a SENHA DE APP do Google (16 letras, sem espaços): myaccount.google.com → Segurança → Senhas de app";;
esac
case "$p" in *" "*|*\"*|*\'*) fail "SMTP_PASSWORD tem espaço ou aspas" "cole as 16 letras juntas, sem aspas";; esac
t="$(val TELEGRAM_BOT_TOKEN)"
[[ "$t" =~ ^[0-9]+:[A-Za-z0-9_-]{30,}$ ]] && pass "TELEGRAM_BOT_TOKEN com formato válido" || fail "TELEGRAM_BOT_TOKEN com formato estranho" "copie de novo do @BotFather (/mybots → API Token)"

echo "== Containers"
for s in db backend telegram web ollama backup; do
  state="$(docker compose ps --format '{{.Service}} {{.State}}' 2>/dev/null | awk -v s="$s" '$1==s{print $2}')"
  [ "$state" = "running" ] && pass "$s rodando" || fail "$s: ${state:-não existe}" "docker compose --env-file .env up -d; docker compose logs --tail 30 $s"
done

echo "== Serviços externos (testados de dentro do backend)"
docker compose exec -T backend python - <<'PY' 2>/dev/null
import json, os, smtplib, ssl, urllib.request
def say(ok, text, fix=""):
    print(("  ✅ " if ok else "  ❌ ") + text + ("" if ok else "\n     → " + fix))
try:
    s = smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=15)
    s.starttls(context=ssl.create_default_context())
    s.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
    s.quit()
    say(True, "Gmail aceitou o login (códigos por e-mail vão funcionar)")
except Exception as e:
    say(False, f"Gmail recusou: {type(e).__name__}", "gere uma senha de app nova e coloque no .env; depois: docker compose up -d --force-recreate backend telegram")
try:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getMe", timeout=15) as r:
        name = json.load(r)["result"]["username"]
    say(True, f"Telegram respondeu como @{name}")
except Exception as e:
    say(False, f"Telegram recusou: {type(e).__name__}", "token errado ou revogado: pegue o atual no @BotFather")
PY
if docker compose exec -T ollama ollama list 2>/dev/null | grep -q "${ASSISTANT_MODEL:-qwen2.5:3b}"; then
  pass "modelo da IA baixado"
else
  fail "modelo da IA não encontrado" "docker compose exec ollama ollama pull qwen2.5:3b"
fi

echo "== Rede"
host="$(val SERVER_HOSTNAME)"
curl -fsS --max-time 10 "https://$host/api/v1/health" >/dev/null 2>&1 && pass "painel responde em https://$host" || fail "https://$host não respondeu" "confira Tailscale (tailscale status) e: sudo tailscale serve status (deve estar vazio)"

echo; echo "Resultado: $ok ok, $bad problema(s)."
[ "$bad" -eq 0 ]
