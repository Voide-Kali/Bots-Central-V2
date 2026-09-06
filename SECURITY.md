# Security Policy

## Reporting a vulnerability

Do not open a public issue with security-sensitive details. Report findings through
the private channel agreed by the project maintainers, including reproduction steps
and impact.

## Repository hygiene

Never commit `.env` files, credentials, tokens, private keys, or production
connection strings. Use `backend/.env.example` only as a non-secret template.

Security controls and future trust boundaries are documented in
`docs/SECURITY_MODEL.md`.
