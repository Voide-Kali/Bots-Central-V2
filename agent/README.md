# Bots Central Linux Agent — Device Online V0.1

This Go Agent implements the constrained MVP-1 Device Online contract: local Ed25519 identity, enrollment proof, fingerprint display and signed heartbeats. It does not execute remote commands.

## Build and checks

Go 1.22+ is required.

```bash
go build ./cmd/bots-central-agent
go test ./...
go test -race ./...
go vet ./...
```

Use [config.example.json](config.example.json) as a schema reference. `state_dir` must be absolute. The Agent creates that directory `0700` and atomically writes records `0600`; do not relax these permissions or casually remove state, which holds the identity and durable sequence.

## Enrollment and transport

`backend_base_url` must be an HTTPS origin without credentials, path, query or fragment. Standard Go TLS validation is used and redirects are disabled. For local E2E only, pass the generated CA with process-scoped `SSL_CERT_FILE`; do not install it globally.

The one-time pairing token is accepted only through `-pairing-token-stdin` during enrollment. Never place it in config, argv, a unit file, shell history or logs.

```bash
./bots-central-agent -config /absolute/path/config.json -pairing-token-stdin
```

When prompted, paste the pairing token and press Enter. The token is neither echoed nor
persisted by this input path.

The Agent sends EdDSA JWS enrollment and heartbeat requests. It persists `active` only after an accepted signed heartbeat. Pending is expected until the owner has compared the complete `SHA256:` fingerprint and explicitly approved the device. Stale sequence and revocation fail closed. See [Device Online](../docs/DEVICE_ONLINE_V01.md), [LOCAL_E2E](../docs/LOCAL_E2E.md), and [Troubleshooting](../docs/TROUBLESHOOTING.md).
