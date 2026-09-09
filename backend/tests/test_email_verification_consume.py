import base64
import threading
import uuid
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from queue import Queue
from time import monotonic
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, event, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.auth import email_verification_consume as consume
from app.auth import email_verification_issuance as issuance
from app.auth.email_verification_materials import (
    EmailVerificationHmacKeyring,
    email_verification_code_digest,
    generate_link_token,
)
from app.db.enums import (
    AccountStatus,
)
from app.db.enums import (
    EmailVerificationInvalidationReason as Reason,
)
from app.db.enums import (
    EmailVerificationMaterialType as Material,
)
from app.db.models import EmailVerificationChallenge as Challenge
from app.db.models import User, UserEmail

pytestmark = pytest.mark.postgresql


def database_time(session: Session) -> datetime:
    value = session.scalar(text("SELECT clock_timestamp()"))
    assert isinstance(value, datetime)
    return value


def keyring(*, previous: bool = True) -> EmailVerificationHmacKeyring:
    keys = {"current": base64.urlsafe_b64encode(b"a" * 32).decode().rstrip("=")}
    if previous:
        keys["previous"] = base64.urlsafe_b64encode(b"b" * 32).decode().rstrip("=")
    return EmailVerificationHmacKeyring(active_key_version="current", keys=keys)


@dataclass(frozen=True)
class Seed:
    user_id: uuid.UUID
    email_id: uuid.UUID
    challenge_id: uuid.UUID
    material: Material
    plaintext: SecretStr = field(repr=False)


def seed_challenge(session: Session, material: Material) -> Seed:
    user = User(status=AccountStatus.PENDING_VERIFICATION)
    session.add(user)
    session.flush()
    address = f"consume-{uuid.uuid4()}@example.com"
    email = UserEmail(user_id=user.id, email_canonical=address, email_display=address)
    session.add(email)
    session.flush()
    timestamp = database_time(session)
    challenge = Challenge(
        id=uuid.uuid4(),
        user_email_id=email.id,
        material_type=material,
        created_at=timestamp - timedelta(minutes=2),
        expires_at=timestamp + timedelta(minutes=5),
    )
    if material is Material.CODE:
        plaintext = "01234567"
        challenge.code_digest = email_verification_code_digest(
            key=keyring().key_for_version("previous"),
            challenge_id=challenge.id,
            user_id=user.id,
            user_email_id=email.id,
            code=plaintext,
        )
        challenge.hmac_key_version = "previous"
        challenge.attempt_count = 0
        challenge.max_attempts = 5
    else:
        token = generate_link_token()
        plaintext = token.external_token
        challenge.link_token_digest = token.digest
    session.add(challenge)
    session.flush()
    return Seed(user.id, email.id, challenge.id, material, SecretStr(plaintext))


def perform(
    session: Session, seed: Seed, *, code: str | None = None
) -> consume.EmailVerificationConsumeOutcome:
    if seed.material is Material.LINK:
        return consume.consume_email_verification_link(
            session, external_token=seed.plaintext.get_secret_value()
        )
    return consume.consume_email_verification_code(
        session,
        challenge_id=seed.challenge_id,
        code=seed.plaintext.get_secret_value() if code is None else code,
        keyring=keyring(),
    )


def rows(session: Session, seed: Seed) -> tuple[User, UserEmail, Challenge]:
    user = session.get(User, seed.user_id)
    email = session.get(UserEmail, seed.email_id)
    challenge = session.get(Challenge, seed.challenge_id)
    assert user is not None and email is not None and challenge is not None
    return user, email, challenge


def snapshot(session: Session, seed: Seed) -> tuple[tuple[Any, ...], ...]:
    # Column projections observe persisted values, independent of the identity map.
    return tuple(
        tuple(session.execute(select(model.__table__).where(model.id == identifier)).one())
        for model, identifier in (
            (User, seed.user_id),
            (UserEmail, seed.email_id),
            (Challenge, seed.challenge_id),
        )
    )


@contextmanager
def committed_seed(engine: Engine, material: Material) -> Generator[Seed, None, None]:
    with Session(engine) as session:
        seed = seed_challenge(session, material)
        session.commit()

    def cleanup() -> None:
        with Session(engine) as session, session.begin():
            session.execute(delete(Challenge).where(Challenge.user_email_id == seed.email_id))
            session.execute(delete(UserEmail).where(UserEmail.id == seed.email_id))
            session.execute(delete(User).where(User.id == seed.user_id))

    try:
        yield seed
    except BaseException:
        try:
            cleanup()
        except Exception:
            pass
        raise
    else:
        cleanup()


@pytest.mark.parametrize("material", list(Material))
def test_success_and_retry_share_one_post_lock_timestamp(
    postgresql_session: Session, material: Material
) -> None:
    session = postgresql_session
    seed = seed_challenge(session, material)
    statements: list[str] = []

    def record(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", record)
    try:
        result = perform(session, seed)
    finally:
        event.remove(connection, "before_cursor_execute", record)
    assert isinstance(result, consume.ConsumedEmailVerification)
    user, email, target = rows(session, seed)
    assert user.status is AccountStatus.ACTIVE
    assert email.verified_at == target.consumed_at == result.consumed_at
    assert user.updated_at == email.updated_at == result.consumed_at
    assert target.invalidated_at is None and target.invalidation_reason is None
    assert target.attempt_count == (0 if material is Material.CODE else None)
    assert seed.plaintext.get_secret_value() not in repr(result)
    selects = [sql for sql in statements if sql.startswith("SELECT")]
    assert "FOR UPDATE" not in selects[0]
    assert "code_digest" not in selects[0] and "link_token_digest," not in selects[0]
    assert "FROM user_emails" in selects[1] and "FOR UPDATE" in selects[1]
    assert "FROM users" in selects[2] and "FOR UPDATE" in selects[2]
    assert "FROM email_verification_challenges" in selects[3] and "FOR UPDATE" in selects[3]
    assert selects[4] == "SELECT clock_timestamp()"
    assert sum("clock_timestamp()" in sql for sql in selects) == 1
    before = snapshot(session, seed)
    assert isinstance(perform(session, seed), consume.AlreadyConsumed)
    assert snapshot(session, seed) == before


def test_display_code_is_accepted(postgresql_session: Session) -> None:
    seed = seed_challenge(postgresql_session, Material.CODE)
    assert isinstance(
        perform(postgresql_session, seed, code="0123 4567"), consume.ConsumedEmailVerification
    )


@pytest.mark.parametrize(
    "code",
    [
        "",
        "1234567",
        "123456789",
        "0123-4567",
        " 01234567",
        "01234567\n",
        "０１２３４５６７",
        "0123  4567",
        "0123\t4567",
    ],
)
def test_malformed_code_changes_nothing(postgresql_session: Session, code: str) -> None:
    seed = seed_challenge(postgresql_session, Material.CODE)
    before = snapshot(postgresql_session, seed)
    assert isinstance(perform(postgresql_session, seed, code=code), consume.MalformedCode)
    assert snapshot(postgresql_session, seed) == before


def test_wrong_code_counts_through_fifth_attempt(postgresql_session: Session) -> None:
    seed = seed_challenge(postgresql_session, Material.CODE)
    for count in range(1, 5):
        assert perform(postgresql_session, seed, code="99999999") == consume.WrongCode(
            count, 5 - count
        )
    assert isinstance(perform(postgresql_session, seed, code="99999999"), consume.AttemptsExhausted)
    user, email, target = rows(postgresql_session, seed)
    assert target.attempt_count == 5
    assert target.invalidation_reason is Reason.ATTEMPTS_EXHAUSTED
    assert target.invalidated_at is not None and target.consumed_at is None
    assert user.status is AccountStatus.PENDING_VERIFICATION and email.verified_at is None
    before = snapshot(postgresql_session, seed)
    assert perform(postgresql_session, seed) == consume.Invalidated(Reason.ATTEMPTS_EXHAUSTED)
    assert snapshot(postgresql_session, seed) == before


@pytest.mark.parametrize("material", list(Material))
@pytest.mark.parametrize(
    "state,outcome",
    [
        ("consumed", consume.AlreadyConsumed),
        ("invalidated", consume.Invalidated),
        ("expired", consume.Expired),
    ],
)
def test_terminal_and_expiry_precede_account_and_material_checks(
    postgresql_session: Session, material: Material, state: str, outcome: type[object]
) -> None:
    session = postgresql_session
    seed = seed_challenge(session, material)
    user, email, target = rows(session, seed)
    timestamp = database_time(session)
    user.status = AccountStatus.LOCKED
    email.verified_at = timestamp
    target.expires_at = timestamp
    if state == "consumed":
        target.consumed_at = timestamp - timedelta(seconds=1)
    elif state == "invalidated":
        target.invalidated_at = timestamp - timedelta(seconds=1)
        target.invalidation_reason = Reason.SUPERSEDED
    session.flush()
    before = snapshot(session, seed)
    assert isinstance(perform(session, seed, code="malformed"), outcome)
    assert snapshot(session, seed) == before


@pytest.mark.parametrize("initial_count", [0, 4])
@pytest.mark.parametrize("commit", [False, True])
def test_attempt_result_obeys_outer_commit_or_rollback(
    migrated_postgresql_engine: Engine, initial_count: int, commit: bool
) -> None:
    engine = migrated_postgresql_engine
    with committed_seed(engine, Material.CODE) as seed:
        with Session(engine) as session, session.begin():
            rows(session, seed)[2].attempt_count = initial_count
        with Session(engine) as session:
            before = snapshot(session, seed)
            result = perform(session, seed, code="99999999")
            assert isinstance(
                result, consume.WrongCode if initial_count == 0 else consume.AttemptsExhausted
            )
            assert session.in_transaction() and not session.in_nested_transaction()
            with Session(engine) as observer:
                assert snapshot(observer, seed) == before
            if commit:
                session.commit()
            else:
                session.rollback()
        with Session(engine) as observer:
            target = rows(observer, seed)[2]
            assert target.attempt_count == initial_count + int(commit)
            assert (target.invalidated_at is not None) == (commit and initial_count == 4)
            if not commit:
                assert snapshot(observer, seed) == before


@pytest.mark.parametrize("material", list(Material))
@pytest.mark.parametrize(
    "status", [AccountStatus.ACTIVE, AccountStatus.LOCKED, AccountStatus.DISABLED]
)
def test_ineligible_account_never_activates(
    postgresql_session: Session, material: Material, status: AccountStatus
) -> None:
    session = postgresql_session
    seed = seed_challenge(session, material)
    user, email, target = rows(session, seed)
    user.status = status
    session.flush()
    assert perform(session, seed, code="bad") == consume.AccountNotEligible(seed.email_id, status)
    assert user.status is status and email.verified_at is None
    assert target.invalidation_reason is Reason.ACCOUNT_STATE_CHANGED
    assert target.invalidated_at is not None and target.consumed_at is None
    assert target.attempt_count == (0 if material is Material.CODE else None)


@pytest.mark.parametrize("material", list(Material))
@pytest.mark.parametrize("status", list(AccountStatus))
def test_verified_email_precedes_account_state_without_changing_user(
    postgresql_session: Session, material: Material, status: AccountStatus
) -> None:
    session = postgresql_session
    seed = seed_challenge(session, material)
    user, email, target = rows(session, seed)
    user.status = status
    email.verified_at = database_time(session)
    session.flush()
    updated_at, verified_at = user.updated_at, email.verified_at
    assert perform(session, seed, code="bad") == consume.AlreadyVerified(seed.email_id)
    assert user.status is status and user.updated_at == updated_at
    assert email.verified_at == verified_at
    assert target.invalidation_reason is Reason.EMAIL_ALREADY_VERIFIED
    assert target.consumed_at is None


@pytest.mark.parametrize("material", list(Material))
def test_success_invalidates_only_live_siblings(
    postgresql_session: Session, material: Material
) -> None:
    session = postgresql_session
    seed = seed_challenge(session, material)
    other = seed_challenge(session, Material.LINK)
    unrelated = snapshot(session, other)
    timestamp = database_time(session)
    siblings: list[Challenge] = []
    for state in ("live-link", "live-code", "expired", "consumed", "invalidated"):
        sibling = Challenge(
            user_email_id=seed.email_id,
            material_type=Material.LINK,
            link_token_digest=generate_link_token().digest,
            created_at=timestamp - timedelta(minutes=2),
            expires_at=timestamp + timedelta(minutes=5),
        )
        if state == "live-code":
            sibling.material_type = Material.CODE
            sibling.link_token_digest = None
            sibling.code_digest = b"c" * 32
            sibling.hmac_key_version = "previous"
            sibling.attempt_count = 2
            sibling.max_attempts = 5
        elif state == "expired":
            sibling.expires_at = timestamp
        elif state == "consumed":
            sibling.consumed_at = timestamp
        elif state == "invalidated":
            sibling.invalidated_at = timestamp
            sibling.invalidation_reason = Reason.KEY_COMPROMISED
        session.add(sibling)
        siblings.append(sibling)
    session.flush()
    unchanged = [(s.consumed_at, s.invalidated_at, s.invalidation_reason) for s in siblings[2:]]
    result = perform(session, seed)
    assert isinstance(result, consume.ConsumedEmailVerification)
    for sibling in siblings[:2]:
        assert sibling.invalidated_at == result.consumed_at
        assert sibling.invalidation_reason is Reason.EMAIL_ALREADY_VERIFIED
        assert sibling.consumed_at is None
    assert siblings[1].attempt_count == 2
    assert [
        (s.consumed_at, s.invalidated_at, s.invalidation_reason) for s in siblings[2:]
    ] == unchanged
    assert snapshot(session, other) == unrelated


@pytest.mark.parametrize("material", list(Material))
@pytest.mark.parametrize("commit", [False, True])
def test_success_is_atomic_and_caller_owned(
    migrated_postgresql_engine: Engine, material: Material, commit: bool
) -> None:
    engine = migrated_postgresql_engine
    with committed_seed(engine, material) as seed:
        with Session(engine) as session, session.begin():
            timestamp = database_time(session)
            sibling = Challenge(
                user_email_id=seed.email_id,
                material_type=Material.LINK,
                link_token_digest=generate_link_token().digest,
                created_at=timestamp,
                expires_at=timestamp + timedelta(minutes=5),
            )
            session.add(sibling)
            session.flush()
            sibling_id = sibling.id
        with Session(engine) as session:
            before = snapshot(session, seed)
            assert isinstance(perform(session, seed), consume.ConsumedEmailVerification)
            with Session(engine) as observer:
                assert snapshot(observer, seed) == before
            if commit:
                session.commit()
            else:
                session.rollback()
        with Session(engine) as observer:
            user, email, target = rows(observer, seed)
            observed_sibling = observer.get(Challenge, sibling_id)
            assert observed_sibling is not None
            assert (target.consumed_at is not None) == commit
            assert (email.verified_at is not None) == commit
            assert (user.status is AccountStatus.ACTIVE) == commit
            assert (observed_sibling.invalidated_at is not None) == commit
            if not commit:
                assert snapshot(observer, seed) == before


def test_unknown_key_and_exhausted_fail_closed(
    postgresql_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = postgresql_session
    seed = seed_challenge(session, Material.CODE)
    before = snapshot(session, seed)
    assert isinstance(
        consume.consume_email_verification_code(
            session,
            challenge_id=seed.challenge_id,
            code=seed.plaintext.get_secret_value(),
            keyring=keyring(previous=False),
        ),
        consume.KeyVersionUnavailable,
    )
    assert snapshot(session, seed) == before
    target = rows(session, seed)[2]
    target.attempt_count = 5
    session.flush()

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("exhausted challenge must not resolve a key or verify HMAC")

    monkeypatch.setattr(EmailVerificationHmacKeyring, "key_for_version", forbidden)
    monkeypatch.setattr(consume, "verify_email_verification_code_digest", forbidden)
    assert isinstance(perform(session, seed), consume.AttemptsExhausted)
    assert target.attempt_count == 5
    assert target.invalidation_reason is Reason.ATTEMPTS_EXHAUSTED
    assert target.consumed_at is None


@pytest.mark.parametrize("material", list(Material))
@pytest.mark.parametrize("state", ["new", "dirty", "deleted"])
def test_clean_session_guard_preserves_caller_state(
    postgresql_session: Session, material: Material, state: str
) -> None:
    session = postgresql_session
    seed = seed_challenge(session, material)
    unrelated = User(status=AccountStatus.PENDING_VERIFICATION)
    session.add(unrelated)
    if state != "new":
        session.flush()
        if state == "dirty":
            unrelated.security_version = 1
        else:
            session.delete(unrelated)
    with pytest.raises(consume.EmailVerificationConsumeTransactionStateError):
        perform(session, seed)
    assert unrelated in getattr(session, state)
    assert not session.in_nested_transaction()


def test_typed_boundaries_and_missing_material(postgresql_session: Session) -> None:
    session = postgresql_session
    with pytest.raises(TypeError, match="challenge_id"):
        consume.consume_email_verification_code(
            session,
            challenge_id="invalid",  # type: ignore[arg-type]
            code="01234567",
            keyring=keyring(),
        )
    with pytest.raises(TypeError, match="code"):
        consume.consume_email_verification_code(
            session,
            challenge_id=uuid.uuid4(),
            code=None,  # type: ignore[arg-type]
            keyring=keyring(),
        )
    with pytest.raises(TypeError, match="keyring"):
        consume.consume_email_verification_code(
            session,
            challenge_id=uuid.uuid4(),
            code="01234567",
            keyring=None,  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match="external_token"):
        consume.consume_email_verification_link(session, external_token=None)  # type: ignore[arg-type]
    assert isinstance(
        consume.consume_email_verification_code(
            session,
            challenge_id=uuid.uuid4(),
            code="01234567",
            keyring=keyring(),
        ),
        consume.InvalidChallenge,
    )
    token = generate_link_token().external_token
    for value in ("", token + "=", "!" * 43, "A" * 42 + "B", token):
        assert isinstance(
            consume.consume_email_verification_link(session, external_token=value),
            consume.InvalidChallenge,
        )
    seed = seed_challenge(session, Material.LINK)
    assert isinstance(
        consume.consume_email_verification_code(
            session,
            challenge_id=seed.challenge_id,
            code="01234567",
            keyring=keyring(),
        ),
        consume.InvalidChallenge,
    )


@pytest.mark.parametrize("material", list(Material))
@pytest.mark.parametrize("changed", ["email", "user", "challenge", "attempts", "digest"])
def test_authoritative_locks_refresh_identity_map(
    migrated_postgresql_engine: Engine, material: Material, changed: str
) -> None:
    engine = migrated_postgresql_engine
    with committed_seed(engine, material) as seed, Session(engine) as session_a:
        user_a, email_a, target_a = rows(session_a, seed)
        with Session(engine) as session_b, session_b.begin():
            user_b, email_b, target_b = rows(session_b, seed)
            timestamp = database_time(session_b)
            if changed == "email":
                email_b.verified_at = timestamp
            elif changed == "user":
                user_b.status = AccountStatus.LOCKED
            elif changed == "challenge":
                target_b.invalidated_at = timestamp
                target_b.invalidation_reason = Reason.SUPERSEDED
            elif changed == "attempts" and material is Material.CODE:
                target_b.attempt_count = 4
            elif changed == "digest" and material is Material.CODE:
                target_b.code_digest = b"x" * 32
            else:
                target_b.expires_at = timestamp
        result = perform(session_a, seed, code="99999999" if changed == "attempts" else None)
        if changed == "email":
            assert isinstance(result, consume.AlreadyVerified) and email_a.verified_at is not None
        elif changed == "user":
            assert (
                isinstance(result, consume.AccountNotEligible)
                and user_a.status is AccountStatus.LOCKED
            )
        elif changed == "challenge":
            assert result == consume.Invalidated(Reason.SUPERSEDED)
            assert target_a.invalidation_reason is Reason.SUPERSEDED
        elif changed == "attempts" and material is Material.CODE:
            assert isinstance(result, consume.AttemptsExhausted) and target_a.attempt_count == 5
        elif changed == "digest" and material is Material.CODE:
            assert result == consume.WrongCode(1, 4)
        else:
            assert isinstance(result, consume.Expired)
        assert target_a.consumed_at is None
        session_a.rollback()


def wait_for_block(engine: Engine, blocked_pid: int, blocking_pid: int) -> None:
    deadline = monotonic() + 5
    wait = threading.Event()
    with Session(engine) as observer:
        while monotonic() < deadline:
            blockers = observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": blocked_pid})
            if isinstance(blockers, list) and blocking_pid in blockers:
                return
            wait.wait(0.02)
    pytest.fail("PostgreSQL did not report the expected lock dependency")


def test_locked_siblings_refresh_cached_fields(migrated_postgresql_engine: Engine) -> None:
    engine = migrated_postgresql_engine
    with committed_seed(engine, Material.LINK) as seed:
        with Session(engine) as session, session.begin():
            timestamp = database_time(session)
            sibling = Challenge(
                user_email_id=seed.email_id,
                material_type=Material.CODE,
                code_digest=b"c" * 32,
                hmac_key_version="previous",
                attempt_count=0,
                max_attempts=5,
                created_at=timestamp,
                expires_at=timestamp + timedelta(minutes=5),
            )
            session.add(sibling)
            session.flush()
            sibling_id = sibling.id
        with Session(engine) as session_a:
            cached = session_a.get(Challenge, sibling_id)
            assert cached is not None and cached.attempt_count == 0
            with Session(engine) as session_b, session_b.begin():
                fresh = session_b.get(Challenge, sibling_id)
                assert fresh is not None
                fresh.attempt_count = 3
            result = perform(session_a, seed)
            assert isinstance(result, consume.ConsumedEmailVerification)
            assert cached.attempt_count == 3
            assert cached.invalidated_at == result.consumed_at
            assert cached.invalidation_reason is Reason.EMAIL_ALREADY_VERIFIED
            session_a.rollback()


def test_flush_failure_rolls_back_whole_savepoint_only(postgresql_session: Session) -> None:
    session = postgresql_session
    seed = seed_challenge(session, Material.CODE)
    timestamp = database_time(session)
    sibling = Challenge(
        user_email_id=seed.email_id,
        material_type=Material.LINK,
        link_token_digest=generate_link_token().digest,
        created_at=timestamp,
        expires_at=timestamp + timedelta(minutes=5),
    )
    session.add(sibling)
    session.flush()
    sibling_id = sibling.id
    before = snapshot(session, seed)

    def fail_after_sibling_flush(flushing_session: Session, context: Any) -> None:
        if sibling.invalidation_reason is Reason.EMAIL_ALREADY_VERIFIED:
            raise RuntimeError("test failure after sibling flush")

    event.listen(session, "after_flush", fail_after_sibling_flush)
    try:
        with pytest.raises(RuntimeError, match="test failure"):
            perform(session, seed)
    finally:
        event.remove(session, "after_flush", fail_after_sibling_flush)
    assert session.is_active and session.in_transaction()
    assert not session.in_nested_transaction()
    assert snapshot(session, seed) == before
    restored = session.get(Challenge, sibling_id)
    assert restored is not None and restored.invalidated_at is None


def worker(
    engine: Engine, seed: Seed, pid_queue: Queue[int], *, resend: bool = False
) -> consume.EmailVerificationConsumeOutcome | issuance.EmailVerificationIssuanceOutcome:
    with Session(engine) as session, session.begin():
        session.execute(text("SET LOCAL lock_timeout = '10s'"))
        pid = session.scalar(text("SELECT pg_backend_pid()"))
        assert isinstance(pid, int)
        pid_queue.put(pid)
        if resend:
            return issuance.stage_email_verification(
                session,
                user_email_id=seed.email_id,
                material_type=Material.LINK,
            )
        return perform(session, seed)


def test_consume_blocks_on_user_email_anchor_and_rechecks_after_commit(
    migrated_postgresql_engine: Engine,
) -> None:
    engine = migrated_postgresql_engine
    with (
        committed_seed(engine, Material.LINK) as seed,
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        worker_pids: Queue[int] = Queue()
        with Session(engine) as session_a, session_a.begin():
            pid_a = session_a.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(pid_a, int)
            locked_email = session_a.scalar(
                select(UserEmail).where(UserEmail.id == seed.email_id).with_for_update()
            )
            assert locked_email is not None

            future = executor.submit(worker, engine, seed, worker_pids)
            pid_b = worker_pids.get(timeout=5)
            # A holds only UserEmail. Removing consume's UserEmail FOR UPDATE would let B
            # reach User/Challenge without blocking here, so this is a lock-anchor proof.
            wait_for_block(engine, pid_b, pid_a)

            locked_email.verified_at = database_time(session_a)

        result = future.result(timeout=10)
        assert result == consume.AlreadyVerified(user_email_id=seed.email_id)
        with Session(engine) as observer:
            user, email, target = rows(observer, seed)
            assert email.verified_at is not None
            assert user.status is AccountStatus.PENDING_VERIFICATION
            assert target.consumed_at is None
            assert target.invalidated_at is not None
            assert target.invalidation_reason is Reason.EMAIL_ALREADY_VERIFIED


@pytest.mark.parametrize("material", list(Material))
@pytest.mark.parametrize("race", ["consume-consume", "consume-resend", "resend-consume"])
def test_concurrent_operations_serialize_on_user_email(
    migrated_postgresql_engine: Engine, material: Material, race: str
) -> None:
    engine = migrated_postgresql_engine
    with committed_seed(engine, material) as seed, ThreadPoolExecutor(max_workers=1) as executor:
        pids: Queue[int] = Queue()
        with Session(engine) as first, first.begin():
            pid = first.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            if race == "resend-consume":
                winner = issuance.stage_email_verification(
                    first,
                    user_email_id=seed.email_id,
                    material_type=Material.LINK,
                )
                assert isinstance(winner, issuance.StagedLinkChallenge)
            else:
                consumed = perform(first, seed)
                assert isinstance(consumed, consume.ConsumedEmailVerification)
            future = executor.submit(worker, engine, seed, pids, resend=race == "consume-resend")
            wait_for_block(engine, pids.get(timeout=5), pid)
        loser = future.result(timeout=10)
        with Session(engine) as observer:
            user, email, target = rows(observer, seed)
            challenges = observer.scalars(
                select(Challenge).where(Challenge.user_email_id == seed.email_id)
            ).all()
            if race == "resend-consume":
                assert loser == consume.Invalidated(Reason.SUPERSEDED)
                assert target.consumed_at is None and email.verified_at is None
                assert user.status is AccountStatus.PENDING_VERIFICATION
                assert len(challenges) == 2
            else:
                assert isinstance(
                    loser,
                    consume.AlreadyConsumed
                    if race == "consume-consume"
                    else issuance.AlreadyVerified,
                )
                assert user.status is AccountStatus.ACTIVE and email.verified_at is not None
                assert sum(row.consumed_at is not None for row in challenges) == 1
                assert len(challenges) == 1


@pytest.mark.parametrize("material", list(Material))
@pytest.mark.parametrize("change", ["deleted", "binding", "material", "digest", "expired"])
def test_locator_is_untrusted_until_post_lock_reload(
    migrated_postgresql_engine: Engine, material: Material, change: str
) -> None:
    engine = migrated_postgresql_engine
    with committed_seed(engine, material) as seed, committed_seed(engine, Material.LINK) as other:
        with ThreadPoolExecutor(max_workers=1) as executor:
            pids: Queue[int] = Queue()
            with Session(engine) as first, first.begin():
                pid = first.scalar(text("SELECT pg_backend_pid()"))
                assert isinstance(pid, int)
                first.scalar(
                    select(UserEmail).where(UserEmail.id == seed.email_id).with_for_update()
                )
                first.scalar(select(User).where(User.id == seed.user_id).with_for_update())
                future = executor.submit(worker, engine, seed, pids)
                # Worker reached UserEmail lock after successfully resolving the locator.
                wait_for_block(engine, pids.get(timeout=5), pid)
                target = first.scalar(
                    select(Challenge).where(Challenge.id == seed.challenge_id).with_for_update()
                )
                assert target is not None
                if change == "deleted":
                    first.delete(target)
                elif change == "binding":
                    target.user_email_id = other.email_id
                elif change == "material":
                    if material is Material.CODE:
                        target.material_type = Material.LINK
                        target.link_token_digest = generate_link_token().digest
                        target.code_digest = target.hmac_key_version = None
                        target.attempt_count = target.max_attempts = None
                    else:
                        target.material_type = Material.CODE
                        target.link_token_digest = None
                        target.code_digest = b"c" * 32
                        target.hmac_key_version = "previous"
                        target.attempt_count = 0
                        target.max_attempts = 5
                elif change == "digest":
                    if material is Material.LINK:
                        target.link_token_digest = generate_link_token().digest
                    else:
                        target.code_digest = b"x" * 32
                else:
                    target.expires_at = database_time(first)
            result = future.result(timeout=10)
        if change == "expired":
            assert isinstance(result, consume.Expired)
        elif change == "digest" and material is Material.CODE:
            assert result == consume.WrongCode(1, 4)
        else:
            assert isinstance(result, consume.InvalidChallenge)
        with Session(engine) as observer:
            assert observer.get(User, seed.user_id).status is AccountStatus.PENDING_VERIFICATION  # type: ignore[union-attr]
            assert observer.get(UserEmail, seed.email_id).verified_at is None  # type: ignore[union-attr]
