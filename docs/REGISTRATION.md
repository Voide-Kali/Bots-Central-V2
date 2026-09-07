# Registration Foundation

Phase 2B.3 provides an internal domain service for account registration only. It
does not provide an HTTP registration endpoint, login, session, access token, refresh
token, email delivery, email verification, or automatic authentication.
The existing database schema already supports this flow; no migration or schema
change was required.

The service validates and canonicalizes an email, validates and hashes the password
with the approved Argon2id layer, then stages `User`, `UserEmail`, and
`PasswordCredential` in one nested database transaction. The caller owns the outer
transaction and final commit. If registration persistence fails, the service savepoint
rolls back all records it staged.

`register_user` requires a SQLAlchemy `Session` with no pre-existing `new`, `dirty`,
or `deleted` state. SQLAlchemy flushes pending session state before opening
`begin_nested()` / `SAVEPOINT`; the service therefore fails early with
`RegistrationTransactionStateError` rather than silently affecting the caller's unit
of work. It does not commit, roll back, clear, expunge, or otherwise alter the
caller's pending objects. Its savepoint protects only the records it stages.

New users are `pending_verification`. Their initial email is primary and has no
`verified_at` value. No session or token is created.

## Email identity

`email_display` is the accepted address after removal of external whitespace and is
preserved for presentation. `email_canonical` is the comparison identity: the ASCII
local part is lowercased and the validated domain is represented in normalized ASCII
form. The domain is validated by `email-validator`; deliverability DNS checks are not
performed at registration.

No provider-specific rules are applied. Dots and `+` tags remain significant; for
example, `User.Name+tag@Example.COM` compares as `user.name+tag@example.com`, never
as `username@example.com`. EAI, Unicode local parts, and genuinely case-sensitive
local parts remain outside this phase.

PostgreSQL's unique constraint on `email_canonical` is the authority for duplicate
prevention, including concurrent registration attempts. The domain service maps that
constraint, confirmed in PostgreSQL as `user_emails_email_canonical_key`, to internal
`DuplicateEmailError`. A future HTTP API must choose a generic, anti-enumeration
response rather than exposing whether a specific email is registered.

Passwords are passed only to the existing Argon2id hashing layer; plaintext passwords
and separate salts are never persisted. The stored credential is an encoded Argon2id
hash plus its existing version field.
