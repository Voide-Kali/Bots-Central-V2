# Security Model

The platform follows deny by default: no actor, device, or operation is trusted until
a future Security Gate explicitly authorizes it. Future device identity and
authentication will be designed before agents or device operations are introduced.

All sensitive actions must become auditable, with sufficient event metadata and no
secrets in audit records. Secrets belong in environment-managed secret stores, never
in source control or application logs. Logging redacts common credential patterns.

Components receive the least privilege required. The backend is the only planned
component with database access; future agents and mobile clients use constrained API
contracts. CORS is not enabled in this foundation and must never use a wildcard in
production.
