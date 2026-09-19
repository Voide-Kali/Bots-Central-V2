# Backend

The Backend is the FastAPI modular monolith for Bots Central V2 MVP-1. PostgreSQL is authoritative for accounts, sessions, token digests, abuse-control state, device lifecycle and Device Online presence. Alembic owns schema migrations.

Implemented API areas include health, registration/email verification, login/refresh/logout/`auth/me`, owner-scoped device listing, pairing, enrollment, fingerprint approval/reject and signed heartbeat. Routes are versioned below `/api/v1`.

## Local setup

Requires Python 3.12+ (CI uses 3.13) and PostgreSQL for integration tests.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock
cp .env.example .env
```

Pydantic reads `backend/.env` when the process is run from this directory. Do not use `source .env`; use environment management appropriate to the host. The provided example is enough for a health-only local backend when its PostgreSQL URL is reachable, not for a functional email-registration flow. See [configuration](../docs/CONFIGURATION.md).

Run migrations and the loopback development server:

```bash
PYTHONPATH=. alembic upgrade head
PYTHONPATH=. uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

## Checks

```bash
ruff check .
mypy app tests
pytest
python -m pip check
pip-audit -r requirements.lock --vulnerability-service osv
```

Set `TEST_DATABASE_URL` only to the dedicated database named `bots_central_test` before running the full PostgreSQL integration suite; its fixtures run migrations. The [local E2E guide](../docs/LOCAL_E2E.md) creates the expected local container.

## Security notes

The backend stores digests rather than plaintext access, refresh and pairing tokens. Browser refresh endpoints require the same-origin cookie boundary; device enrollment uses a pairing token and proof of possession, while heartbeats are Ed25519 JWSs. Production startup has additional configuration requirements. Consult [AUTH](../docs/AUTH.md), [DATABASE](../docs/DATABASE.md), [Device Online](../docs/DEVICE_ONLINE_V01.md), and [security limitations](../docs/SECURITY_LIMITATIONS.md).
