# Bots Central Linux Agent — Device Online V0.1

This module implements the Agent side of the frozen Device Online V0.1
contract. It creates one local Ed25519 identity, displays its canonical
fingerprint, enrolls with proof-of-possession, and sends signed heartbeats. It
does not implement remote commands.

## Local state and secret handling

The absolute `state_dir` is created as `0700`; its records are atomically
written as `0600` files. The identity record holds the local Ed25519 private
key, enrollment state holds only a device UUID plus lifecycle status, and the
heartbeat sequence is durable and protected by an owner-only file lock.

The private key has no export API and never appears in a request or log. The
pairing token is accepted only through `-pairing-token-stdin` during first
enrollment; it is not accepted in config or argv and is never persisted. Supply
it from an approved ephemeral secret-input mechanism, not shell history, a
file, or a unit definition.

```bash
go build ./cmd/bots-central-agent
your-secret-input-command | ./bots-central-agent -config ./config.json -pairing-token-stdin
```

The displayed fingerprint is byte-for-byte compatible with the Backend:
`SHA256:<unpadded-base64url-SHA-256-of-raw-Ed25519-public-key>`.

## Configuration and transport

`backend_base_url` is one HTTPS origin with no embedded credentials, path,
query, or fragment. The Agent builds only these frozen paths:

- `POST /api/v1/devices/enrollments`;
- `POST /api/v1/devices/{device_id}/heartbeat`.

TLS uses standard Go verification. Redirects are disabled, and responses are
bounded before JSON parsing. The Agent uses `go-jose/v4` with the algorithm
fixed to `EdDSA`; it does not negotiate algorithms or accept request-selected
keys.

## Device protocol

Enrollment sends JSON with `pairing_token`, canonical raw-32-byte `public_key`,
`proof`, `name`, `platform`, and optional `agent_version`. The pairing token is
not an HTTP bearer credential. The compact JWS proof is signed by the same
local key and carries exact `aud` `bots-central:enrollment:v1`, `sub`
`enrollment`, and the plaintext `pairing_token`. Before persisting the pending
enrollment, the Agent compares the returned fingerprint exactly against its
local canonical fingerprint.

Heartbeats send `Content-Type: application/json` and `{"jws":"..."}`. Their
EdDSA JWS carries exact `aud` `bots-central:heartbeat:v1`, the persisted UUID as
`sub`, and a durable monotonic `uint64` `seq`. The sequence is committed before
the probe, so crashes may leave gaps but never reuse values. Backend time is the
only presence authority.

A pending device sends signed, sequenced probes every 30 seconds with ±5 seconds
jitter. `403 DEVICE_PENDING` keeps it pending and schedules the next nominal
probe. The first `200 {"accepted":true}` persists `active`; active restart
continues normally. `409 STALE_HEARTBEAT` persists `state_lost` and fails closed.
`403 DEVICE_REVOKED` persists `revoked` and stops normal traffic. Neither path
deletes the key. Valid `Retry-After`, including zero, is honored for
`429 HEARTBEAT_RATE_LIMITED`; network/5xx use bounded backoff and other 4xx
responses fail closed.

Run checks from this directory:

```bash
go test ./...
go test -race ./...
go vet ./...
```
