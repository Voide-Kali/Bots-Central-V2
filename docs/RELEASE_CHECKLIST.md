# Release checklist

Use this checklist against the release candidate SHA. It is a review aid, not a production-deployment or rollback promise.

## Repository and documentation

- [ ] Worktree is clean; expected branch and SHA are recorded.
- [ ] No `.env`, credentials, private keys, tokens or production URLs are tracked.
- [ ] README, Current State, Configuration, Local E2E, Troubleshooting and Security Limitations describe the candidate.
- [ ] Known limitations and MVP-2 exclusions are included in release notes.

## Backend

- [ ] `ruff check .`, `mypy app tests`, `pytest`, `python -m pip check` and dependency audit pass from `backend/`.
- [ ] Full PostgreSQL tests use only dedicated `bots_central_test`; expected coverage is recorded.
- [ ] `alembic upgrade head` succeeds on a disposable test database and migration head is recorded.

## Frontend and Agent

- [ ] Frontend: `npm ci`, `npm test`, `npm run lint`, `npm run typecheck`, `npm run build` pass.
- [ ] Agent: `go test ./...`, `go test -race ./...`, `go vet ./...` pass.

## Security and E2E

- [ ] CI and secret scan are green; dependency findings are reviewed.
- [ ] No TLS downgrade, CORS bypass, persistent web token storage or unsafe pairing-token handling was introduced.
- [ ] Owner isolation, pairing one-time behavior, fingerprint approval and stale/revoked heartbeat behavior are covered by tests/E2E evidence.
- [ ] E2E preflight passes, then register → verify → login → `auth/me` → pairing → enrollment → fingerprint approval → active heartbeat → Device Center online is recorded without secrets.

## Release and rollback record

- [ ] Tag, release notes, candidate SHA, validation dates and known limitations are prepared for reviewer approval.
- [ ] Any schema-impacting release has a tested database migration plan.
- [ ] A documentary rollback checkpoint identifies the prior reviewed SHA and migration compatibility. No claim of automatic production rollback is made because production deployment/restore is not yet supported.
