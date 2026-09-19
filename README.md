# Bots Central V2

Bots Central V2 is a device-management platform. The MVP-1 snapshot provides a web account flow and a deliberately narrow Linux Device Online flow: a person creates a one-time pairing token in the web UI, compares an Agent fingerprint, and explicitly approves the enrolled device. It is not a remote-control product.

**Snapshot:** `mvp1/integration` at `efbec158059995a1069119084fd5e29eedc3f64a`. MVP-1 live E2E validation passed locally on 2026-09-13. A separate post-review hardening branch exists and is not part of this snapshot.

## Components

- **Backend:** FastAPI modular monolith, PostgreSQL and Alembic.
- **Web:** React, TypeScript and Vite, used in a same-origin topology.
- **Linux Agent:** Go process with a local Ed25519 identity and signed heartbeats.

See [Architecture](docs/ARCHITECTURE.md) for boundaries and data flow.

## Product status

| Area | Status | Notes |
| --- | --- | --- |
| Registration, email verification and login | Implemented | PostgreSQL-backed account flow. |
| Server-side sessions and opaque tokens | Implemented | Access token in web memory; refresh cookie rotates server-side. |
| Device Center and owner-scoped device list | Implemented | Browser UI uses the same-origin API. |
| Linux Agent enrollment and Device Online | Implemented | One-time pairing, Ed25519 proof, fingerprint approval and heartbeat. |
| MVP-1 hardening/documentation review | In progress | Tracked separately; not asserted as merged here. |
| Security Gate, Task Engine and Lock PC | Planned MVP-2 | Not available in MVP-1. |
| Remote actions, file transfer, webcam, shutdown/restart | Future / unavailable | No remote command execution exists. |
| Flutter mobile, Desktop Companion, Windows Agent | Future / unavailable | Not shipped in this snapshot. |
| Telegram, Nmap, arbitrary shell, remote software installation | Explicitly not part of V2 | Not supported features. |

## Requirements

- Docker Compose for the health-only stack.
- Python 3.12+ for backend development; CI uses Python 3.13.
- Node.js/npm for the web client.
- Go 1.22+ for the Linux Agent.
- For the local E2E harness: Linux, Docker usable through `sudo docker`, `curl`, `openssl`, and `git`.

## Quick start

### A. Health-only Compose stack

This starts PostgreSQL, runs migrations, and exposes the backend health endpoint. It does **not** start the frontend, SMTP capture, Caddy proxy, or Agent; registration and login are not a configured functional flow in this mode.

```bash
cp .env.example .env
# Set a unique local-only POSTGRES_PASSWORD before starting it.
# On the validated Kali host, use its approved Docker authorization:
sudo docker compose up --build
```

Open `http://localhost:8000/api/v1/health`. Use Docker authorization appropriate to the host; the validated Kali runbook uses `sudo docker` and does not recommend adding a user to the Docker group. Compose reads `.env`; do not use `source .env`. The example is local-development-only and must not be deployed.

### B. Functional MVP-1 local E2E

Use the reproducible [local E2E runbook](docs/LOCAL_E2E.md). It starts the dedicated test PostgreSQL container, local Mailpit with STARTTLS, backend, Vite, a loopback Caddy harness, and the Linux Agent. It includes the complete registration → verify → login → pairing → fingerprint approval → online-device flow.

## Development checks

```bash
# backend, from backend/
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock
pytest

# frontend, from frontend/
npm ci
npm test
npm run lint
npm run typecheck
npm run build

# Agent, from agent/
go test ./...
go test -race ./...
go vet ./...
```

PostgreSQL integration tests require `TEST_DATABASE_URL` pointing only to the dedicated `bots_central_test` database; see [LOCAL_E2E](docs/LOCAL_E2E.md).

## Documentation

- [Current state](docs/CURRENT_STATE.md), [product capabilities](docs/PRODUCT.md), and [architecture](docs/ARCHITECTURE.md)
- [Backend operation](backend/README.md), [authentication](docs/AUTH.md), and [database](docs/DATABASE.md)
- [Configuration reference](docs/CONFIGURATION.md) and [Device Online contract](docs/DEVICE_ONLINE_V01.md)
- [Local E2E](docs/LOCAL_E2E.md), [troubleshooting](docs/TROUBLESHOOTING.md), and [release checklist](docs/RELEASE_CHECKLIST.md)
- [Security model](docs/SECURITY_MODEL.md) and [security limitations](docs/SECURITY_LIMITATIONS.md)

## Security and limitations

Do not commit `.env`, credentials, pairing tokens, private keys, or connection strings. Report vulnerabilities through the private maintainer channel in [SECURITY.md](SECURITY.md). MVP-1 limitations—including the absence of remote actions and production deployment certification—are documented in [Security limitations](docs/SECURITY_LIMITATIONS.md).
