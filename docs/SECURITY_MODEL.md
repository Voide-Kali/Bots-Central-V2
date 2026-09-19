# Security Model

MVP-1 applies deny-by-default at its implemented boundaries; it does not yet have an executable cross-feature Security Gate. PostgreSQL is the authority for account, session, ownership and device state.

## Implemented controls

- Argon2id password hashing; plaintext passwords are neither stored nor logged.
- Opaque high-entropy access, refresh and pairing tokens; server persistence uses digests. Refresh rotation and server-side session revocation are implemented.
- Same-origin refresh-cookie boundary with Origin checks, no-store responses, bounded credential-bearing request bodies and PostgreSQL-backed abuse limiting that fails closed.
- Email delivery uses configured STARTTLS validation; production configuration has stricter startup requirements.
- Pairing is one-time, short-lived and bound to the initiating user session. A device enrolls with an Ed25519 proof of possession and remains pending until the owner compares and approves its fingerprint.
- Heartbeats require HTTPS, an EdDSA JWS, the enrolled public key and a strictly increasing sequence. Backend time, not Agent time, determines presence. Owner scoping applies to device operations.
- The browser keeps the access token in memory rather than `localStorage` or `sessionStorage`. The Agent validates TLS, disables redirects and protects its local state with owner-only permissions.

## Limits and assumptions

Email is not strong MFA. An Agent key identifies control of a key, not an uncompromised operating system. There is no mTLS, hardware attestation, tamper-proof external audit or production deployment certification. There is no remote action executor: shell commands, software installation, Nmap, Telegram, shutdown/restart, webcam and file transfer are unavailable.

Security Gate execution, high-risk proof/consent, recovery, Windows/mobile clients and durable audit operations remain future work. See [Security limitations](SECURITY_LIMITATIONS.md) and [Threat model](THREAT_MODEL.md).
