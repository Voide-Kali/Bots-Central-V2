import base64
import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, event, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.auth import email_verification_application as application
from app.auth import email_verification_consume as consume
from app.auth import email_verification_issuance as issuance
from app.auth.email_verification_delivery import (
    DeliveryDispatched,
    DeliveryFailed,
    DeliveryIntent,
    dispatch_delivery,
)
from app.auth.email_verification_materials import EmailVerificationHmacKeyring
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
from app.db.models import PasswordCredential, User, UserEmail

pytestmark = pytest.mark.postgresql

SessionFactory = Callable[[], Session]


def session_factory(engine: Engine) -> SessionFactory:
    return lambda: Session(engine)


def keyring() -> EmailVerificationHmacKeyring:
    def encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    return EmailVerificationHmacKeyring(
        active_key_version="current",
        keys={"current": SecretStr(encode(b"a" * 32))},
    )


def database_time(session: Session) -> datetime:
    value = session.scalar(text("SELECT clock_timestamp()"))
    assert isinstance(value, datetime)
    return value


def row_counts(session: Session, email: str) -> tuple[int, int, int, int]:
    from sqlalchemy import func

    user_ids = select(User.id).join(UserEmail).where(UserEmail.email_canonical == email)
    email_ids = select(UserEmail.id).where(UserEmail.email_canonical == email)
    return (
        session.scalar(select(func.count()).select_from(User).where(User.id.in_(user_ids))) or 0,
        session.scalar(
            select(func.count()).select_from(UserEmail).where(UserEmail.email_canonical == email)
        )
        or 0,
        session.scalar(
            select(func.count())
            .select_from(PasswordCredential)
            .where(PasswordCredential.user_id.in_(user_ids))
        )
        or 0,
        session.scalar(
            select(func.count())
            .select_from(Challenge)
            .where(Challenge.user_email_id.in_(email_ids))
        )
        or 0,
    )


@contextmanager
def cleanup_email(engine: Engine, email: str) -> Generator[None, None, None]:
    def cleanup() -> None:
        with Session(engine) as session, session.begin():
            email_rows = session.execute(
                select(UserEmail.id, UserEmail.user_id).where(UserEmail.email_canonical == email)
            ).all()
            email_ids = [row[0] for row in email_rows]
            user_ids = [row[1] for row in email_rows]
            if email_ids:
                session.execute(delete(Challenge).where(Challenge.user_email_id.in_(email_ids)))
                session.execute(
                    delete(PasswordCredential).where(PasswordCredential.user_id.in_(user_ids))
                )
                session.execute(delete(UserEmail).where(UserEmail.id.in_(email_ids)))
                session.execute(delete(User).where(User.id.in_(user_ids)))

    try:
        yield
    except BaseException:
        try:
            cleanup()
        except BaseException:
            pass
        raise
    else:
        cleanup()


def register_and_stage(engine: Engine, email: str, material: Material) -> DeliveryIntent:
    result = application.register_and_stage_email_verification(
        session_factory(engine),
        email=email,
        password="a sufficiently long registration password",
        material_type=material,
        keyring=keyring() if material is Material.CODE else None,
    )
    assert result.delivery_intent is not None
    return result.delivery_intent


@pytest.mark.parametrize("material", list(Material))
def test_registration_and_issuance_are_one_outer_transaction(
    migrated_postgresql_engine: Engine, material: Material, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = migrated_postgresql_engine
    email = f"application-atomic-{uuid.uuid4()}@example.com"
    commits: list[None] = []

    def count_commit(connection: Any) -> None:
        commits.append(None)

    original_stage = issuance.stage_email_verification

    def assert_clean_then_stage(*args: Any, **kwargs: Any) -> Any:
        session = args[0]
        assert not session.new and not session.dirty and not session.deleted
        return original_stage(*args, **kwargs)

    event.listen(engine, "commit", count_commit)
    monkeypatch.setattr(application, "stage_email_verification", assert_clean_then_stage)
    try:
        with cleanup_email(engine, email):
            intent = register_and_stage(engine, email, material)
            assert intent.recipient == email
            assert intent.material_type is material
            with Session(engine) as session:
                assert row_counts(session, email) == (1, 1, 1, 1)
                primary = session.scalar(
                    select(UserEmail).where(
                        UserEmail.email_canonical == email, UserEmail.is_primary.is_(True)
                    )
                )
                challenge = session.get(Challenge, intent.challenge_id)
                assert primary is not None and challenge is not None
                assert challenge.user_email_id == primary.id
            assert len(commits) == 1
    finally:
        event.remove(engine, "commit", count_commit)


@pytest.mark.parametrize("material", list(Material))
def test_registration_rollback_removes_everything_on_staging_exception(
    migrated_postgresql_engine: Engine, material: Material, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = migrated_postgresql_engine
    email = f"application-rollback-{uuid.uuid4()}@example.com"
    original_stage = issuance.stage_email_verification

    def stage_then_fail(*args: Any, **kwargs: Any) -> Any:
        original_stage(*args, **kwargs)
        raise RuntimeError("test staging failure")

    monkeypatch.setattr(application, "stage_email_verification", stage_then_fail)
    with pytest.raises(RuntimeError, match="test staging failure"):
        application.register_and_stage_email_verification(
            session_factory(engine),
            email=email,
            password="a sufficiently long registration password",
            material_type=material,
            keyring=keyring() if material is Material.CODE else None,
        )
    with Session(engine) as session:
        assert row_counts(session, email) == (0, 0, 0, 0)


@pytest.mark.parametrize(
    "outcome_factory",
    [
        lambda user_email_id: issuance.NotFound(user_email_id=user_email_id),
        lambda user_email_id: issuance.AlreadyVerified(user_email_id=user_email_id),
        lambda user_email_id: issuance.AccountNotEligible(
            user_email_id=user_email_id, account_status=AccountStatus.ACTIVE
        ),
        lambda user_email_id: issuance.CooldownActive(
            user_email_id=user_email_id,
            retry_at=datetime(2030, 1, 1, tzinfo=UTC),
        ),
    ],
    ids=["not-found", "already-verified", "account-not-eligible", "cooldown"],
)
def test_registration_rolls_back_when_issuance_does_not_stage(
    migrated_postgresql_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    outcome_factory: Callable[[uuid.UUID], issuance.EmailVerificationIssuanceOutcome],
) -> None:
    engine = migrated_postgresql_engine
    email = f"application-non-staged-{uuid.uuid4()}@example.com"

    def return_non_staged(*args: Any, **kwargs: Any) -> issuance.EmailVerificationIssuanceOutcome:
        user_email_id = kwargs["user_email_id"]
        assert isinstance(user_email_id, uuid.UUID)
        return outcome_factory(user_email_id)

    monkeypatch.setattr(application, "stage_email_verification", return_non_staged)
    with pytest.raises(application.EmailVerificationApplicationInvariantError):
        application.register_and_stage_email_verification(
            session_factory(engine),
            email=email,
            password="a sufficiently long registration password",
            material_type=Material.LINK,
        )
    with Session(engine) as session:
        assert row_counts(session, email) == (0, 0, 0, 0)


def test_duplicate_registration_has_no_delivery_intent(migrated_postgresql_engine: Engine) -> None:
    engine = migrated_postgresql_engine
    email = f"application-duplicate-{uuid.uuid4()}@example.com"
    with cleanup_email(engine, email):
        register_and_stage(engine, email, Material.LINK)
        duplicate = application.register_and_stage_email_verification(
            session_factory(engine),
            email=email,
            password="a sufficiently long registration password",
            material_type=Material.LINK,
        )
        assert isinstance(duplicate.public_outcome, application.RegistrationAccepted)
        assert duplicate.delivery_intent is None
        with Session(engine) as session:
            assert row_counts(session, email) == (1, 1, 1, 1)


@pytest.mark.parametrize("material", list(Material))
def test_commit_failure_cannot_return_delivery_intent(
    migrated_postgresql_engine: Engine, material: Material
) -> None:
    engine = migrated_postgresql_engine
    email = f"application-commit-failure-{uuid.uuid4()}@example.com"

    def fail_commit(connection: Any) -> None:
        raise RuntimeError("test commit failure")

    event.listen(engine, "commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="test commit failure"):
            application.register_and_stage_email_verification(
                session_factory(engine),
                email=email,
                password="a sufficiently long registration password",
                material_type=material,
                keyring=keyring() if material is Material.CODE else None,
            )
    finally:
        event.remove(engine, "commit", fail_commit)
    with Session(engine) as session:
        assert row_counts(session, email) == (0, 0, 0, 0)


@pytest.mark.parametrize("material", list(Material))
def test_delivery_intent_is_orm_free_session_free_and_redacted(
    migrated_postgresql_engine: Engine, material: Material
) -> None:
    engine = migrated_postgresql_engine
    email = f"application-intent-{uuid.uuid4()}@example.com"
    with cleanup_email(engine, email):
        result = application.register_and_stage_email_verification(
            session_factory(engine),
            email=email,
            password="a sufficiently long registration password",
            material_type=material,
            keyring=keyring() if material is Material.CODE else None,
        )
        intent = result.delivery_intent
        assert intent is not None
        secret = intent.material.get_secret_value()
        assert secret not in repr(intent)
        assert email not in repr(intent)
        assert secret not in repr(result)
        assert email not in repr(result)
        assert all(not hasattr(value, "_sa_instance_state") for value in vars(intent).values())
        with Session(engine) as observer:
            challenge = observer.get(Challenge, intent.challenge_id)
            assert challenge is not None
            assert secret not in repr(challenge)
            assert "material" not in challenge.__dict__


def test_resend_outcomes_control_delivery_intent(migrated_postgresql_engine: Engine) -> None:
    engine = migrated_postgresql_engine
    email = f"application-resend-{uuid.uuid4()}@example.com"
    unknown = application.resend_email_verification(
        session_factory(engine),
        email=f"unknown-{uuid.uuid4()}@example.com",
        material_type=Material.LINK,
    )
    assert unknown.delivery_intent is None
    with cleanup_email(engine, email):
        intent = register_and_stage(engine, email, Material.LINK)
        cooldown = application.resend_email_verification(
            session_factory(engine), email=email, material_type=Material.LINK
        )
        assert cooldown.delivery_intent is None
        with Session(engine) as session, session.begin():
            user_email = session.scalar(select(UserEmail).where(UserEmail.email_canonical == email))
            assert user_email is not None
            user_email.verified_at = database_time(session)
        verified = application.resend_email_verification(
            session_factory(engine), email=email, material_type=Material.LINK
        )
        assert verified.delivery_intent is None
        assert intent.material.get_secret_value() not in repr(verified)


def test_resend_success_and_ineligible_have_expected_intents(
    migrated_postgresql_engine: Engine,
) -> None:
    engine = migrated_postgresql_engine
    email = f"application-resend-success-{uuid.uuid4()}@example.com"
    with cleanup_email(engine, email):
        with Session(engine) as session, session.begin():
            user = User(status=AccountStatus.PENDING_VERIFICATION)
            session.add(user)
            session.flush()
            session.add(
                UserEmail(
                    user_id=user.id, email_canonical=email, email_display=email, is_primary=True
                )
            )
        result = application.resend_email_verification(
            session_factory(engine), email=email, material_type=Material.LINK
        )
        assert result.delivery_intent is not None
        secret = result.delivery_intent.material.get_secret_value()
        assert secret not in repr(result)
        assert email not in repr(result)
        with Session(engine) as session, session.begin():
            locked_user = session.scalar(
                select(User).join(UserEmail).where(UserEmail.email_canonical == email)
            )
            assert locked_user is not None
            locked_user.status = AccountStatus.LOCKED
        ineligible = application.resend_email_verification(
            session_factory(engine), email=email, material_type=Material.LINK
        )
        assert ineligible.delivery_intent is None


def test_consume_application_commits_all_mutating_normal_outcomes(
    migrated_postgresql_engine: Engine,
) -> None:
    engine = migrated_postgresql_engine
    email = f"application-consume-{uuid.uuid4()}@example.com"
    with cleanup_email(engine, email):
        code_intent = register_and_stage(engine, email, Material.CODE)
        for count in range(1, 5):
            result = application.consume_email_verification_code_application(
                session_factory(engine),
                challenge_id=code_intent.challenge_id,
                code="99999999",
                keyring=keyring(),
            )
            assert result.outcome == consume.WrongCode(count, 5 - count)
        exhausted = application.consume_email_verification_code_application(
            session_factory(engine),
            challenge_id=code_intent.challenge_id,
            code="99999999",
            keyring=keyring(),
        )
        assert isinstance(exhausted.outcome, consume.AttemptsExhausted)
        with Session(engine) as session:
            challenge = session.get(Challenge, code_intent.challenge_id)
            assert challenge is not None and challenge.attempt_count == 5
            assert challenge.invalidation_reason is Reason.ATTEMPTS_EXHAUSTED


def test_consume_application_commits_success_and_defensive_outcomes(
    migrated_postgresql_engine: Engine,
) -> None:
    engine = migrated_postgresql_engine
    success_email = f"application-consume-success-{uuid.uuid4()}@example.com"
    verified_email = f"application-consume-verified-{uuid.uuid4()}@example.com"
    ineligible_email = f"application-consume-ineligible-{uuid.uuid4()}@example.com"
    with (
        cleanup_email(engine, success_email),
        cleanup_email(engine, verified_email),
        cleanup_email(engine, ineligible_email),
    ):
        success = register_and_stage(engine, success_email, Material.LINK)
        success_result = application.consume_email_verification_link_application(
            session_factory(engine), external_token=success.material.get_secret_value()
        )
        assert isinstance(success_result.outcome, consume.ConsumedEmailVerification)
        with Session(engine) as session:
            user = session.scalar(
                select(User).join(UserEmail).where(UserEmail.email_canonical == success_email)
            )
            assert user is not None and user.status is AccountStatus.ACTIVE

        verified = register_and_stage(engine, verified_email, Material.LINK)
        with Session(engine) as session, session.begin():
            row = session.scalar(
                select(UserEmail).where(UserEmail.email_canonical == verified_email)
            )
            assert row is not None
            row.verified_at = database_time(session)
        verified_result = application.consume_email_verification_link_application(
            session_factory(engine), external_token=verified.material.get_secret_value()
        )
        assert isinstance(verified_result.outcome, consume.AlreadyVerified)
        with Session(engine) as session:
            challenge = session.get(Challenge, verified.challenge_id)
            verified_user = session.scalar(
                select(User).join(UserEmail).where(UserEmail.email_canonical == verified_email)
            )
            assert challenge is not None and challenge.invalidated_at is not None
            assert challenge.invalidation_reason is Reason.EMAIL_ALREADY_VERIFIED
            assert verified_user is not None
            assert verified_user.status is AccountStatus.PENDING_VERIFICATION

        ineligible = register_and_stage(engine, ineligible_email, Material.LINK)
        with Session(engine) as session, session.begin():
            user = session.scalar(
                select(User).join(UserEmail).where(UserEmail.email_canonical == ineligible_email)
            )
            assert user is not None
            user.status = AccountStatus.LOCKED
        ineligible_result = application.consume_email_verification_link_application(
            session_factory(engine), external_token=ineligible.material.get_secret_value()
        )
        assert isinstance(ineligible_result.outcome, consume.AccountNotEligible)
        with Session(engine) as session:
            challenge = session.get(Challenge, ineligible.challenge_id)
            assert (
                challenge is not None
                and challenge.invalidation_reason is Reason.ACCOUNT_STATE_CHANGED
            )


def test_consume_database_exception_rolls_back(migrated_postgresql_engine: Engine) -> None:
    engine = migrated_postgresql_engine
    email = f"application-consume-rollback-{uuid.uuid4()}@example.com"
    with cleanup_email(engine, email):
        intent = register_and_stage(engine, email, Material.CODE)

        def fail_commit(connection: Any) -> None:
            raise RuntimeError("test consume commit failure")

        event.listen(engine, "commit", fail_commit)
        try:
            with pytest.raises(RuntimeError, match="test consume commit failure"):
                application.consume_email_verification_code_application(
                    session_factory(engine),
                    challenge_id=intent.challenge_id,
                    code="99999999",
                    keyring=keyring(),
                )
        finally:
            event.remove(engine, "commit", fail_commit)
        with Session(engine) as session:
            challenge = session.get(Challenge, intent.challenge_id)
            assert challenge is not None and challenge.attempt_count == 0


class RecordingAdapter:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[DeliveryIntent] = []

    def deliver(self, intent: DeliveryIntent) -> None:
        self.calls.append(intent)
        if self.error is not None:
            raise self.error


def test_dispatcher_attempts_once_and_sanitizes_provider_failure() -> None:
    secret = SecretStr("never-in-repr")
    intent = DeliveryIntent(
        recipient="recipient@example.com",
        challenge_id=uuid.uuid4(),
        expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        material_type=Material.LINK,
        material=secret,
    )
    delivered = RecordingAdapter()
    assert isinstance(dispatch_delivery(delivered, intent), DeliveryDispatched)
    assert delivered.calls == [intent]
    failed = RecordingAdapter(RuntimeError("provider secret body never-in-repr"))
    outcome = dispatch_delivery(failed, intent)
    assert isinstance(outcome, DeliveryFailed)
    assert len(failed.calls) == 1
    assert "never-in-repr" not in repr(outcome)
    assert "provider secret body" not in repr(outcome)
