# Product capabilities

This matrix is for the MVP-1 snapshot `efbec158059995a1069119084fd5e29eedc3f64a`.

| Capability | Status | Notes |
| --- | --- | --- |
| Account registration | Available | Creates a pending-verification account. |
| Email verification | Available | Link/code flow with configured delivery. |
| Login and sessions | Available | Opaque access and rotating refresh tokens. |
| Device Center | Available | Owner-scoped listing and lifecycle/presence display. |
| Linux device enrollment | Available | Pairing token plus Ed25519 proof of possession. |
| Fingerprint approval/reject | Available | Human comparison is required before activation. |
| Device Online | Available | Signed heartbeat and backend-derived presence. |
| Security Gate, Task Engine, Lock PC | Planned MVP-2 | Design/work in progress; unavailable now. |
| Shutdown/restart, webcam, file transfer | Future | No remote action exists in MVP-1. |
| Flutter mobile, Desktop Companion, Windows Agent | Future | Not shipped. |
| Telegram and Nmap | Not part of V2 | Explicitly excluded from this product scope. |
| Arbitrary shell and remote software installation | Intentionally unsupported | No executor exists. |
