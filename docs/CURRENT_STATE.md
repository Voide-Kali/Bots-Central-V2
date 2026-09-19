# Current State

## Snapshot

This document describes `mvp1/integration` at `efbec158059995a1069119084fd5e29eedc3f64a`. It is the documentation/release-readiness baseline, not a claim about later branches. Post-review hardening is tracked separately and is not integrated into this snapshot.

## Implemented

- FastAPI modular monolith, PostgreSQL, Alembic migrations `0001` through `0006`, Docker health-only stack and CI.
- Registration, email verification, Argon2id password handling, PostgreSQL abuse control, login, opaque access tokens, rotating refresh tokens, server-side sessions, logout and `auth/me`.
- React/TypeScript/Vite web client with same-origin API use, memory-only access token handling, account flows and Device Center.
- Linux Go Agent with local Ed25519 identity, protected local state, stdin-only pairing token input, enrollment, signed heartbeat, TLS verification and durable sequence.
- Device Online: owner-scoped device list, one-time session-bound pairing, enrollment proof, fingerprint comparison, explicit approve/reject, pending-by-default lifecycle and server-derived online/offline presence.

## Validated

- MVP-1 live local E2E passed on 2026-09-13: register `202` → email verification `200` → login `200` → `auth/me` `200` → pairing `201` → enrollment `201` → pending heartbeat `403` → fingerprint approval `200` → active heartbeat `200`; Device Center showed one active online device.
- Recorded baseline: Backend 338 passed with 86% coverage; Frontend 47 tests plus lint, typecheck and build; Agent `go test ./...`, race test and vet; remote CI green; E2E preflight passed.

## Known limitations

- No Security Gate executor, Task Engine, Lock PC, remote commands, shutdown/restart, webcam, file transfer, arbitrary shell, software installation, Nmap or Telegram integration.
- No Windows Agent, mobile app, Desktop Companion, complete signed auto-update, complete recovery, mTLS, hardware attestation, tamper-proof external audit, supported production deployment baseline, or complete backup/restore procedure.
- A device key proves control of that key, not that its operating system is honest. Email verification is not strong MFA.

## In progress

MVP-1 documentation/release readiness and post-review hardening are separate review tracks. The local E2E runbook is clone-path independent and specifies explicit backend virtual-environment executables for separate terminals; its documentation corrections do not represent hardening as merged into this frozen snapshot. Neither review track is represented as merged until reviewed.

## Next milestone

MVP-2 remains design work: a Security Gate, Task Engine and Lock PC require explicit contracts, authorization, audit and operational decisions before implementation.

## Historical validation log

Earlier phase-by-phase notes are intentionally not repeated here. They are superseded by this snapshot summary; use Git history when an earlier validation record is needed.
