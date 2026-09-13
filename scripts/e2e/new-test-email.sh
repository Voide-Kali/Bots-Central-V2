#!/usr/bin/env bash
# Generates an ephemeral recipient only; it never contacts the application.
set -eu

for required in date od; do
    command -v "$required" >/dev/null 2>&1 || {
        printf 'Missing required command: %s\n' "$required" >&2
        exit 1
    }
done

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
random=$(od -An -N4 -tx4 /dev/urandom | tr -d '[:space:]')
printf 'mvp1-e2e-%s-%s@example.test\n' "$timestamp" "$random"
