# Historical validation notes

`CURRENT_STATE.md` is intentionally the single current snapshot. Earlier phase-by-phase validation notes, intermediate pass counts and pre-E2E pending records must not be read as current release status.

## Superseded records

- 2026-09-12 integration and SMTP-harness notes recorded host-pending Docker proof and `READY FOR LIVE E2E: NO` conditions. They were superseded by the recorded MVP-1 live E2E PASS on 2026-09-13.
- Phase 2B/3A records describe incremental database, password, registration, email-verification and HTTP delivery work. Their historical wording such as “no endpoint” or “no login” applies only to that phase, not the MVP-1 snapshot.
- Earlier test totals and coverage values are validation evidence for their commits, not a replacement for the baseline in [Current State](CURRENT_STATE.md).

For detailed original wording, inspect Git history at the frozen base. The current authoritative outcome is the MVP-1 live E2E PASS recorded in [Current State](CURRENT_STATE.md).
