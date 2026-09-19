# Local MVP-1 E2E

This Linux-only runbook reproduces the MVP-1 flow locally: register → verify → login → `auth/me` → pairing → Linux Agent enrollment → pending → fingerprint comparison → approval → signed heartbeat → Device Center online. It uses loopback listeners and development certificates only; it is not a deployment guide.

## Select the real clone

In every terminal used below, set the root of the real product clone (not a documentation worktree) and enter it before using relative paths:

```bash
REPO_ROOT="$HOME/Bots-Central-V2"
cd "$REPO_ROOT"
```

## Prerequisites

Install Python 3.12+, Go 1.22+, Node/npm, Docker, `sudo`, `curl`, `openssl`, `git` and `realpath`. Docker commands below use `sudo docker`; do not add users to the Docker group as a workaround. Confirm the daemon before continuing:

```bash
sudo docker info >/dev/null
```

## Create the dedicated PostgreSQL test container

The backend test fixtures intentionally accept only database name `bots_central_test`. Choose a local password without echoing it, then create the named loopback-only container once. Do not use this database for anything else.

```bash
E2E_DB_PASSWORD="$(
python3 - <<'PY'
import getpass
print(getpass.getpass("Local E2E PostgreSQL password: "))
PY
)"
sudo docker run -d --name bots-central-v2-pg17-test --restart=no \
  -p 127.0.0.1:55432:5432 \
  -e POSTGRES_DB=bots_central_test \
  -e POSTGRES_USER=bots_central_test \
  -e POSTGRES_PASSWORD="$E2E_DB_PASSWORD" \
  postgres:17-alpine
unset E2E_DB_PASSWORD
```

Wait until it is healthy enough to accept connections:

```bash
attempt=1
while ! sudo docker exec bots-central-v2-pg17-test pg_isready -U bots_central_test -d bots_central_test >/dev/null 2>&1; do
  if [ "$attempt" -ge 30 ]; then
    printf '%s\n' 'PostgreSQL did not become ready within 30 seconds.' >&2
    exit 1
  fi
  attempt=$((attempt + 1))
  sleep 1
done
```

On a reboot, use `sudo docker start bots-central-v2-pg17-test`. If it already exists, do not recreate it merely to rerun E2E.

## Prepare dependencies

```bash
REPO_ROOT="$HOME/Bots-Central-V2"
cd "$REPO_ROOT/backend"
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock

cd ../frontend
npm ci
```

## Start order

Use separate terminals and stop at the first failed gate.

1. Start local Mailpit. It generates ignored owner-only CA/key files in `.local/e2e-mailpit`, publishes only loopback ports, and requires STARTTLS.

   ```bash
   REPO_ROOT="$HOME/Bots-Central-V2"
   cd "$REPO_ROOT"
   scripts/e2e/mailpit-local.sh
   ```

2. Start Backend on loopback. Retrieve test credentials only into shell variables; never print them, save them, or commit them. The temporary abuse-control key exists only in this process.

   ```bash
   REPO_ROOT="$HOME/Bots-Central-V2"
   cd "$REPO_ROOT"
   e2e_env() { sudo docker inspect bots-central-v2-pg17-test --format '{{range .Config.Env}}{{println .}}{{end}}' | awk -F= -v name="$1" '$1 == name { print substr($0, index($0, "=") + 1); exit }'; }
   export E2E_DB_USER="$(e2e_env POSTGRES_USER)" E2E_DB_NAME="$(e2e_env POSTGRES_DB)" E2E_DB_PASSWORD="$(e2e_env POSTGRES_PASSWORD)"
   export E2E_DB_PASSWORD_ESCAPED="$(python3 -c 'import os, urllib.parse; print(urllib.parse.quote(os.environ["E2E_DB_PASSWORD"], safe=""))')"
   export DATABASE_URL="postgresql+psycopg://${E2E_DB_USER}:${E2E_DB_PASSWORD_ESCAPED}@127.0.0.1:55432/${E2E_DB_NAME}"
   export APP_ENV=development PUBLIC_ORIGIN=http://127.0.0.1:8080
   export EMAIL_VERIFICATION_DELIVERY_MODE=smtp SMTP_HOST=localhost SMTP_PORT=1025 SMTP_SENDER=verification@localhost
   export SMTP_CA_FILE="$PWD/.local/e2e-mailpit/smtp-ca.pem"
   export ABUSE_CONTROL_HMAC_KEY="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=\n')"
   cd backend
   PYTHONPATH=. .venv/bin/alembic upgrade head
   PYTHONPATH=. .venv/bin/uvicorn app.main:app \
     --host 127.0.0.1 \
     --port 8000 \
     --no-proxy-headers
   ```

3. Start Vite on loopback.

   ```bash
   REPO_ROOT="$HOME/Bots-Central-V2"
   cd "$REPO_ROOT/frontend"
   npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
   ```

4. Start the versioned Caddy harness, then preflight. Browser origin is `http://127.0.0.1:8080`; Agent origin is `https://localhost:8443`.

   ```bash
   REPO_ROOT="$HOME/Bots-Central-V2"
   cd "$REPO_ROOT"
   scripts/e2e/proxy-local.sh
   scripts/e2e/preflight-local.sh
   ```

   Continue only after `E2E_PREFLIGHT: PASS`. It checks PostgreSQL, Mailpit, STARTTLS validation, Backend, Vite, Caddy HTTP/HTTPS and the safe subset of the Uvicorn environment.

## Live flow

1. Create one recipient after preflight; never reuse it.

   ```bash
   TEST_EMAIL="$(scripts/e2e/new-test-email.sh)"
   printf '%s\n' "$TEST_EMAIL"
   ```

2. In the Browser origin, register that email. Wait for only that recipient with `scripts/e2e/mailpit-find-verification.py --wait-seconds 30 "$TEST_EMAIL"`; inspect the local Mailpit UI, open the real verification link and log in. Confirm `auth/me` returns `200`.
3. Open Device Center, create a pairing session, and keep its token out of argv, files, config, shell history and logs.
4. Build and start a fresh Agent state. The Agent CA is process-scoped; do not install the development CA globally.

   ```bash
   REPO_ROOT="$HOME/Bots-Central-V2"
   cd "$REPO_ROOT/agent"
   go build -o ../.local/bots-central-agent ./cmd/bots-central-agent
   ../scripts/e2e/agent-config-local.sh "$PWD/../.local/e2e-agent.json" "$PWD/../.local/e2e-agent-state"
   SSL_CERT_FILE="$PWD/../.local/e2e-mailpit/smtp-ca.pem" ../.local/bots-central-agent \
     -config "$PWD/../.local/e2e-agent.json" \
     -pairing-token-stdin
   ```

   When prompted in that terminal, paste the pairing token displayed by Device Center and press Enter. The Agent reads exactly one line and continues. Do not pass the token in argv, configuration, a file, or shell history.

5. Confirm the device is pending, compare the complete `SHA256:` Agent and Device Center fingerprints byte-for-byte, then approve it as a human action. Verify a subsequent heartbeat succeeds and Device Center shows `ACTIVE / Online`.

Record only timestamps and statuses. Never record passwords, database URLs, HMAC keys, pairing/verification/access/refresh tokens, or private keys.

## Cleanup and reboot

```bash
REPO_ROOT="$HOME/Bots-Central-V2"
cd "$REPO_ROOT"
scripts/e2e/proxy-cleanup.sh
scripts/e2e/mailpit-cleanup.sh
```

These remove only their named harness containers. They do not remove PostgreSQL or volumes. On reboot, start the PostgreSQL container, repeat Mailpit → Backend → Vite → proxy → preflight. Do not casually remove Agent state: it contains the device identity and durable sequence.

## Troubleshooting

Use [Troubleshooting](TROUBLESHOOTING.md) for Docker, port, migration, SMTP/CA, Caddy, pairing, Agent state and heartbeat failures. Do not bypass TLS validation, Origin checks, fingerprint comparison or file permissions to make E2E pass.
