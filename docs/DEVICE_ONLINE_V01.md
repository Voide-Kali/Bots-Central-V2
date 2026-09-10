# Device Online V0.1 (Backend contract)

`POST /api/v1/devices/pairings` requires a current user access token and returns a
one-time, 256-bit base64url pairing token. The Backend persists only its SHA-256
digest, binds it to that user and initiating server session, and expires it after
five minutes. Pairing responses are `no-store`.

`POST /api/v1/devices/enrollments` accepts the pairing token, a raw 32-byte
Ed25519 public key encoded as canonical unpadded base64url, a compact EdDSA JWS
proof, and only `name`, `platform`, and optional `agent_version`. The proof has
`aud` `bots-central:enrollment:v1`, a string `sub`, and the exact
`pairing_token` claim. Atomic consumption creates a Backend UUID device in
`pending` state. Its public key and SHA-256 fingerprint (`SHA256:<base64url>`)
are immutable.

The owner confirms or rejects a pending device by posting the displayed
fingerprint to `/api/v1/devices/{device_id}/approve` or `/reject`. Only approval
changes lifecycle to `active`; reject revokes the device.

`POST /api/v1/devices/{device_id}/heartbeat` accepts `{ "jws": "..." }`.
The JWS is verified only as `alg=EdDSA`, with the enrolled Ed25519 public key,
exact `aud` `bots-central:heartbeat:v1`, matching UUID `sub`, and an integer
`seq` in `[0, 2^64-1]`. The Backend atomically accepts only a strictly increasing
sequence, then sets `last_seen_at` from PostgreSQL `clock_timestamp()`.
Agent timestamps are not presence authority. `active` plus a valid accepted beat
within 90 seconds is `online`; lifecycle and presence remain independent.

Pending devices receive `403 DEVICE_PENDING`; revoked devices receive
`403 DEVICE_REVOKED`; replay/stale sequence receives `409 STALE_HEARTBEAT`.
Before lookup or signature verification, heartbeats are admitted by source network
(120/minute) plus a shared 10000/minute ceiling. After valid Ed25519 authentication,
they are admitted at 10 per device per 60 seconds (plus a shared 5000/minute ceiling).
Both PostgreSQL-backed limiters fail closed; denial is `429 HEARTBEAT_RATE_LIMITED`
with `Retry-After: 60` and never updates heartbeat state.

There is no permanent Agent bearer token, static API key, mTLS decision, remote
action, or invasive collection in this version.
