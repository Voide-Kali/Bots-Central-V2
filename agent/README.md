# Bots Central Linux Agent — Device Online V0.1

This module implements the local half of Device Online V0.1. It creates one
local Ed25519 identity, displays a fingerprint, performs enrollment by
proof-of-possession, and sends signed heartbeats only for an `active` device.
It does not implement remote commands.

## Local state and secret handling

The absolute `state_dir` in the configuration is created as `0700`. Its records
are written atomically as `0600` files:

- `device-identity-v1.json` contains the local Ed25519 private key;
- `device-enrollment-v1.json` contains only the device ID and lifecycle status;
- `heartbeat-sequence-v1.json` contains the last sent sequence; and
- `heartbeat-sequence-v1.lock` serializes sequence allocation across processes.

The private key has no export API and is never included in a request or log. The
pairing token is accepted only from standard input during initial enrollment; it
is not accepted in configuration or command arguments and is never persisted.
Provide it from an approved ephemeral secret-input mechanism, for example by
piping it to `-pairing-token-stdin`; do not place it in a shell history, file,
or unit definition.

```bash
go build ./cmd/bots-central-agent
your-secret-input-command | ./bots-central-agent -config ./config.json -pairing-token-stdin
```

The agent logs only the public-key fingerprint in the format
`ed25519-sha256:<base64url digest>` so an operator can verify the local identity.

## Configuration

Start from `config.example.json`. All fields are required. `enrollment_url` and
`heartbeat_url` must be absolute HTTPS URLs with no embedded credentials, query,
or fragment. TLS uses the standard Go verifier. The client does not follow HTTP
redirects, preventing a pairing token or JWS from being forwarded to another
endpoint.

`heartbeat_interval` is fixed at `30s`; the runtime applies a bounded random
jitter of plus or minus five seconds after a successful heartbeat. Failed
network and 5xx attempts use the configured bounded exponential backoff.

## Wire behavior

Enrollment sends the configured `enrollment_url` a POST with the pairing token
in the `Authorization: Bearer` header and a JSON body containing the base64url
public key plus a compact Ed25519 JWS proof. The proof has audience
`bots-central:enrollment:v1`. The response is accepted only when it contains a
device ID and status `pending` or `active`; neither pairing data nor proof data
is written locally.

Each heartbeat is a POST to the configured `heartbeat_url` with a compact
Ed25519 JWS in `Authorization: Bearer`. Its audience is exactly
`bots-central:heartbeat:v1`; it includes the device ID, a durable monotonic
`uint64` sequence, hostname/platform metadata, and an agent timestamp. The
sequence is committed before the request is signed or sent, so a crash may skip
a number but never reuses one.

The local enrollment status gates delivery:

- `pending` sends no heartbeat;
- `active` sends heartbeats;
- a `409` stale sequence persists `state_lost` and fails closed; and
- a `403` response whose JSON code is `DEVICE_REVOKED` persists `revoked` and
  stops normal heartbeats.

Neither terminal path deletes the private key. A `429` obeys a valid
`Retry-After`; malformed or absent values use bounded backoff. Other 5xx and
network errors use bounded backoff, while other rejected responses stop normal
retries.

## Backend integration boundary

The current backend base does not yet expose or approve the enrollment,
activation-status, or heartbeat endpoints. Consequently, a locally persisted
`pending` device remains safely idle until a backend-approved activation-status
contract is integrated; the agent never promotes it itself. Endpoint URLs are
explicit configuration rather than guessed paths. This is an integration
blocker, not a fallback to a permanent user token or API key.

Run checks from this directory:

```bash
go test ./...
go test -race ./...
go vet ./...
```
