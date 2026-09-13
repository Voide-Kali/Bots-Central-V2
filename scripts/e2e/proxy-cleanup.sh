#!/usr/bin/env bash
# Stops and removes only the named local E2E proxy; never touches PostgreSQL or volumes.
set -u

if ! command -v sudo >/dev/null 2>&1 || ! command -v docker >/dev/null 2>&1; then
    printf 'sudo and docker are required.\n' >&2
    exit 1
fi
if ! sudo docker rm -f bots-central-v2-e2e-proxy >/dev/null 2>&1; then
    printf 'Local E2E proxy was not running.\n'
    exit 0
fi
printf 'Removed only the local E2E proxy container. Certificates remain in .local/e2e-mailpit.\n'
