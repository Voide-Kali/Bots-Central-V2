import base64
import threading
import uuid
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta
from queue import Queue
from time import monotonic

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as DatabaseSession

from app.auth.email_verification_issuance import (
    AccountNotEligible,
    AlreadyVerified,
    CooldownActive,
    EmailVerificationIssuanceTransactionStateError,
    NotFound,
    StagedCodeChallenge,
    StagedLinkChallenge,
    stage_email_verification,
)
from app.auth.email_verification_materials import (
    EmailVerificationHmacKeyring,
    email_verification_code_digest,
)
from app.db.enums import (
    AccountStatus,
    EmailVerificationInvalidationReason,
    EmailVerificationMaterialType,
)
from app.db.models import EmailVerificationChallenge, User, UserEmail


def database_now(session: DatabaseSession) -> datetime:
    current_time = session.scalar(text("SELECT clock_timestamp()"))
    assert isinstance(current_time, datetime)
    return current_time


def create_user_email(
    session: DatabaseSession,
    *,
    suffix: str,
    status: AccountStatus = AccountStatus.PENDING_VERIFICATION,
    verified: bool = False,
) -> tuple[User, UserEmail]:
    user = User(status=status)
    session.add(user)
    session.flush()
    email = UserEmail(
        user_id=user.id,
        email_canonical=f"issuance-{suffix}@example.com",
        email_display=f"issuance-{suffix}@example.com",
        verified_at=database_now(session) if verified else None,
    )
    session.add(email)
    session.flush()
    return user, email


def link_challenge(
    user_email_id: uuid.UUID, *, created_at: datetime, expires_at: datetime, marker: int
) -> EmailVerificationChallenge:
    return EmailVerificationChallenge(
        id=uuid.uuid4(),
        user_email_id=user_email_id,
        material_type=EmailVerificationMaterialType.LINK,
        link_token_digest=bytes([marker]) * 32,
        created_at=created_at,
        expires_at=expires_at,
    )


def code_challenge(
    user_email_id: uuid.UUID, *, created_at: datetime, expires_at: datetime, marker: int
) -> EmailVerificationChallenge:
    return EmailVerificationChallenge(
        id=uuid.uuid4(),
        user_email_id=user_email_id,
        material_type=EmailVerificationMaterialType.CODE,
        code_digest=bytes([marker]) * 32,
        hmac_key_version="test-v1",
        attempt_count=0,
        max_attempts=5,
        created_at=created_at,
        expires_at=expires_at,
    )


def keyring() -> EmailVerificationHmacKeyring:
    def encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    return EmailVerificationHmacKeyring(
        active_key_version="current",
        keys={
            "current": SecretStr(encode(b"a" * 32)),
            "previous": SecretStr(encode(b"b" * 32)),
        },
    )


@pytest.mark.postgresql
def test_first_link_issuance_stages_only_digest_and_caller_owns_commit(
    postgresql_session: DatabaseSession,
) -> None:
    _, email = create_user_email(postgresql_session, suffix="first")

    result = stage_email_verification(
        postgresql_session,
        user_email_id=email.id,
        material_type=EmailVerificationMaterialType.LINK,
    )

    assert isinstance(result, StagedLinkChallenge)
    challenge = postgresql_session.get(EmailVerificationChallenge, result.challenge_id)
    assert challenge is not None
    assert challenge.link_token_digest is not None
    assert challenge.code_digest is None
    assert challenge.created_at is not None
    assert challenge.expires_at - challenge.created_at == timedelta(minutes=15)
    assert result.external_token.get_secret_value() not in repr(result)
    assert result.external_token.get_secret_value() not in repr(challenge)
    assert "external_token" not in challenge.__dict__
    assert "raw_token" not in challenge.__dict__


@pytest.mark.postgresql
def test_link_issuance_never_requires_a_keyring(postgresql_session: DatabaseSession) -> None:
    _, email = create_user_email(postgresql_session, suffix="link-no-keyring")

    result = stage_email_verification(
        postgresql_session,
        user_email_id=email.id,
        material_type=EmailVerificationMaterialType.LINK,
    )

    assert isinstance(result, StagedLinkChallenge)


@pytest.mark.postgresql
def test_code_issuance_binds_active_key_and_persists_no_plaintext(
    postgresql_session: DatabaseSession,
) -> None:
    user, email = create_user_email(postgresql_session, suffix="code")
    configured_keyring = keyring()

    result = stage_email_verification(
        postgresql_session,
        user_email_id=email.id,
        material_type=EmailVerificationMaterialType.CODE,
        keyring=configured_keyring,
    )

    assert isinstance(result, StagedCodeChallenge)
    challenge = postgresql_session.get(EmailVerificationChallenge, result.challenge_id)
    assert challenge is not None
    assert challenge.hmac_key_version == "current"
    assert challenge.attempt_count == 0
    assert challenge.max_attempts == 5
    assert challenge.code_digest == email_verification_code_digest(
        key=configured_keyring.key_for_version("current"),
        challenge_id=challenge.id,
        user_id=user.id,
        user_email_id=email.id,
        code=result.code.get_secret_value(),
    )
    assert challenge.code_digest != email_verification_code_digest(
        key=configured_keyring.key_for_version("previous"),
        challenge_id=challenge.id,
        user_id=user.id,
        user_email_id=email.id,
        code=result.code.get_secret_value(),
    )
    assert result.code.get_secret_value() not in repr(result)
    assert result.code.get_secret_value() not in repr(challenge)
    assert "code" not in challenge.__dict__


@pytest.mark.postgresql
@pytest.mark.parametrize(
    ("status", "verified", "outcome_type"),
    [
        (AccountStatus.PENDING_VERIFICATION, True, AlreadyVerified),
        (AccountStatus.ACTIVE, False, AccountNotEligible),
        (AccountStatus.LOCKED, False, AccountNotEligible),
        (AccountStatus.DISABLED, False, AccountNotEligible),
    ],
)
def test_ineligible_account_outcomes_do_not_issue(
    postgresql_session: DatabaseSession,
    status: AccountStatus,
    verified: bool,
    outcome_type: type[AlreadyVerified | AccountNotEligible],
) -> None:
    _, email = create_user_email(
        postgresql_session,
        suffix=f"state-{status.value}-{verified}",
        status=status,
        verified=verified,
    )

    result = stage_email_verification(
        postgresql_session,
        user_email_id=email.id,
        material_type=EmailVerificationMaterialType.LINK,
    )

    assert isinstance(result, outcome_type)
    assert (
        postgresql_session.scalar(
            select(func.count())
            .select_from(EmailVerificationChallenge)
            .where(EmailVerificationChallenge.user_email_id == email.id)
        )
        == 0
    )


@pytest.mark.postgresql
def test_missing_email_returns_not_found(postgresql_session: DatabaseSession) -> None:
    missing_id = uuid.uuid4()

    result = stage_email_verification(
        postgresql_session,
        user_email_id=missing_id,
        material_type=EmailVerificationMaterialType.LINK,
    )

    assert result == NotFound(user_email_id=missing_id)


@pytest.mark.postgresql
def test_cooldown_boundaries_and_resend_supersedes_live_sibling(
    postgresql_session: DatabaseSession,
) -> None:
    _, blocked_email = create_user_email(postgresql_session, suffix="cooldown-blocked")
    _, allowed_email = create_user_email(postgresql_session, suffix="cooldown-allowed")
    current_time = database_now(postgresql_session)
    blocked = link_challenge(
        blocked_email.id,
        created_at=current_time - timedelta(seconds=30),
        expires_at=current_time + timedelta(minutes=5),
        marker=1,
    )
    allowed = link_challenge(
        allowed_email.id,
        created_at=current_time - timedelta(seconds=60),
        expires_at=current_time + timedelta(minutes=5),
        marker=2,
    )
    postgresql_session.add_all((blocked, allowed))
    postgresql_session.flush()

    blocked_result = stage_email_verification(
        postgresql_session,
        user_email_id=blocked_email.id,
        material_type=EmailVerificationMaterialType.LINK,
    )
    allowed_result = stage_email_verification(
        postgresql_session,
        user_email_id=allowed_email.id,
        material_type=EmailVerificationMaterialType.LINK,
    )

    assert isinstance(blocked_result, CooldownActive)
    assert blocked.invalidated_at is None
    assert isinstance(allowed_result, StagedLinkChallenge)
    assert allowed.invalidated_at is not None
    assert allowed.invalidation_reason is EmailVerificationInvalidationReason.SUPERSEDED


@pytest.mark.postgresql
def test_resend_supersedes_only_live_siblings(postgresql_session: DatabaseSession) -> None:
    _, email = create_user_email(postgresql_session, suffix="siblings")
    current_time = database_now(postgresql_session)
    live_link = link_challenge(
        email.id,
        created_at=current_time - timedelta(seconds=61),
        expires_at=current_time + timedelta(minutes=5),
        marker=11,
    )
    live_code = code_challenge(
        email.id,
        created_at=current_time - timedelta(seconds=62),
        expires_at=current_time + timedelta(minutes=5),
        marker=12,
    )
    expired = link_challenge(
        email.id,
        created_at=current_time - timedelta(minutes=3),
        expires_at=current_time - timedelta(seconds=1),
        marker=13,
    )
    consumed = link_challenge(
        email.id,
        created_at=current_time - timedelta(minutes=3),
        expires_at=current_time + timedelta(minutes=5),
        marker=14,
    )
    consumed.consumed_at = current_time - timedelta(seconds=30)
    invalidated = code_challenge(
        email.id,
        created_at=current_time - timedelta(minutes=3),
        expires_at=current_time + timedelta(minutes=5),
        marker=15,
    )
    invalidated.invalidated_at = current_time - timedelta(seconds=30)
    invalidated.invalidation_reason = EmailVerificationInvalidationReason.SUPERSEDED
    postgresql_session.add_all((live_link, live_code, expired, consumed, invalidated))
    postgresql_session.flush()

    result = stage_email_verification(
        postgresql_session,
        user_email_id=email.id,
        material_type=EmailVerificationMaterialType.LINK,
    )

    assert isinstance(result, StagedLinkChallenge)
    assert live_link.invalidation_reason is EmailVerificationInvalidationReason.SUPERSEDED
    assert live_code.invalidation_reason is EmailVerificationInvalidationReason.SUPERSEDED
    assert expired.invalidated_at is None
    assert consumed.invalidated_at is None
    assert invalidated.invalidation_reason is EmailVerificationInvalidationReason.SUPERSEDED


@pytest.mark.postgresql
def test_outer_rollback_reverts_staged_challenge_and_sibling_invalidation(
    migrated_postgresql_engine: Engine,
) -> None:
    with committed_eligible_email(migrated_postgresql_engine, "rollback") as email_id:
        with DatabaseSession(migrated_postgresql_engine) as seed_session:
            current_time = database_now(seed_session)
            sibling = link_challenge(
                email_id,
                created_at=current_time - timedelta(seconds=61),
                expires_at=current_time + timedelta(minutes=5),
                marker=20,
            )
            seed_session.add(sibling)
            seed_session.commit()
            sibling_id = sibling.id

        with DatabaseSession(migrated_postgresql_engine) as session:
            result = stage_email_verification(
                session, user_email_id=email_id, material_type=EmailVerificationMaterialType.LINK
            )
            assert isinstance(result, StagedLinkChallenge)
            session.rollback()

        with DatabaseSession(migrated_postgresql_engine) as verify_session:
            restored_sibling = verify_session.get(EmailVerificationChallenge, sibling_id)
            assert restored_sibling is not None
            assert restored_sibling.invalidated_at is None
            assert (
                verify_session.scalar(
                    select(func.count())
                    .select_from(EmailVerificationChallenge)
                    .where(EmailVerificationChallenge.user_email_id == email_id)
                )
                == 1
            )


@pytest.mark.postgresql
@pytest.mark.parametrize("state", ["new", "dirty", "deleted"])
def test_issuance_rejects_caller_owned_pending_state(
    postgresql_session: DatabaseSession, state: str
) -> None:
    unrelated_user = User(status=AccountStatus.PENDING_VERIFICATION)
    postgresql_session.add(unrelated_user)
    if state != "new":
        postgresql_session.flush()
        if state == "dirty":
            unrelated_user.security_version = 1
        else:
            postgresql_session.delete(unrelated_user)

    with pytest.raises(EmailVerificationIssuanceTransactionStateError):
        stage_email_verification(
            postgresql_session,
            user_email_id=uuid.uuid4(),
            material_type=EmailVerificationMaterialType.LINK,
        )

    if state == "new":
        assert unrelated_user in postgresql_session.new
    elif state == "dirty":
        assert unrelated_user in postgresql_session.dirty
    else:
        assert unrelated_user in postgresql_session.deleted


def _cleanup_committed_email(engine: Engine, email_id: uuid.UUID) -> None:
    with DatabaseSession(engine) as session:
        user_id = session.scalar(select(UserEmail.user_id).where(UserEmail.id == email_id))
        session.execute(
            delete(EmailVerificationChallenge).where(
                EmailVerificationChallenge.user_email_id == email_id
            )
        )
        session.execute(delete(UserEmail).where(UserEmail.id == email_id))
        if user_id is not None:
            session.execute(delete(User).where(User.id == user_id))
        session.commit()


@contextmanager
def committed_eligible_email(engine: Engine, suffix: str) -> Generator[uuid.UUID, None, None]:
    email_id: uuid.UUID | None = None
    try:
        with DatabaseSession(engine) as session:
            _, email = create_user_email(session, suffix=suffix)
            email_id = email.id
            session.commit()
        yield email_id
    except BaseException:
        if email_id is not None:
            try:
                _cleanup_committed_email(engine, email_id)
            except Exception:
                pass
        raise
    else:
        if email_id is not None:
            _cleanup_committed_email(engine, email_id)


def _concurrent_stage(
    engine: Engine, email_id: uuid.UUID, barrier: threading.Barrier
) -> StagedLinkChallenge | CooldownActive:
    with DatabaseSession(engine) as session:
        with session.begin():
            session.execute(text("SET LOCAL lock_timeout = '3s'"))
            barrier.wait(timeout=5)
            result = stage_email_verification(
                session,
                user_email_id=email_id,
                material_type=EmailVerificationMaterialType.LINK,
            )
            assert isinstance(result, (StagedLinkChallenge, CooldownActive))
            return result


def _stage_after_publishing_backend_pid(
    engine: Engine, email_id: uuid.UUID, pid_queue: Queue[int]
) -> StagedLinkChallenge | CooldownActive:
    with DatabaseSession(engine) as session:
        with session.begin():
            session.execute(text("SET LOCAL lock_timeout = '3s'"))
            backend_pid = session.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(backend_pid, int)
            pid_queue.put(backend_pid)
            result = stage_email_verification(
                session,
                user_email_id=email_id,
                material_type=EmailVerificationMaterialType.LINK,
            )
            assert isinstance(result, (StagedLinkChallenge, CooldownActive))
            return result


def _wait_until_blocked_by(
    engine: Engine, *, blocked_pid: int, blocking_pid: int, timeout_seconds: float = 3.0
) -> bool:
    deadline = monotonic() + timeout_seconds
    wait = threading.Event()
    with DatabaseSession(engine) as observer_session:
        while monotonic() < deadline:
            blocking_pids = observer_session.scalar(
                text("SELECT pg_blocking_pids(:blocked_pid)"), {"blocked_pid": blocked_pid}
            )
            if isinstance(blocking_pids, list) and blocking_pid in blocking_pids:
                return True
            wait.wait(0.02)
    return False


@pytest.mark.postgresql
def test_user_email_lock_blocks_then_rechecks_cooldown_after_commit(
    migrated_postgresql_engine: Engine,
) -> None:
    with committed_eligible_email(migrated_postgresql_engine, "lock-proof") as email_id:
        backend_pid_queue: Queue[int] = Queue()
        with ThreadPoolExecutor(max_workers=1) as executor:
            with DatabaseSession(migrated_postgresql_engine) as lock_session:
                with lock_session.begin():
                    pid_a = lock_session.scalar(text("SELECT pg_backend_pid()"))
                    assert isinstance(pid_a, int)
                    locked_email = lock_session.scalar(
                        select(UserEmail).where(UserEmail.id == email_id).with_for_update()
                    )
                    assert locked_email is not None
                    future = executor.submit(
                        _stage_after_publishing_backend_pid,
                        migrated_postgresql_engine,
                        email_id,
                        backend_pid_queue,
                    )
                    pid_b = backend_pid_queue.get(timeout=3)
                    assert _wait_until_blocked_by(
                        migrated_postgresql_engine,
                        blocked_pid=pid_b,
                        blocking_pid=pid_a,
                    )
                    current_time = database_now(lock_session)
                    lock_session.add(
                        link_challenge(
                            email_id,
                            created_at=current_time,
                            expires_at=current_time + timedelta(minutes=15),
                            marker=40,
                        )
                    )
                    lock_session.flush()

            result = future.result(timeout=5)

        assert isinstance(result, CooldownActive)
        with DatabaseSession(migrated_postgresql_engine) as verify_session:
            assert (
                verify_session.scalar(
                    select(func.count())
                    .select_from(EmailVerificationChallenge)
                    .where(EmailVerificationChallenge.user_email_id == email_id)
                )
                == 1
            )


@pytest.mark.postgresql
def test_locked_user_load_repopulates_stale_identity_map(
    migrated_postgresql_engine: Engine,
) -> None:
    with committed_eligible_email(migrated_postgresql_engine, "stale-user") as email_id:
        session_a = DatabaseSession(migrated_postgresql_engine)
        try:
            email_a = session_a.get(UserEmail, email_id)
            assert email_a is not None
            user_a = session_a.get(User, email_a.user_id)
            assert user_a is not None
            assert user_a.status is AccountStatus.PENDING_VERIFICATION
            assert email_a.verified_at is None
            assert not session_a.new and not session_a.dirty and not session_a.deleted

            with DatabaseSession(migrated_postgresql_engine) as session_b:
                user_b = session_b.get(User, user_a.id)
                assert user_b is not None
                user_b.status = AccountStatus.LOCKED
                session_b.commit()

            result = stage_email_verification(
                session_a,
                user_email_id=email_id,
                material_type=EmailVerificationMaterialType.LINK,
            )

            assert isinstance(result, AccountNotEligible)
            refreshed_user = session_a.get(User, user_a.id)
            assert refreshed_user is not None
            assert refreshed_user.status is AccountStatus.LOCKED
            assert (
                session_a.scalar(
                    select(func.count())
                    .select_from(EmailVerificationChallenge)
                    .where(EmailVerificationChallenge.user_email_id == email_id)
                )
                == 0
            )
        finally:
            session_a.close()


@pytest.mark.postgresql
def test_locked_email_load_repopulates_stale_identity_map(
    migrated_postgresql_engine: Engine,
) -> None:
    with committed_eligible_email(migrated_postgresql_engine, "stale-email") as email_id:
        session_a = DatabaseSession(migrated_postgresql_engine)
        try:
            email_a = session_a.get(UserEmail, email_id)
            assert email_a is not None
            user_a = session_a.get(User, email_a.user_id)
            assert user_a is not None
            assert user_a.status is AccountStatus.PENDING_VERIFICATION
            assert email_a.verified_at is None
            assert not session_a.new and not session_a.dirty and not session_a.deleted

            with DatabaseSession(migrated_postgresql_engine) as session_b:
                email_b = session_b.get(UserEmail, email_id)
                assert email_b is not None
                email_b.verified_at = database_now(session_b)
                session_b.commit()

            result = stage_email_verification(
                session_a,
                user_email_id=email_id,
                material_type=EmailVerificationMaterialType.LINK,
            )

            assert isinstance(result, AlreadyVerified)
            assert email_a.verified_at is not None
            assert (
                session_a.scalar(
                    select(func.count())
                    .select_from(EmailVerificationChallenge)
                    .where(EmailVerificationChallenge.user_email_id == email_id)
                )
                == 0
            )
        finally:
            session_a.close()


@pytest.mark.postgresql
def test_first_issuance_concurrency_serializes_on_user_email(
    migrated_postgresql_engine: Engine,
) -> None:
    with committed_eligible_email(migrated_postgresql_engine, "concurrent-first") as email_id:
        barrier = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: _concurrent_stage(migrated_postgresql_engine, email_id, barrier),
                    range(2),
                )
            )
        assert sum(isinstance(result, StagedLinkChallenge) for result in results) == 1
        assert sum(isinstance(result, CooldownActive) for result in results) == 1
        with DatabaseSession(migrated_postgresql_engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(EmailVerificationChallenge)
                    .where(EmailVerificationChallenge.user_email_id == email_id)
                )
                == 1
            )


@pytest.mark.postgresql
def test_resend_concurrency_observes_first_committed_emission(
    migrated_postgresql_engine: Engine,
) -> None:
    with committed_eligible_email(migrated_postgresql_engine, "concurrent-resend") as email_id:
        with DatabaseSession(migrated_postgresql_engine) as seed_session:
            current_time = database_now(seed_session)
            seed_session.add(
                link_challenge(
                    email_id,
                    created_at=current_time - timedelta(seconds=61),
                    expires_at=current_time + timedelta(minutes=5),
                    marker=30,
                )
            )
            seed_session.commit()

        barrier = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: _concurrent_stage(migrated_postgresql_engine, email_id, barrier),
                    range(2),
                )
            )
        assert sum(isinstance(result, StagedLinkChallenge) for result in results) == 1
        assert sum(isinstance(result, CooldownActive) for result in results) == 1
        with DatabaseSession(migrated_postgresql_engine) as session:
            challenges = session.scalars(
                select(EmailVerificationChallenge).where(
                    EmailVerificationChallenge.user_email_id == email_id
                )
            ).all()
            assert len(challenges) == 2
            assert sum(challenge.invalidated_at is None for challenge in challenges) == 1
