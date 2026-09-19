# Architecture

Bots Central V2 MVP-1 is a modular monolith: the Backend owns API rules and PostgreSQL is the authority for security and device state.

```text
Browser
  | HTTPS / same-origin
  v
Frontend (React / TypeScript / Vite)
  | /api/v1
  v
Backend (FastAPI)
  |
  v
PostgreSQL

Linux Agent (Go)
  | HTTPS + Ed25519 JWS
  v
Backend Device API
```

## Current boundaries

- **Authentication boundary:** registration, email verification, login, refresh, logout and `auth/me` are served by FastAPI. PostgreSQL validates account/session/security state on protected requests. Browser refresh endpoints require the same-origin cookie boundary; the web access token remains in memory.
- **Device boundary:** an authenticated owner creates a one-time pairing token. The Agent proves possession of its Ed25519 key at enrollment. The owner compares and posts the fingerprint to approve or reject the pending device.
- **Heartbeat boundary:** the Agent sends an EdDSA JWS through HTTPS. Backend verifies the enrolled public key and a strictly increasing durable sequence. PostgreSQL timestamps `last_seen_at`; `active` plus a recent accepted heartbeat derives presence.
- **Data boundary:** neither Browser nor Agent accesses PostgreSQL directly. Token and pairing plaintext are not persisted; digests are stored where required.

## Current components

The backend has API, core, auth and database modules. The frontend implements account flows and Device Center. The Linux Agent implements the frozen Device Online V0.1 contract. See [AUTH](AUTH.md) and [DEVICE_ONLINE_V01](DEVICE_ONLINE_V01.md).

## Planned, not current

Security Gate execution, Task Engine, Lock PC and every remote control capability remain unimplemented. Flutter mobile, Desktop Companion, Windows Agent, mTLS and production deployment architecture are also future work. These are not implied by the MVP-1 Agent or Device Center.
