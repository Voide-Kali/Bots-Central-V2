# Bots Central Linux Agent (MVP-1 foundation)

This module contains the local foundation for the future Bots Central Linux agent.
It deliberately has no HTTP endpoint, pairing flow, credential format, or request
signing implementation until those contracts are agreed with the backend.

Run tests from this directory with `go test ./...`.

Build and run with an explicit configuration file:

```bash
go build ./cmd/bots-central-agent
./bots-central-agent -config ./config.json
```

`config.example.json` documents the required configuration. The state directory must
be absolute. The agent creates it with owner-only permissions and keeps its local
Ed25519 private key there; that key is not logged, exported, or sent by this foundation.

Until a backend-owned enrollment and transport contract exists, the process initializes
its local identity then waits for enrollment. It does not make speculative network calls.
