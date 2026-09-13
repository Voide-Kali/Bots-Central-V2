# Local MVP-1 E2E harness

Browser access is `http://127.0.0.1:8080`; Agent access is `https://localhost:8443`.
Backend, Vite, and Caddy listeners remain loopback-only. Caddy uses host networking because this
host has demonstrated unreliable Docker bridge-to-host forwarding; do not substitute
`host.docker.internal` without new evidence. The Caddy container is non-root and read-only, drops
all capabilities except its single `NET_BIND_SERVICE` requirement (the pinned official image carries
that file capability), and uses owner-only tmpfs directories for runtime data.

The ignored E2E CA and separate SMTP/HTTPS leaf keys live in `.local/e2e-mailpit`. Nothing requires
installing that CA in the global OS trust store. `SSL_CERT_FILE` is process-scoped and belongs only
on the Agent process.

## Live validation

MVP-1 passed locally on 2026-09-13 with the PostgreSQL test container, Mailpit STARTTLS with the
verified local CA, loopback Caddy, and Linux Agent `PC000`: register `202`, email verification
`200`, login `200`, `auth/me` `200`, pairing `201`, enrollment `201`, expected pending heartbeat
`403`, explicit approval `200`, and active heartbeat `200`. The local and Device Center fingerprints matched; the
final Device Center state was `TOTAL 1`, `ONLINE 1`, `PENDENTES 0`, `PC000 ACTIVE / Online`.

## Reboot procedure

Use separate terminals and stop at the first failing gate.

1. Start PostgreSQL and Mailpit:

   ```bash
   cd ~/Bots-Central-V2
   sudo docker start bots-central-v2-pg17-test
   scripts/e2e/mailpit-local.sh
   ```

2. Start Backend with the dedicated test database and SMTP environment. Keep database credentials
   in shell variables; do not print or save them. It binds only to loopback.

   ```bash
   cd ~/Bots-Central-V2
   e2e_env() { sudo docker inspect bots-central-v2-pg17-test --format '{{range .Config.Env}}{{println .}}{{end}}' | awk -F= -v name="$1" '$1 == name { print substr($0, index($0, "=") + 1); exit }'; }
   export E2E_DB_USER="$(e2e_env POSTGRES_USER)" E2E_DB_NAME="$(e2e_env POSTGRES_DB)" E2E_DB_PASSWORD="$(e2e_env POSTGRES_PASSWORD)"
   export E2E_DB_PASSWORD_ESCAPED="$(python3 -c 'import os, urllib.parse; print(urllib.parse.quote(os.environ["E2E_DB_PASSWORD"], safe=""))')"
   export DATABASE_URL="postgresql+psycopg://${E2E_DB_USER}:${E2E_DB_PASSWORD_ESCAPED}@127.0.0.1:55432/${E2E_DB_NAME}"
   cd backend
   export APP_ENV=development PUBLIC_ORIGIN=http://127.0.0.1:8080
   export EMAIL_VERIFICATION_DELIVERY_MODE=smtp SMTP_HOST=localhost SMTP_PORT=1025 SMTP_SENDER=verification@localhost
   export SMTP_CA_FILE="$PWD/../.local/e2e-mailpit/smtp-ca.pem"
   export ABUSE_CONTROL_HMAC_KEY="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=\n')"
   PYTHONPATH=. .venv/bin/alembic upgrade head
   PYTHONPATH=. .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
   ```

3. Start Vite on loopback:

   ```bash
   cd ~/Bots-Central-V2/frontend
   npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
   ```
4. Start the proxy only after both upstreams are ready:

   ```bash
   cd ~/Bots-Central-V2
   scripts/e2e/proxy-local.sh
   scripts/e2e/preflight-local.sh
   ```

   Continue only if the final line is `E2E_PREFLIGHT: PASS`. The preflight checks PostgreSQL,
   Mailpit HTTP, SMTP STARTTLS with `CERT_REQUIRED` and hostname validation, Backend, Vite, Caddy
   HTTP, Caddy HTTPS, and the safe subset of a matching Uvicorn environment. It never prints
   database URLs, passwords, tokens, keys, or HMAC material.

5. Generate a distinct recipient only after preflight passes:

   ```bash
   TEST_EMAIL="$(scripts/e2e/new-test-email.sh)"
   printf '%s\n' "$TEST_EMAIL"
   ```

   Register with that address. A register response of `202` is intentionally generic and does not
   prove that a new account or email was created. Do not reuse an E2E address.
6. Wait only for that recipient's message, without printing its body, link, or verification token:

   ```bash
   scripts/e2e/mailpit-find-verification.py --wait-seconds 30 "$TEST_EMAIL"
   ```

   Open the loopback Mailpit UI, inspect that message, use the real link, verify the account, then
   log in. Confirm `GET /auth/me` returns `200`.
7. Open Device Center and create a pairing session; confirm its `201` response. Pairing tokens are
   single-use: never reuse them and never place one in argv, config, files, or shell history.
8. Build and start the Agent with a fresh owner-only state directory. `-pairing-token-stdin` reads
   exactly one line and proceeds immediately after Enter; pipe input also works. Keep
   `SSL_CERT_FILE` on this Agent command only.

   ```bash
   cd ~/Bots-Central-V2/agent
   go build -o ../.local/bots-central-agent ./cmd/bots-central-agent
   ../scripts/e2e/agent-config-local.sh "$PWD/../.local/e2e-agent.json" "$PWD/../.local/e2e-agent-state"
   your-approved-secret-input-command | SSL_CERT_FILE="$PWD/../.local/e2e-mailpit/smtp-ca.pem" ../.local/bots-central-agent -config "$PWD/../.local/e2e-agent.json" -pairing-token-stdin
   ```

9. Record only timestamps and HTTP statuses as evidence: registration `202`, login `200`,
   `/auth/me` `200`, pairing `201`, enrollment `201`, and heartbeat `200`. Never record a password,
   pairing token, access/refresh token, verification token, private key, `DATABASE_URL`, or
   `ABUSE_CONTROL_HMAC_KEY`.
10. Confirm the enrolled device is `PENDING`, compare the full local and server `SHA256:`
    fingerprints byte-for-byte, then perform approval as a human action. Confirm the Agent observes
    approval, its heartbeat succeeds, the device becomes `ACTIVE`, and Device Center displays
    `TOTAL 1`, `ONLINE 1`, `PENDENTES 0`.

If a certificate bundle is invalid, scripts refuse to replace it. Preserve/rename only
`.local/e2e-mailpit` and rerun the relevant harness script to regenerate that bundle; never remove
Agent state, PostgreSQL data, or volumes.

## Cleanup

```bash
scripts/e2e/proxy-cleanup.sh
scripts/e2e/mailpit-cleanup.sh
```

These remove only named harness containers, never PostgreSQL or volumes.
