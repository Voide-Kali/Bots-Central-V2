#!/usr/bin/env bash
# Creates deploy/server/.env with fresh random secrets. Fill in the REPLACE_ME values.
set -euo pipefail
cd "$(dirname "$0")"
if [ -e .env ]; then echo ".env already exists; not overwriting." >&2; exit 1; fi
rand() { python3 -c "import secrets;print(secrets.token_urlsafe(32))"; }
umask 077
cat > .env <<ENV
# --- Server -------------------------------------------------------------
# Full Tailscale name, e.g. servidor.tail1234.ts.net  (tailscale status --self)
SERVER_HOSTNAME=REPLACE_ME
# Tailscale IPv4 of this server (tailscale ip -4)
TAILSCALE_IP=REPLACE_ME
# Folder on the 1 TB data disk (already mounted at /mnt/storage) for daily database dumps
BACKUP_DIR=/mnt/storage/bots-central-backups
BACKUP_KEEP_DAYS=14

# --- Database (generated) ------------------------------------------------
POSTGRES_DB=bots_central
POSTGRES_USER=bots_central
POSTGRES_PASSWORD=$(rand)

# --- Security keys (generated; never share) -----------------------------
ABUSE_CONTROL_HMAC_KEY=$(rand)
EMAIL_VERIFICATION_HMAC_ACTIVE_KEY_VERSION=v1
EMAIL_VERIFICATION_HMAC_KEYS={"v1":"$(rand)"}
EMAIL_VERIFICATION_MATERIAL_TYPE=code

# --- E-mail of the system (Gmail with 2-step verification + app password) --
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=aval.app.br@gmail.com
SMTP_PASSWORD=REPLACE_ME_APP_PASSWORD
SMTP_SENDER=aval.app.br@gmail.com

# --- Telegram (@BotFather) ---------------------------------------------
TELEGRAM_BOT_TOKEN=REPLACE_ME
TELEGRAM_BOT_USERNAME=aval_sistema_bot

# --- Local AI (ADR-013) -------------------------------------------------
ASSISTANT_MODEL=qwen2.5:3b

LOG_LEVEL=INFO
ENV
echo "Created $(pwd)/.env — edit the REPLACE_ME values (nano .env)."
