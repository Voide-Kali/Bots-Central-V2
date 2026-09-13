#!/usr/bin/env bash
# Starts only the named loopback-published E2E reverse proxy.
set -u

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
. "$repo_root/scripts/e2e/e2e-local-common.sh"
state_dir=${E2E_PROXY_STATE_DIR:-"$repo_root/.local/e2e-mailpit"}
container_name=bots-central-v2-e2e-proxy
image=caddy:2.11.4-alpine
browser_port=${E2E_BROWSER_PORT:-8080}
agent_port=${E2E_AGENT_HTTPS_PORT:-8443}

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
https_key="$state_dir/agent-https-key.pem"
https_csr="$state_dir/agent-https.csr"
https_cert="$state_dir/agent-https.pem"
https_ext="$state_dir/agent-https.ext"

if [ -e "$ca_key" ] || [ -e "$ca_cert" ]; then
    if [ ! -f "$ca_key" ] || [ ! -f "$ca_cert" ] || ! e2e_validate_ca "$ca_cert"; then
        e2e_certificate_recovery_hint "$state_dir"
        exit 1
    fi
fi
if [ ! -f "$ca_key" ]; then
    if ! openssl req -x509 -new -nodes -newkey rsa:3072 -sha256 -days 7 \
        -addext 'keyUsage=critical,keyCertSign,cRLSign' \
        -subj '/CN=Bots Central local E2E CA' -keyout "$ca_key" -out "$ca_cert" >/dev/null 2>&1; then
        printf 'Could not generate the local E2E CA.\n' >&2
        exit 1
    fi
fi
if [ -e "$https_key" ] || [ -e "$https_cert" ] || [ -e "$https_csr" ] || [ -e "$https_ext" ]; then
    if [ ! -f "$https_key" ] || [ ! -f "$https_cert" ] || [ ! -f "$https_csr" ] || [ ! -f "$https_ext" ]; then
        e2e_certificate_recovery_hint "$state_dir"
        exit 1
    fi
    if ! e2e_validate_localhost_leaf "$ca_cert" "$https_cert"; then
        e2e_certificate_recovery_hint "$state_dir"
        exit 1
    fi
else
    if ! openssl req -new -nodes -newkey rsa:3072 -subj '/CN=localhost' \
        -keyout "$https_key" -out "$https_csr" >/dev/null 2>&1; then
        printf 'Could not generate the local Agent HTTPS key.\n' >&2
        exit 1
    fi
    if ! printf '%s\n' 'basicConstraints=critical,CA:FALSE' 'keyUsage=critical,digitalSignature,keyEncipherment' 'extendedKeyUsage=serverAuth' 'subjectAltName=DNS:localhost,IP:127.0.0.1' >"$https_ext"; then
        printf 'Could not configure local Agent HTTPS certificate SANs.\n' >&2
        exit 1
    fi
    if ! openssl x509 -req -sha256 -days 7 -in "$https_csr" -CA "$ca_cert" \
        -CAkey "$ca_key" -CAcreateserial -extfile "$https_ext" -out "$https_cert" >/dev/null 2>&1; then
        printf 'Could not sign the local Agent HTTPS certificate.\n' >&2
        exit 1
    fi
fi
if ! chmod 600 "$ca_key" "$https_key" "$https_csr" "$https_ext" || ! chmod 644 "$ca_cert" "$https_cert"; then
    printf 'Could not secure local E2E certificate material.\n' >&2
    exit 1
fi
if ! e2e_validate_localhost_leaf "$ca_cert" "$https_cert"; then
    printf 'Local Agent HTTPS certificate does not validate against its local CA.\n' >&2
    exit 1
fi

caddyfile="$state_dir/Caddyfile"
if ! cat >"$caddyfile" <<'EOF'
{
    auto_https off
    admin off
}

http://127.0.0.1:8080 {
    @backend path /api/* /email-verification
    reverse_proxy @backend 127.0.0.1:8000
    reverse_proxy 127.0.0.1:5173
}

https://localhost:8443 {
    bind 127.0.0.1
    tls /certs/agent-https.pem /certs/agent-https-key.pem
    reverse_proxy 127.0.0.1:8000
}
EOF
then
    printf 'Could not write local proxy configuration.\n' >&2
    exit 1
fi
if ! chmod 600 "$caddyfile"; then
    printf 'Could not secure local proxy configuration.\n' >&2
    exit 1
fi

if ! sudo docker rm -f "$container_name" >/dev/null 2>&1; then :; fi
# The pinned official image marks /usr/bin/caddy with NET_BIND_SERVICE. Retain this one
# capability so exec succeeds under no-new-privileges, even though listeners are high ports.
if ! sudo docker run -d --name "$container_name" --restart=no --read-only \
    --tmpfs "/data:uid=$(id -u),gid=$(id -g),mode=0700" \
    --tmpfs "/config:uid=$(id -u),gid=$(id -g),mode=0700" \
    --cap-drop=ALL --cap-add=NET_BIND_SERVICE --security-opt no-new-privileges --user "$(id -u):$(id -g)" \
    --network host -v "$caddyfile:/etc/caddy/Caddyfile:ro" \
    -v "$https_cert:/certs/agent-https.pem:ro" -v "$https_key:/certs/agent-https-key.pem:ro" \
    "$image" caddy run --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null; then
    printf 'Could not start the local E2E proxy.\n' >&2
    exit 1
fi

if ! e2e_wait_for 'Caddy HTTP browser origin' "http://127.0.0.1:${browser_port}/" \
    curl --fail --silent --show-error --connect-timeout 2 --max-time 4 "http://127.0.0.1:${browser_port}/"; then
    exit 1
fi
if ! e2e_wait_for 'Caddy HTTP Backend health' "http://127.0.0.1:${browser_port}/api/v1/health" \
    curl --fail --silent --show-error --connect-timeout 2 --max-time 4 "http://127.0.0.1:${browser_port}/api/v1/health"; then
    exit 1
fi
if ! e2e_wait_for 'Caddy HTTPS Agent health' "https://localhost:${agent_port}/api/v1/health" \
    curl --fail --silent --show-error --connect-timeout 2 --max-time 4 --cacert "$ca_cert" "https://localhost:${agent_port}/api/v1/health"; then
    exit 1
fi

printf 'Browser origin: http://127.0.0.1:%s\n' "$browser_port"
printf 'Agent HTTPS origin: https://localhost:%s\n' "$agent_port"
printf 'Agent process trust: SSL_CERT_FILE=%s\n' "$ca_cert"
