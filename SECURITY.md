# Security Policy

## Reporting a vulnerability

Do not open a public issue with security-sensitive details. Report findings through
the private channel agreed by the project maintainers, including reproduction steps
and impact.

## Repository hygiene

Never commit `.env` files, credentials, tokens, private keys, or production
connection strings. Use the root `.env.example` for the health-only Compose stack
and `backend/.env.example` for direct Backend development; both are non-secret
templates, not deployment configuration.

Security controls and future trust boundaries are documented in
`docs/SECURITY_MODEL.md` and `docs/SECURITY_LIMITATIONS.md`.
