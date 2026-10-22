#!/usr/bin/env bash
# Throwaway PostgreSQL 17 for the backend test suite (loopback only, test-only password).
#
#   scripts/test-db.sh up      # start (or reuse) the container and print TEST_DATABASE_URL
#   scripts/test-db.sh test    # start if needed and run the full backend suite
#   scripts/test-db.sh down    # remove the container and its data
#
# Uses plain `docker` (Docker Desktop / OrbStack on macOS need no sudo). On Linux, if your
# user is not in the docker group, run with DOCKER="sudo docker".
set -euo pipefail
DOCKER="${DOCKER:-docker}"
NAME="aval-test-pg"
PORT="${TEST_DB_PORT:-55432}"
PASSWORD="test-only-not-a-secret"
URL="postgresql+psycopg://bots_central_test:${PASSWORD}@127.0.0.1:${PORT}/bots_central_test"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

up() {
  if ! $DOCKER inspect "$NAME" >/dev/null 2>&1; then
    $DOCKER run -d --name "$NAME" -p "127.0.0.1:${PORT}:5432" \
      -e POSTGRES_DB=bots_central_test -e POSTGRES_USER=bots_central_test \
      -e POSTGRES_PASSWORD="$PASSWORD" --tmpfs /var/lib/postgresql/data \
      postgres:17-alpine >/dev/null
  else
    $DOCKER start "$NAME" >/dev/null
  fi
  for _ in $(seq 1 60); do
    if $DOCKER exec "$NAME" pg_isready -q -U bots_central_test -d bots_central_test; then
      echo "export TEST_DATABASE_URL='$URL'"
      return 0
    fi
    sleep 1
  done
  echo "PostgreSQL did not become ready" >&2
  exit 1
}

case "${1:-up}" in
  up) up ;;
  test)
    up >/dev/null
    cd "$ROOT/backend"
    TEST_DATABASE_URL="$URL" python -m pytest "${@:2}"
    ;;
  down) $DOCKER rm -f "$NAME" >/dev/null 2>&1 || true; echo "removed $NAME" ;;
  *) echo "usage: $0 {up|test|down}" >&2; exit 2 ;;
esac
