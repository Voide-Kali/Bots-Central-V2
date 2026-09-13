#!/usr/bin/env bash
# Stops and removes only the named local Mailpit harness; never touches PostgreSQL or volumes.
set -u

if ! command -v sudo >/dev/null 2>&1 || ! command -v docker >/dev/null 2>&1; then
    printf 'sudo and docker are required.\n' >&2
    exit 1
fi
if ! sudo docker rm -f bots-central-v2-e2e-mailpit >/dev/null 2>&1; then
    printf 'Local Mailpit harness was not running.\n'
    exit 0
fi
printf 'Removed only the local Mailpit harness container. Certificates remain in .local/e2e-mailpit.\n'
