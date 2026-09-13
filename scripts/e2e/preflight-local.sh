#!/usr/bin/env bash
# Read-only readiness checks for a rebooted local MVP-1 E2E harness.
set -u

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
. "$repo_root/scripts/e2e/e2e-local-common.sh"

state_dir=${E2E_MAILPIT_STATE_DIR:-"$repo_root/.local/e2e-mailpit"}
smtp_port=${E2E_MAILPIT_SMTP_PORT:-1025}
mailpit_port=${E2E_MAILPIT_UI_PORT:-8025}
browser_port=${E2E_BROWSER_PORT:-8080}
agent_port=${E2E_AGENT_HTTPS_PORT:-8443}
backend_url=${E2E_BACKEND_HEALTH_URL:-http://127.0.0.1:8000/api/v1/health}
vite_url=${E2E_VITE_URL:-http://127.0.0.1:5173/}
ca_cert="$state_dir/smtp-ca.pem"
smtp_cert="$state_dir/smtp-server.pem"
https_cert="$state_dir/agent-https.pem"
failed=0

for required in curl docker openssl python3 realpath sudo; do
    if ! command -v "$required" >/dev/null 2>&1; then
        printf 'PREFLIGHT: FAIL (missing required command: %s)\n' "$required" >&2
        exit 1
    fi
done

gate() {
    local name=$1
    shift
    if "$@" >/dev/null 2>&1; then
        printf '%s: OK\n' "$name"
    else
        printf '%s: FAIL\n' "$name"
        failed=1
    fi
}

container_ready() {
    local container=$1
    local state
    state=$(sudo docker inspect --format '{{.State.Running}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container" 2>/dev/null) || return 1
    case "$state" in
        'true healthy'|'true none') return 0 ;;
        *) return 1 ;;
    esac
}

postgres_ready() {
    container_ready bots-central-v2-pg17-test && sudo docker exec bots-central-v2-pg17-test pg_isready -q
}

smtp_starttls_verify() {
    python3 - "$ca_cert" "$smtp_port" <<'PY'
import smtplib
import ssl
import sys

context = ssl.create_default_context(cafile=sys.argv[1])
context.check_hostname = True
context.verify_mode = ssl.CERT_REQUIRED
with smtplib.SMTP("localhost", int(sys.argv[2]), timeout=5) as client:
    client.ehlo()
    if not client.has_extn("starttls"):
        raise RuntimeError("SMTP server does not offer STARTTLS")
    client.starttls(context=context)
    client.ehlo()
PY
}

smtp_ca_verify() {
    e2e_validate_ca "$ca_cert" && e2e_validate_localhost_leaf "$ca_cert" "$smtp_cert" && smtp_starttls_verify
}

proxy_https_verify() {
    e2e_validate_localhost_leaf "$ca_cert" "$https_cert" && \
        curl --fail --silent --show-error --connect-timeout 2 --max-time 5 --cacert "$ca_cert" "https://localhost:${agent_port}/api/v1/health"
}

backend_smtp_env() {
    local pid entries expected key value found=0
    local expected_app_env=development
    local expected_origin="http://127.0.0.1:${browser_port}"
    local expected_mode=smtp
    local expected_host=localhost
    local expected_port="$smtp_port"
    local expected_sender=verification@localhost
    for pid in /proc/[0-9]*; do
        [ -r "$pid/cmdline" ] || continue
        if ! tr '\0' ' ' <"$pid/cmdline" 2>/dev/null | grep -Eq 'uvicorn .*app\.main:app'; then
            continue
        fi
        found=1
        entries=$(tr '\0' '\n' <"$pid/environ" 2>/dev/null | awk -F= '/^(APP_ENV|PUBLIC_ORIGIN|EMAIL_VERIFICATION_DELIVERY_MODE|SMTP_HOST|SMTP_PORT|SMTP_SENDER|SMTP_CA_FILE)=/{print}') || return 1
        for expected in \
            "APP_ENV=$expected_app_env" \
            "PUBLIC_ORIGIN=$expected_origin" \
            "EMAIL_VERIFICATION_DELIVERY_MODE=$expected_mode" \
            "SMTP_HOST=$expected_host" \
            "SMTP_PORT=$expected_port" \
            "SMTP_SENDER=$expected_sender"; do
            key=${expected%%=*}
            value=${expected#*=}
            [ "$(printf '%s\n' "$entries" | awk -F= -v key="$key" '$1 == key { print substr($0, index($0, "=") + 1); exit }')" = "$value" ] || return 1
        done
        value=$(printf '%s\n' "$entries" | awk -F= '$1 == "SMTP_CA_FILE" { print substr($0, index($0, "=") + 1); exit }')
        e2e_same_regular_file "$value" "$ca_cert" || return 1
    done
    [ "$found" -eq 1 ] || return 2
}

gate POSTGRES postgres_ready
gate MAILPIT_CONTAINER container_ready bots-central-v2-e2e-mailpit
gate MAILPIT_HTTP curl --fail --silent --show-error --connect-timeout 2 --max-time 5 "http://127.0.0.1:${mailpit_port}/api/v1/info"
gate SMTP_STARTTLS smtp_starttls_verify
gate SMTP_CA_VERIFY smtp_ca_verify
gate BACKEND curl --fail --silent --show-error --connect-timeout 2 --max-time 5 "$backend_url"
gate VITE curl --fail --silent --show-error --connect-timeout 2 --max-time 5 "$vite_url"
gate PROXY_HTTP curl --fail --silent --show-error --connect-timeout 2 --max-time 5 "http://127.0.0.1:${browser_port}/"
gate PROXY_HTTPS proxy_https_verify

if backend_smtp_env; then
    printf 'BACKEND_SMTP_ENV: OK\n'
else
    env_status=$?
    if [ "$env_status" -eq 2 ]; then
        printf 'BACKEND_SMTP_ENV: SKIP (no local Uvicorn app.main:app process found)\n'
    else
        printf 'BACKEND_SMTP_ENV: FAIL\n'
        failed=1
    fi
fi

if [ "$failed" -ne 0 ]; then
    printf 'E2E_PREFLIGHT: FAIL\n'
    exit 1
fi
printf 'E2E_PREFLIGHT: PASS\n'
