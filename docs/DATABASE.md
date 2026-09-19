# Database

PostgreSQL is the authoritative MVP-1 datastore. Clients and Agents never connect to it directly. Alembic migrations are ordered and the current head is `0006_device_online_v01`.

## Migration summary

| Revision | Scope |
| --- | --- |
| `0001_foundation` | Initial PostgreSQL foundation. |
| `0002_auth_database_foundation` | Accounts, email identities, password credentials, sessions and token persistence. |
| `0003_email_verification_challenge_foundation` | Email verification challenges and material constraints. |
| `0004_auth_abuse_control` | PostgreSQL-backed abuse-control buckets. |
| `0005_device_foundation` | Device lifecycle foundation. |
| `0006_device_online_v01` | Pairing, Agent public-key identity, heartbeat sequence and presence data. |

## Main data

| Entity | Responsibility and sensitive-data rule |
| --- | --- |
| `users`, `user_emails`, `password_credentials` | Account state, canonical email and Argon2id password hash. No plaintext password. |
| `sessions`, `access_tokens`, `refresh_tokens` | Server-side session state plus SHA-256 token digests, expiry, revocation and refresh-family rotation. No raw access or refresh token. |
| `email_verification_challenges` | Single-use email-link/code material stored as digest/HMAC-derived material, with consumption and invalidation state. HMAC keys remain outside PostgreSQL. |
| `auth_abuse_buckets` | Shared rate-limit state keyed by pseudonymized inputs; it is not an authentication credential store. |
| `devices` | Owner-scoped device identity, lifecycle, Ed25519 public key/fingerprint, agent metadata, heartbeat sequence and server-derived `last_seen_at`. |
| Device pairing records | One-time, short-lived pairing-token digest bound to the initiating user/session and consumed atomically by enrollment. No raw pairing token is persisted. |

## Device Online invariants

Enrollment creates a `pending` device only after valid Ed25519 proof of possession. Its enrolled public key and canonical `SHA256:` fingerprint are immutable. Only the owner can approve or reject while posting the displayed fingerprint. A heartbeat must have the enrolled key, exact protocol audience/device subject and a strictly increasing unsigned-64-bit sequence. PostgreSQL supplies the accepted timestamp; an active device with an accepted beat in the last 90 seconds is online.

## Operational notes

Run `PYTHONPATH=. alembic upgrade head` from `backend/`. Integration fixtures deliberately require `TEST_DATABASE_URL` to name `bots_central_test` because they exercise migrations. Database availability is part of the security boundary: protected operations and shared admission fail safely rather than using a permissive cache.

This snapshot has no complete backup/restore or production deployment procedure. See [Configuration](CONFIGURATION.md), [AUTH](AUTH.md), and [Device Online](DEVICE_ONLINE_V01.md).
