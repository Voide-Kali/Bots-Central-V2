import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DatabaseSession

from app.auth.repository import AuthRepository
from app.db.enums import AccountStatus, AuthenticationLevel, SessionRevocationReason
from app.db.models import AccessToken, PasswordCredential, RefreshToken, Session, User, UserEmail


def now() -> datetime:
    return datetime.now(UTC)


def create_user(session: DatabaseSession) -> User:
    user = User(status=AccountStatus.ACTIVE, security_version=0)
    session.add(user)
    session.flush()
    return user


def create_session(session: DatabaseSession, user: User) -> Session:
    created_at = now()
    auth_session = Session(
        user_id=user.id,
        created_at=created_at,
        last_seen_at=created_at,
        expires_at=created_at + timedelta(days=30),
        idle_expires_at=created_at + timedelta(days=7),
        security_version=user.security_version,
        client_metadata={"client_type": "test"},
        authentication_methods=["password"],
    )
    session.add(auth_session)
    session.flush()
    return auth_session


@pytest.mark.postgresql
def test_models_create_with_controlled_account_status(postgresql_session: DatabaseSession) -> None:
    user = create_user(postgresql_session)
    credential = PasswordCredential(
        user_id=user.id,
        password_hash="future-library-output",
        password_hash_version="future-policy-v1",
        password_hash_metadata={"algorithm": "argon2id"},
    )
    postgresql_session.add(credential)
    postgresql_session.flush()

    assert user.status is AccountStatus.ACTIVE
    assert credential.user_id == user.id

    stored_status = postgresql_session.scalar(
        text("SELECT status::text FROM users WHERE id = :user_id"), {"user_id": user.id}
    )
    postgresql_session.expire(user)
    assert stored_status == AccountStatus.ACTIVE.value
    assert user.status is AccountStatus.ACTIVE


@pytest.mark.postgresql
def test_canonical_email_is_unique(postgresql_session: DatabaseSession) -> None:
    first_user = create_user(postgresql_session)
    second_user = create_user(postgresql_session)
    email = "user@example.com"
    postgresql_session.add(
        UserEmail(user_id=first_user.id, email_canonical=email, email_display="User@Example.COM")
    )
    postgresql_session.flush()
    with pytest.raises(IntegrityError):
        with postgresql_session.begin_nested():
            postgresql_session.add(
                UserEmail(
                    user_id=second_user.id,
                    email_canonical=email,
                    email_display="user@example.com",
                )
            )
            postgresql_session.flush()

    assert postgresql_session.get(User, first_user.id) == first_user


@pytest.mark.postgresql
def test_security_version_must_not_be_negative(postgresql_session: DatabaseSession) -> None:
    with pytest.raises(IntegrityError):
        with postgresql_session.begin_nested():
            postgresql_session.add(User(status=AccountStatus.ACTIVE, security_version=-1))
            postgresql_session.flush()

    assert create_user(postgresql_session).status is AccountStatus.ACTIVE


@pytest.mark.postgresql
def test_session_expiration_and_revocation_fields(postgresql_session: DatabaseSession) -> None:
    user = create_user(postgresql_session)
    auth_session = create_session(postgresql_session, user)
    auth_session.revoked_at = now()
    auth_session.revocation_reason = SessionRevocationReason.USER_REVOKED
    postgresql_session.flush()

    assert auth_session.revocation_reason is SessionRevocationReason.USER_REVOKED
    stored_values = postgresql_session.execute(
        text(
            "SELECT authentication_level::text, revocation_reason::text "
            "FROM sessions WHERE id = :session_id"
        ),
        {"session_id": auth_session.id},
    ).one()
    postgresql_session.expire(auth_session)
    assert stored_values == (
        AuthenticationLevel.PASSWORD_AUTHENTICATED.value,
        SessionRevocationReason.USER_REVOKED.value,
    )
    assert auth_session.authentication_level is AuthenticationLevel.PASSWORD_AUTHENTICATED
    assert auth_session.revocation_reason is SessionRevocationReason.USER_REVOKED

    invalid_created_at = now()
    with pytest.raises(IntegrityError):
        with postgresql_session.begin_nested():
            postgresql_session.add(
                Session(
                    user_id=user.id,
                    created_at=invalid_created_at,
                    last_seen_at=invalid_created_at,
                    expires_at=invalid_created_at,
                    idle_expires_at=invalid_created_at,
                    security_version=user.security_version,
                    client_metadata={},
                    authentication_methods=["password"],
                )
            )
            postgresql_session.flush()

    assert postgresql_session.get(Session, auth_session.id) == auth_session


@pytest.mark.postgresql
def test_token_digests_are_unique_and_resolved_without_plaintext(
    postgresql_session: DatabaseSession,
) -> None:
    user = create_user(postgresql_session)
    auth_session = create_session(postgresql_session, user)
    digest = b"a" * 32
    token = AccessToken(
        session_id=auth_session.id,
        token_digest=digest,
        created_at=now(),
        expires_at=now() + timedelta(minutes=10),
    )
    postgresql_session.add(token)
    postgresql_session.flush()

    repository = AuthRepository(postgresql_session)
    assert repository.get_access_token_by_digest(digest) == token

    with pytest.raises(IntegrityError):
        with postgresql_session.begin_nested():
            postgresql_session.add(
                AccessToken(
                    session_id=auth_session.id,
                    token_digest=digest,
                    created_at=now(),
                    expires_at=now() + timedelta(minutes=10),
                )
            )
            postgresql_session.flush()

    assert repository.get_access_token_by_digest(digest) == token


@pytest.mark.postgresql
def test_refresh_family_generation_and_digest_lookup(postgresql_session: DatabaseSession) -> None:
    user = create_user(postgresql_session)
    auth_session = create_session(postgresql_session, user)
    family_id = uuid.uuid4()
    digest = b"b" * 32
    token = RefreshToken(
        session_id=auth_session.id,
        family_id=family_id,
        token_digest=digest,
        generation=1,
        created_at=now(),
        expires_at=now() + timedelta(days=30),
    )
    postgresql_session.add(token)
    postgresql_session.flush()

    assert AuthRepository(postgresql_session).get_refresh_token_by_digest(digest) == token

    with pytest.raises(IntegrityError):
        with postgresql_session.begin_nested():
            postgresql_session.add(
                RefreshToken(
                    session_id=auth_session.id,
                    family_id=family_id,
                    token_digest=b"c" * 32,
                    generation=0,
                    created_at=now(),
                    expires_at=now() + timedelta(days=30),
                )
            )
            postgresql_session.flush()

    assert AuthRepository(postgresql_session).get_refresh_token_by_digest(digest) == token


def test_sensitive_models_have_no_plaintext_credential_fields() -> None:
    prohibited_fields = {"plaintext_token", "raw_token", "secret"}
    for model in (User, UserEmail, PasswordCredential, Session, AccessToken, RefreshToken):
        assert not prohibited_fields.intersection(model.__table__.columns.keys())

    credential = PasswordCredential(
        user_id=uuid.uuid4(),
        password_hash="do-not-expose",
        password_hash_version="future-policy-v1",
    )
    token = AccessToken(
        session_id=uuid.uuid4(),
        token_digest=b"d" * 32,
        created_at=now(),
        expires_at=now() + timedelta(minutes=10),
    )

    assert "do-not-expose" not in repr(credential)
    assert "dddd" not in repr(token)
