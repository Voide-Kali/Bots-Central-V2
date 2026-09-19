# Security limitations

This is an honest scope statement for MVP-1, not a vulnerability advisory.

- MVP-1 has no remote-action executor. Lock PC, shutdown, restart, webcam, file transfer, arbitrary shell, remote software installation, Nmap and Telegram are unavailable.
- Email verification proves control of a mailbox, not strong MFA or phishing-resistant identity. Complete account recovery is not implemented.
- The Linux Agent Ed25519 key proves possession of a local key. It does not attest an uncompromised OS, user consent, physical device identity or honest telemetry.
- There is no mTLS, hardware/boot attestation, Windows Agent, mobile app, Desktop Companion or complete signed auto-update.
- No tamper-proof external audit trail exists in MVP-1. Durable mandatory security audit remains future work; PostgreSQL itself is not assumed tamper-proof against a DBA or host root.
- Local E2E CA/certificates are short-lived development material. They are not a production PKI and should not be installed in global trust stores for this runbook.
- No supported production deployment, backup/restore, DR or rollback baseline is certified in this snapshot. The release checklist supplies documentary checkpoints, not a production rollback mechanism.
- Security Gate execution and high-risk proof/consent are not implemented. Device approval is limited to fingerprint comparison and ownership checks.
- Browser protections documented here do not establish a CSP claim; do not infer a CSP or security header baseline that is not implemented.

See [Security model](SECURITY_MODEL.md), [Threat model](THREAT_MODEL.md), and [Current state](CURRENT_STATE.md).
