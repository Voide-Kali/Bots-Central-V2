#!/usr/bin/env bash
# Restore an age-encrypted backup (ADR-033) into the running database.
#
#   ./restore-backup.sh <arquivo.dump.age> <chave-privada-age.txt>
#
# A chave privada (age1...-SECRET, do age-keygen) NAO fica no servidor — traga-a so na hora de
# restaurar e leve embora depois. O dump e decifrado em memoria (stream) e aplicado com pg_restore
# como o POSTGRES_USER (owner), porque restaurar recria objetos (DDL).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
enc="${1:?uso: ./restore-backup.sh <arquivo.dump.age> <chave-privada.txt>}"
key="${2:?informe o arquivo da chave privada age}"
[ -f "$enc" ] || { echo "nao achei o backup: $enc" >&2; exit 1; }
[ -f "$key" ] || { echo "nao achei a chave: $key" >&2; exit 1; }
[ -f .env ] || { echo "faltou o .env" >&2; exit 1; }
set -a; . ./.env; set +a
: "${POSTGRES_USER:?}"; : "${POSTGRES_DB:?}"

echo "==> restaurando $enc em '$POSTGRES_DB' (pode sobrescrever dados atuais). Ctrl-C para abortar."
sleep 3
# Decifra fora do container e envia o dump por stdin ao pg_restore de dentro do container db.
age -d -i "$key" "$enc" \
  | docker compose exec -T db pg_restore --clean --if-exists --no-owner \
      -U "$POSTGRES_USER" -d "$POSTGRES_DB"
echo "==> restore concluido."
