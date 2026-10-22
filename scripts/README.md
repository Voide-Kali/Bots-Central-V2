# Scripts

`e2e/` contains the local-only SMTP capture and same-origin/HTTPS proxy harnesses used for
the MVP-1 runbook. They generate ignored, owner-only short-lived certificates and remove only
their own named containers. See `docs/LOCAL_E2E.md`.

`test-db.sh` starts a throwaway PostgreSQL 17 (data in tmpfs, port bound to 127.0.0.1) so the
whole backend suite runs locally — including the PostgreSQL-only tests for locks,
concurrency and migrations that are otherwise skipped:

```bash
scripts/test-db.sh test          # up + full backend suite
scripts/test-db.sh test -k audit # extra pytest arguments are passed through
scripts/test-db.sh down
```

Pinned tool versions: `backend/.python-version` (3.13, same as CI and Dockerfile),
`frontend/.nvmrc` (Node 22, same as CI), `agent/go.mod` (Go directive).
