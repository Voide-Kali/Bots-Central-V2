# Configuration reference

The Backend `Settings` model is the authority for these variables. Pydantic reads `backend/.env` when run from `backend/`; Docker Compose interpolates the repository-root `.env`. Neither requires nor recommends `source .env`.

| Variable | Required | Secret | Notes |
| --- | --- | --- | --- |
| `APP_ENV` | No | No | `development` (default), `test`, or `production`. |
| `APP_NAME`, `LOG_LEVEL`, `DEBUG` | No | No | `DEBUG=true` is rejected in production. |
| `DATABASE_URL` | Yes for a usable backend | Usually | PostgreSQL URL with host; never record a real password. |
| `PUBLIC_ORIGIN` | Required for web cookie/login and SMTP delivery | No | Absolute origin; production requires non-loopback HTTPS. |
| `TRUSTED_PROXY_IP` | Only behind one trusted proxy | No | A single IP; do not enable XFF trust without that proxy. |
| `ABUSE_CONTROL_HMAC_KEY` | Required in production; required for functional admission | Yes | Base64url random key of at least 32 bytes. |
| `ARGON2_MAX_CONCURRENCY` | No | No | Integer 1–16; default `2`. |
| `EMAIL_VERIFICATION_DELIVERY_MODE` | No | No | `disabled` default or `smtp`; production requires `smtp`. |
| `EMAIL_VERIFICATION_MATERIAL_TYPE` | No | No | `link` default or `code`. |
| `EMAIL_VERIFICATION_HMAC_ACTIVE_KEY_VERSION` | Required for code material | No | Active key name. |
| `EMAIL_VERIFICATION_HMAC_KEYS` | Required for code material | Yes | JSON object of key version to base64url 32-byte-or-longer secret. |
| `SMTP_HOST`, `SMTP_SENDER` | Required with SMTP | No | Delivery host and authorized sender. |
| `SMTP_PORT`, `SMTP_TIMEOUT_SECONDS` | No | No | Defaults `587` and `10`; bounded by settings. |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | Optional pair | Password is secret | Password is required when username is present. |
| `SMTP_CA_FILE` | Optional | No | Absolute PEM bundle of additional SMTP CA roots; system trust remains enabled. |

## Modes

**Health-only local development:** `APP_ENV=development`, a reachable `DATABASE_URL`, and optional name/log level allow health, migrations and ordinary backend startup. It does not configure registration delivery or the shared limiter, so auth issuance can return `503` by design.

**Functional local MVP-1:** configure `PUBLIC_ORIGIN`, a generated `ABUSE_CONTROL_HMAC_KEY`, `EMAIL_VERIFICATION_DELIVERY_MODE=smtp`, SMTP host/sender and, for code material, the HMAC keyring. The committed [local E2E](LOCAL_E2E.md) uses `link` material and Mailpit; it generates its abuse key per process and does not persist it.

**Production:** this repository has no supported production deployment baseline. Settings nevertheless enforce production restrictions: no debug, SMTP delivery, secure non-loopback HTTPS `PUBLIC_ORIGIN`, and a valid abuse-control HMAC key. Treat all secrets as environment-managed values outside Git and images.

## Compose variables

The root `.env.example` supplies `POSTGRES_DB`, `POSTGRES_USER` and `POSTGRES_PASSWORD` for `compose.yaml`. Its `DATABASE_URL` is for local direct backend use and is not injected verbatim into Compose: Compose builds its backend URL against service hostname `db`.
