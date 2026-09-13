#!/usr/bin/env bash
# Starts only the named, loopback-bound local SMTP capture harness.
set -u

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
. "$repo_root/scripts/e2e/e2e-local-common.sh"
state_dir=${E2E_MAILPIT_STATE_DIR:-"$repo_root/.local/e2e-mailpit"}
container_name=bots-central-v2-e2e-mailpit
image=axllent/mailpit:v1.30.6
smtp_port=${E2E_MAILPIT_SMTP_PORT:-1025}
ui_port=${E2E_MAILPIT_UI_PORT:-8025}

for required in openssl sudo docker curl; do
    if ! command -v "$required" >/dev/null 2>&1; then
        printf 'Missing required command: %s\n' "$required" >&2
        exit 1
    fi
done

umask 077
if ! mkdir -p "$state_dir" || ! chmod 700 "$state_dir"; then
    printf 'Could not create and secure local harness state directory.\n' >&2
    exit 1
fi

ca_key="$state_dir/smtp-ca-key.pem"
ca_cert="$state_dir/smtp-ca.pem"
server_key="$state_dir/smtp-server-key.pem"
server_csr="$state_dir/smtp-server.csr"
server_cert="$state_dir/smtp-server.pem"
server_ext="$state_dir/smtp-server.ext"

if [ -e "$ca_key" ] || [ -e "$ca_cert" ]; then
    if [ ! -f "$ca_key" ] || [ ! -f "$ca_cert" ] || ! e2e_validate_ca "$ca_cert"; then
        e2e_certificate_recovery_hint "$state_dir"
        exit 1
    fi
fi
if [ ! -f "$ca_key" ]; then
    if ! openssl req -x509 -new -nodes -newkey rsa:3072 -sha256 -days 7 \
        -addext 'keyUsage=critical,keyCertSign,cRLSign' \
        -subj '/CN=Bots Central local SMTP CA' -keyout "$ca_key" -out "$ca_cert" >/dev/null 2>&1; then
        printf 'Could not generate the local SMTP CA.\n' >&2
        exit 1
    fi
fi
if [ -e "$server_key" ] || [ -e "$server_cert" ] || [ -e "$server_csr" ] || [ -e "$server_ext" ]; then
    if [ ! -f "$server_key" ] || [ ! -f "$server_cert" ] || [ ! -f "$server_csr" ] || [ ! -f "$server_ext" ]; then
        e2e_certificate_recovery_hint "$state_dir"
        exit 1
    fi
    if ! e2e_validate_localhost_leaf "$ca_cert" "$server_cert"; then
        e2e_certificate_recovery_hint "$state_dir"
        exit 1
    fi
else
    if ! openssl req -new -nodes -newkey rsa:3072 -subj '/CN=localhost' \
        -keyout "$server_key" -out "$server_csr" >/dev/null 2>&1; then
        printf 'Could not generate the local SMTP server key.\n' >&2
        exit 1
    fi
    if ! printf '%s\n' 'basicConstraints=critical,CA:FALSE' 'keyUsage=critical,digitalSignature,keyEncipherment' 'extendedKeyUsage=serverAuth' 'subjectAltName=DNS:localhost,IP:127.0.0.1' >"$server_ext"; then
        printf 'Could not configure local SMTP certificate SANs.\n' >&2
        exit 1
    fi
    if ! openssl x509 -req -sha256 -days 7 -in "$server_csr" -CA "$ca_cert" \
        -CAkey "$ca_key" -CAcreateserial -extfile "$server_ext" -out "$server_cert" >/dev/null 2>&1; then
        printf 'Could not sign the local SMTP server certificate.\n' >&2
        exit 1
    fi
fi
if ! chmod 600 "$ca_key" "$server_key" "$server_csr" "$server_ext" || ! chmod 644 "$ca_cert" "$server_cert"; then
    printf 'Could not secure local SMTP private material.\n' >&2
    exit 1
fi

if ! sudo docker rm -f "$container_name" >/dev/null 2>&1; then :; fi
if ! sudo docker run -d --name "$container_name" --restart=no --read-only --tmpfs /tmp \
    --user "$(id -u):$(id -g)" \
    --cap-drop=ALL --security-opt no-new-privileges \
    -p "127.0.0.1:${smtp_port}:1025" \
    -p "127.0.0.1:${ui_port}:8025" \
    -v "$server_cert:/smtp-server.pem:ro" \
    -v "$server_key:/smtp-server-key.pem:ro" \
    "$image" \
    --smtp-tls-cert /smtp-server.pem \
    --smtp-tls-key /smtp-server-key.pem \
    --smtp-require-starttls >/dev/null; then
    printf 'Could not start the local Mailpit harness.\n' >&2
    exit 1
fi

if ! e2e_wait_for 'Mailpit HTTP UI' "http://127.0.0.1:${ui_port}/api/v1/info" \
    curl --fail --silent --show-error --connect-timeout 2 --max-time 4 "http://127.0.0.1:${ui_port}/api/v1/info"; then
    exit 1
fi
if ! e2e_validate_localhost_leaf "$ca_cert" "$server_cert" || ! openssl s_client \
    -connect "127.0.0.1:${smtp_port}" -starttls smtp -CAfile "$ca_cert" \
    -verify_return_error -verify_hostname localhost </dev/null >/dev/null 2>&1; then
    printf 'Mailpit STARTTLS verification failed.\n' >&2
    exit 1
fi

printf 'Mailpit SMTP: 127.0.0.1:%s (STARTTLS required)\n' "$smtp_port"
printf 'Mailpit UI/API: http://127.0.0.1:%s\n' "$ui_port"
printf 'SMTP_CA_FILE=%s\n' "$ca_cert"
