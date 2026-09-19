# Troubleshooting

Do not solve failures by disabling TLS, Origin checks, fingerprint comparison, rate limits or Agent file permissions.

| Symptom | Check and safe response |
| --- | --- |
| Docker command fails | Run `sudo docker info`; start the daemon using the host's normal service management. The runbook deliberately uses `sudo docker`, not Docker-group membership. |
| Test container missing | Create `bots-central-v2-pg17-test` with the loopback `55432` command in [LOCAL_E2E](LOCAL_E2E.md). |
| Port `55432` busy | Identify the listener and stop only the conflicting local test service, or choose a deliberate new port and update every E2E URL consistently. Do not expose PostgreSQL broadly. |
| Migration fails | Verify `DATABASE_URL` is PostgreSQL with a host and points at `bots_central_test` for E2E. Run Alembic from `backend/` with `PYTHONPATH=.`. |
| Backend returns `503` on register/login | Functional auth needs PostgreSQL plus `ABUSE_CONTROL_HMAC_KEY`; registration also needs SMTP delivery configuration. Check [Configuration](CONFIGURATION.md), not an unsafe fallback. |
| SMTP/STARTTLS fails | Start `mailpit-local.sh`; ensure `SMTP_CA_FILE` names its generated CA and hostname is `localhost`. Do not set insecure TLS options. |
| Certificate validation fails | Keep CA process-scoped with `SSL_CERT_FILE` for the Agent. Harness scripts refuse malformed bundles; preserve/rename only the E2E certificate directory before regeneration. |
| Caddy fails to start | Check Docker availability, loopback ports 8080/8443, and the harness output. It needs the documented single capability because of the pinned image; do not grant broad privileges. |
| Vite unavailable through proxy | Run Vite with the exact loopback/port/`--strictPort` command, then rerun preflight. |
| Pairing expired or enrollment fails | Create a new pairing after login. Tokens are one-time and must never be reused or placed in config/argv. |
| Agent stays pending | This is expected until the owner compares the full fingerprint and explicitly approves the device. |
| Fingerprint mismatch | Reject the device and investigate; do not approve it. Create a new pairing/enrollment only after understanding the mismatch. |
| `STALE_HEARTBEAT` | Agent enters fail-closed state because its sequence is no longer accepted. Do not edit sequence files; preserve evidence and re-enroll according to the approved operational process. |
| Device revoked | The Agent stops normal traffic. Do not delete identity/state casually; revocation/recovery scope is limited in MVP-1. |
| Session/access expiry | Log in again through the same-origin browser flow. Do not manually manufacture cookies or tokens. |
| Reboot | Start the existing PostgreSQL container, then Mailpit, Backend, Vite, proxy and preflight in that order. |
