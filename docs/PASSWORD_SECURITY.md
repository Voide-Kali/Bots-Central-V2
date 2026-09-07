# Password Security

Phase 2B.2 provides only reusable password primitives. It does not implement
registration, login, sessions, tokens, recovery, or any HTTP endpoint.

Passwords are hashed with `argon2-cffi` using Argon2id and this explicit profile:

- `time_cost=3`
- `memory_cost=65536` KiB
- `parallelism=4`
- `hash_len=32` bytes
- `salt_len=16` bytes
- `encoding="utf-8"`

The library generates a fresh random salt for every hash. The encoded Argon2 hash
contains the salt; no salt is stored separately. Plaintext passwords are neither
persisted nor logged.

Password input is accepted as Unicode, including spaces, without composition rules,
normalization, trimming, or case folding. The Argon2 API receives strings with an
explicit UTF-8 encoding. Therefore `senha`, `senha `, and canonically equivalent
Unicode strings with different UTF-8 input remain distinct.

For password creation or change, the policy is 15 to 1024 Unicode characters. The
maximum is a technical abuse-protection limit, measured in characters rather than
UTF-8 bytes. Verification applies the same 1024-character technical limit before
calling Argon2, but deliberately does not apply the 15-character minimum so hashes
created under an older policy can still be verified. Input is never silently
truncated.

`VerifyMismatchError` (mismatch) and `InvalidHashError` return `False`. A corrupted
encoded Argon2 hash that the library reports as a generic `VerificationError` raises
`PasswordVerificationError` with the original error chained. `UnsupportedParametersError`,
platform failures, and other unexpected failures are not hidden as a mismatch.
`password_needs_rehash` exposes the library's `check_needs_rehash` decision only;
corrupt hashes raise the library error instead of being treated as current, and this
phase does not write an updated hash to the database.
