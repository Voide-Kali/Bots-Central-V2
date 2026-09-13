#!/usr/bin/env bash
# Writes a non-secret, owner-only Agent E2E configuration exactly once.
set -u

if [ "$#" -ne 2 ]; then
    printf 'usage: agent-config-local.sh <absolute-config-path> <absolute-state-dir>\n' >&2
    exit 2
fi
config_path=$1
state_dir=$2
case "$config_path" in /*) ;; *) printf 'Config path must be absolute.\n' >&2; exit 2 ;; esac
case "$state_dir" in /*) ;; *) printf 'State directory must be absolute.\n' >&2; exit 2 ;; esac
if [ -e "$config_path" ]; then
    printf 'Refusing to replace an existing Agent configuration.\n' >&2
    exit 1
fi
umask 077
if ! mkdir -p "$state_dir" || ! chmod 700 "$state_dir"; then
    printf 'Could not create owner-only Agent state directory.\n' >&2
    exit 1
fi
if ! printf '{\n  "state_dir": "%s",\n  "backend_base_url": "https://localhost:8443",\n  "heartbeat_interval": "30s",\n  "transport_timeout": "10s",\n  "backoff_initial": "1s",\n  "backoff_max": "1m"\n}\n' "$state_dir" >"$config_path"; then
    printf 'Could not write Agent E2E configuration.\n' >&2
    exit 1
fi
if ! chmod 600 "$config_path"; then
    printf 'Could not secure Agent E2E configuration.\n' >&2
    exit 1
fi
printf 'Created non-secret owner-only Agent E2E configuration.\n'
