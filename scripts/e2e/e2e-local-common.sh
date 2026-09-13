#!/usr/bin/env bash
# Shared, dependency-free checks for the local E2E harness.  Source this file; do not execute it.

e2e_wait_for() {
    local description=$1
    local endpoint=$2
    shift 2
    local attempt=1

    # Twenty one-second attempts keep startup feedback quick while allowing Docker services to settle.
    while [ "$attempt" -le 20 ]; do
        if "$@" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
        attempt=$((attempt + 1))
    done
    printf 'Readiness failed: %s (%s) did not become available within 20 seconds.\n' \
        "$description" "$endpoint" >&2
    return 1
}

e2e_validate_ca() {
    local ca_cert=$1
    openssl x509 -in "$ca_cert" -noout >/dev/null 2>&1 || return 1
    openssl x509 -in "$ca_cert" -noout -ext basicConstraints 2>/dev/null | grep -Eq 'CA:TRUE' || return 1
    openssl x509 -in "$ca_cert" -noout -ext keyUsage 2>/dev/null | grep -Eq 'Certificate Sign' || return 1
}

e2e_validate_localhost_leaf() {
    local ca_cert=$1
    local leaf_cert=$2
    openssl x509 -in "$leaf_cert" -noout >/dev/null 2>&1 || return 1
    openssl verify -CAfile "$ca_cert" "$leaf_cert" >/dev/null 2>&1 || return 1
    openssl verify -CAfile "$ca_cert" -verify_hostname localhost "$leaf_cert" >/dev/null 2>&1 || return 1
    openssl verify -CAfile "$ca_cert" -verify_ip 127.0.0.1 "$leaf_cert" >/dev/null 2>&1 || return 1
    openssl x509 -in "$leaf_cert" -noout -ext subjectAltName 2>/dev/null | grep -Eq 'DNS:localhost' || return 1
    openssl x509 -in "$leaf_cert" -noout -ext subjectAltName 2>/dev/null | grep -Eq 'IP Address:127\.0\.0\.1' || return 1
}

e2e_same_regular_file() {
    local first=$1
    local second=$2
    local first_canonical
    local second_canonical

    [ -f "$first" ] && [ -f "$second" ] || return 1
    first_canonical=$(realpath -e -- "$first") || return 1
    second_canonical=$(realpath -e -- "$second") || return 1
    [ "$first_canonical" = "$second_canonical" ]
}

e2e_certificate_recovery_hint() {
    local state_dir=$1
    printf 'Existing E2E certificates are invalid or incomplete; nothing was replaced.\n' >&2
    printf 'Regenerate only the E2E certificate bundle after preserving it, for example:\n' >&2
    printf '  mv %s %s.invalid-UTC_TIMESTAMP\n' "$state_dir" "$state_dir" >&2
    printf 'Then rerun the relevant local harness script. Do not remove Agent state or PostgreSQL data.\n' >&2
}
