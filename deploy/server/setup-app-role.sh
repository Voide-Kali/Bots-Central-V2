#!/usr/bin/env bash
# Create (or update) the least-privilege application role for the backend and the Telegram bot,
# and grant it only the DML it needs (ADR-032). Idempotent: safe to run on every deploy.
#
# Run from this folder (deploy/server), with the stack's `db` service up and .env present:
#   ./setup-app-role.sh
#
# It connects to the db container as the OWNER/superuser (POSTGRES_USER) and applies
# sql/app-role.sql, which creates the role APP_DB_USER with password APP_DB_PASSWORD. Bring the
# backend and telegram services up AFTER this (they connect as that role).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
[ -f .env ] || { echo "faltou o .env em $HERE" >&2; exit 1; }
set -a; . ./.env; set +a

: "${POSTGRES_USER:?defina POSTGRES_USER no .env}"
: "${POSTGRES_DB:?defina POSTGRES_DB no .env}"
: "${APP_DB_USER:?defina APP_DB_USER no .env (ex.: aval_app)}"
: "${APP_DB_PASSWORD:?defina APP_DB_PASSWORD no .env}"

case "$APP_DB_USER" in
  "$POSTGRES_USER") echo "APP_DB_USER nao pode ser igual ao POSTGRES_USER (o superusuario)." >&2; exit 1;;
esac

echo "==> aplicando papel de aplicacao '$APP_DB_USER' no banco '$POSTGRES_DB' (como '$POSTGRES_USER')"
docker compose exec -T db \
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -v app_user="$APP_DB_USER" \
    -v app_pw="$APP_DB_PASSWORD" \
    -v db_name="$POSTGRES_DB" \
    -v owner="$POSTGRES_USER" \
  < sql/app-role.sql

echo "==> pronto. Suba/recrie backend e telegram para usarem o novo papel:"
echo "    docker compose up -d backend telegram"
