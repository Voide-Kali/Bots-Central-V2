import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DatabaseSession

import app.auth.registration as registration
from app.auth.emails import EmailValidationError
from app.auth.passwords import PasswordPolicyError, verify_password
from app.auth.registration import (
    DuplicateEmailError,
    RegistrationTransactionStateError,
    register_user,
)
from app.db.enums import AccountStatus
from app.db.models import PasswordCredential, User, UserEmail


@pytest.mark.postgresql
def test_register_user_creates_pending_account_email_and_password(
    postgresql_session: DatabaseSession,
) -> None:
    password = "correct horse battery staple"

    result = register_user(
        postgresql_session,
        email="User.Name+tag@Example.COM",
        password=password,
    )

    user = postgresql_session.get(User, result.user_id)
    email = postgresql_session.scalar(select(UserEmail).where(UserEmail.user_id == result.user_id))
    credential = postgresql_session.get(PasswordCredential, result.user_id)

    assert result.account_status is AccountStatus.PENDING_VERIFICATION
    assert result.email_display == "User.Name+tag@Example.COM"
    assert user is not None
    assert user.status is AccountStatus.PENDING_VERIFICATION
    assert email is not None
    assert email.email_display == "User.Name+tag@Example.COM"
    assert email.email_canonical == "user.name+tag@example.com"
    assert email.is_primary
    assert email.verified_at is None
    assert credential is not None
    assert credential.password_hash.startswith("$argon2id$")
    assert password not in credential.password_hash
    assert verify_password(credential.password_hash, password)
    assert not hasattr(result, "password")
    assert not hasattr(result, "password_hash")


@pytest.mark.postgresql
def test_registration_rejects_invalid_input_before_persistence(
    postgresql_session: DatabaseSession,
) -> None:
    with pytest.raises(EmailValidationError):
        register_user(postgresql_session, email="not-an-email", password="a" * 15)
    with pytest.raises(PasswordPolicyError):
        register_user(postgresql_session, email="user@example.com", password="short")

    assert postgresql_session.scalar(select(func.count()).select_from(User)) == 0
    assert postgresql_session.scalar(select(func.count()).select_from(UserEmail)) == 0
    assert postgresql_session.scalar(select(func.count()).select_from(PasswordCredential)) == 0


@pytest.mark.postgresql
def test_duplicate_canonical_email_is_mapped_and_rolls_back_partial_records(
    postgresql_session: DatabaseSession,
) -> None:
    first = register_user(
        postgresql_session,
        email="User@Example.COM",
        password="correct horse battery staple",
    )

    with pytest.raises(DuplicateEmailError):
        register_user(
            postgresql_session,
            email="user@example.com",
            password="another correct horse battery staple",
        )

    assert postgresql_session.scalar(select(func.count()).select_from(User)) == 1
    assert postgresql_session.scalar(select(func.count()).select_from(UserEmail)) == 1
    assert postgresql_session.scalar(select(func.count()).select_from(PasswordCredential)) == 1
    assert postgresql_session.get(User, first.user_id) is not None


@pytest.mark.postgresql
def test_postgresql_constraint_remains_authoritative_for_canonical_email(
    postgresql_session: DatabaseSession,
) -> None:
    register_user(
        postgresql_session,
        email="User.Name+tag@Example.COM",
        password="correct horse battery staple",
    )

    with pytest.raises(DuplicateEmailError):
        register_user(
            postgresql_session,
            email="user.name+tag@example.com",
            password="another correct horse battery staple",
        )


@pytest.mark.postgresql
def test_registration_rejects_pending_new_state_before_hashing(
    postgresql_session: DatabaseSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unrelated_user = User(status=AccountStatus.ACTIVE)
    postgresql_session.add(unrelated_user)
    pending_before = set(postgresql_session.new)

    def hashing_must_not_run(password: str) -> str:
        pytest.fail("password hashing must not run with pending session state")

    monkeypatch.setattr(registration, "hash_password", hashing_must_not_run)

    with pytest.raises(RegistrationTransactionStateError, match="without pending"):
        register_user(
            postgresql_session,
            email="user@example.com",
            password="correct horse battery staple",
        )

    assert set(postgresql_session.new) == pending_before
    assert unrelated_user in postgresql_session.new


@pytest.mark.postgresql
def test_registration_rejects_dirty_state_without_changing_caller_object(
    postgresql_session: DatabaseSession,
) -> None:
    unrelated_user = User(status=AccountStatus.ACTIVE)
    postgresql_session.add(unrelated_user)
    postgresql_session.flush()
    unrelated_user.security_version = 1

    with pytest.raises(RegistrationTransactionStateError, match="without pending"):
        register_user(
            postgresql_session,
            email="user@example.com",
            password="correct horse battery staple",
        )

    assert unrelated_user in postgresql_session.dirty
    assert unrelated_user.security_version == 1
    assert not postgresql_session.new


@pytest.mark.postgresql
def test_registration_rejects_deleted_state_without_removing_caller_object(
    postgresql_session: DatabaseSession,
) -> None:
    unrelated_user = User(status=AccountStatus.ACTIVE)
    postgresql_session.add(unrelated_user)
    postgresql_session.flush()
    postgresql_session.delete(unrelated_user)

    with pytest.raises(RegistrationTransactionStateError, match="without pending"):
        register_user(
            postgresql_session,
            email="user@example.com",
            password="correct horse battery staple",
        )

    assert unrelated_user in postgresql_session.deleted
    assert not postgresql_session.new
