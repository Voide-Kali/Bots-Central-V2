import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DatabaseSession

from app.auth.repository import AuthRepository
from app.db.enums import (
    AccountStatus,
    AuthenticationLevel,
    EmailVerificationInvalidationReason,
    EmailVerificationMaterialType,
    SessionRevocationReason,
)
from app.db.models import (
    AccessToken,
    EmailVerificationChallenge,
    PasswordCredential,
    RefreshToken,
    Session,
    User,
    UserEmail,
)


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


def create_user_email(session: DatabaseSession, user: User, suffix: str) -> UserEmail:
    email = UserEmail(
        user_id=user.id,
        email_canonical=f"user-{suffix}@example.com",
        email_display=f"user-{suffix}@example.com",
    )
    session.add(email)
    session.flush()
    return email


def valid_link_challenge(user_email_id: uuid.UUID) -> EmailVerificationChallenge:
    created_at = now()
    return EmailVerificationChallenge(
        user_email_id=user_email_id,
        material_type=EmailVerificationMaterialType.LINK,
        link_token_digest=b"l" * 32,
        created_at=created_at,
        expires_at=created_at + timedelta(minutes=15),
    )


def valid_code_challenge(user_email_id: uuid.UUID) -> EmailVerificationChallenge:
    created_at = now()
    return EmailVerificationChallenge(
        user_email_id=user_email_id,
        material_type=EmailVerificationMaterialType.CODE,
        code_digest=b"c" * 32,
        hmac_key_version="test-v1",
        attempt_count=0,
        max_attempts=5,
        created_at=created_at,
        expires_at=created_at + timedelta(minutes=10),
    )


def insert_email_verification_challenge(
    session: DatabaseSession, values: dict[str, object]
) -> None:
    session.execute(
        text(
            "INSERT INTO email_verification_challenges ("
            "id, user_email_id, material_type, link_token_digest, code_digest, "
            "hmac_key_version, attempt_count, max_attempts, created_at, expires_at, "
            "consumed_at, invalidated_at, invalidation_reason) "
            "VALUES (:id, :user_email_id, "
            "CAST(:material_type AS email_verification_material_type), "
            ":link_token_digest, :code_digest, :hmac_key_version, :attempt_count, "
            ":max_attempts, :created_at, :expires_at, :consumed_at, :invalidated_at, "
            "CAST(:invalidation_reason AS email_verification_invalidation_reason))"
        ),
        values,
    )


def challenge_values(user_email_id: uuid.UUID, material_type: str) -> dict[str, object]:
    created_at = now()
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "user_email_id": user_email_id,
        "material_type": material_type,
        "link_token_digest": None,
        "code_digest": None,
        "hmac_key_version": None,
        "attempt_count": None,
        "max_attempts": None,
        "created_at": created_at,
        "expires_at": created_at + timedelta(minutes=15),
        "consumed_at": None,
        "invalidated_at": None,
        "invalidation_reason": None,
    }
    if material_type == "link":
        values["link_token_digest"] = b"l" * 32
    else:
        values.update(
            code_digest=b"c" * 32,
            hmac_key_version="test-v1",
            attempt_count=0,
            max_attempts=5,
        )
    return values


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


@pytest.mark.postgresql
def test_email_verification_challenge_roundtrip_and_constraints(
    postgresql_session: DatabaseSession,
) -> None:
    user = create_user(postgresql_session)
    user_email = create_user_email(postgresql_session, user, "challenge")
    link = valid_link_challenge(user_email.id)
    code = valid_code_challenge(user_email.id)
    postgresql_session.add_all((link, code))
    postgresql_session.flush()

    assert link.user_email_id == user_email.id
    assert code.max_attempts == 5
    assert "user_id" not in EmailVerificationChallenge.__table__.columns
    assert "llll" not in repr(link)
    assert "cccc" not in repr(code)

    invalid_cases = (
        valid_link_challenge(uuid.uuid4()),
        EmailVerificationChallenge(
            user_email_id=user_email.id,
            material_type=EmailVerificationMaterialType.LINK,
            created_at=now(),
            expires_at=now(),
        ),
        EmailVerificationChallenge(
            user_email_id=user_email.id,
            material_type=EmailVerificationMaterialType.LINK,
            link_token_digest=b"x" * 31,
            created_at=now(),
            expires_at=now() + timedelta(minutes=15),
        ),
        EmailVerificationChallenge(
            user_email_id=user_email.id,
            material_type=EmailVerificationMaterialType.LINK,
            link_token_digest=b"x" * 32,
            code_digest=b"c" * 32,
            created_at=now(),
            expires_at=now() + timedelta(minutes=15),
        ),
        EmailVerificationChallenge(
            user_email_id=user_email.id,
            material_type=EmailVerificationMaterialType.CODE,
            created_at=now(),
            expires_at=now() + timedelta(minutes=10),
        ),
        EmailVerificationChallenge(
            user_email_id=user_email.id,
            material_type=EmailVerificationMaterialType.CODE,
            code_digest=b"c" * 32,
            hmac_key_version="test-v1",
            max_attempts=5,
            created_at=now(),
            expires_at=now() + timedelta(minutes=10),
        ),
        EmailVerificationChallenge(
            user_email_id=user_email.id,
            material_type=EmailVerificationMaterialType.CODE,
            code_digest=b"c" * 31,
            hmac_key_version="test-v1",
            attempt_count=0,
            max_attempts=5,
            created_at=now(),
            expires_at=now() + timedelta(minutes=10),
        ),
        EmailVerificationChallenge(
            user_email_id=user_email.id,
            material_type=EmailVerificationMaterialType.CODE,
            code_digest=b"c" * 32,
            hmac_key_version="",
            attempt_count=0,
            max_attempts=5,
            created_at=now(),
            expires_at=now() + timedelta(minutes=10),
        ),
        EmailVerificationChallenge(
            user_email_id=user_email.id,
            material_type=EmailVerificationMaterialType.CODE,
            link_token_digest=b"l" * 32,
            code_digest=b"c" * 32,
            hmac_key_version="test-v1",
            attempt_count=0,
            max_attempts=5,
            created_at=now(),
            expires_at=now() + timedelta(minutes=10),
        ),
        EmailVerificationChallenge(
            user_email_id=user_email.id,
            material_type=EmailVerificationMaterialType.CODE,
            code_digest=b"c" * 32,
            hmac_key_version="test-v1",
            attempt_count=-1,
            max_attempts=5,
            created_at=now(),
            expires_at=now() + timedelta(minutes=10),
        ),
        EmailVerificationChallenge(
            user_email_id=user_email.id,
            material_type=EmailVerificationMaterialType.CODE,
            code_digest=b"c" * 32,
            hmac_key_version="test-v1",
            attempt_count=6,
            max_attempts=5,
            created_at=now(),
            expires_at=now() + timedelta(minutes=10),
        ),
        EmailVerificationChallenge(
            user_email_id=user_email.id,
            material_type=EmailVerificationMaterialType.CODE,
            code_digest=b"c" * 32,
            hmac_key_version="test-v1",
            attempt_count=0,
            max_attempts=4,
            created_at=now(),
            expires_at=now() + timedelta(minutes=10),
        ),
    )
    for invalid in invalid_cases:
        with pytest.raises(IntegrityError):
            with postgresql_session.begin_nested():
                postgresql_session.add(invalid)
                postgresql_session.flush()


@pytest.mark.postgresql
def test_email_verification_terminal_state_and_digest_indexes(
    postgresql_session: DatabaseSession,
) -> None:
    user = create_user(postgresql_session)
    first_email = create_user_email(postgresql_session, user, "first")
    second_email = create_user_email(postgresql_session, user, "second")
    first_link = valid_link_challenge(first_email.id)
    first_code = valid_code_challenge(first_email.id)
    second_code = valid_code_challenge(second_email.id)
    postgresql_session.add_all((first_link, first_code, second_code))
    postgresql_session.flush()

    with pytest.raises(IntegrityError):
        with postgresql_session.begin_nested():
            postgresql_session.add(valid_link_challenge(second_email.id))
            postgresql_session.flush()

    assert first_code.code_digest == second_code.code_digest
    invalidated_at = now()
    terminal_conflict = valid_link_challenge(first_email.id)
    terminal_conflict.link_token_digest = b"t" * 32
    terminal_conflict.consumed_at = invalidated_at
    terminal_conflict.invalidated_at = invalidated_at
    terminal_conflict.invalidation_reason = EmailVerificationInvalidationReason.SUPERSEDED
    with pytest.raises(IntegrityError):
        with postgresql_session.begin_nested():
            postgresql_session.add(terminal_conflict)
            postgresql_session.flush()

    invalidation_without_reason = valid_code_challenge(second_email.id)
    invalidation_without_reason.code_digest = b"z" * 32
    invalidation_without_reason.invalidated_at = invalidated_at
    with pytest.raises(IntegrityError):
        with postgresql_session.begin_nested():
            postgresql_session.add(invalidation_without_reason)
            postgresql_session.flush()


@pytest.mark.postgresql
@pytest.mark.parametrize(
    ("material_type", "overrides"),
    [
        ("link", {"link_token_digest": None}),
        ("link", {"code_digest": b"c" * 32}),
        ("link", {"hmac_key_version": "test-v1"}),
        ("link", {"attempt_count": 0}),
        ("link", {"max_attempts": 5}),
        ("link", {"link_token_digest": b"l" * 31}),
        ("link", {"link_token_digest": b"l" * 33}),
        ("code", {"code_digest": None}),
        ("code", {"link_token_digest": b"l" * 32}),
        ("code", {"hmac_key_version": None}),
        ("code", {"hmac_key_version": ""}),
        ("code", {"attempt_count": None}),
        ("code", {"max_attempts": None}),
        ("code", {"max_attempts": 4}),
        ("code", {"attempt_count": -1}),
        ("code", {"attempt_count": 6}),
        ("code", {"code_digest": b"c" * 31}),
        ("code", {"code_digest": b"c" * 33}),
    ],
)
def test_email_verification_null_and_three_valued_logic_rejected_by_postgresql(
    postgresql_session: DatabaseSession, material_type: str, overrides: dict[str, object]
) -> None:
    user = create_user(postgresql_session)
    user_email = create_user_email(postgresql_session, user, uuid.uuid4().hex)
    values = challenge_values(user_email.id, material_type)
    values.update(overrides)

    with pytest.raises(IntegrityError):
        with postgresql_session.begin_nested():
            insert_email_verification_challenge(postgresql_session, values)


@pytest.mark.postgresql
@pytest.mark.parametrize(
    "overrides",
    [
        {"consumed_at": now(), "invalidated_at": now(), "invalidation_reason": "superseded"},
        {"invalidated_at": now()},
        {"invalidation_reason": "superseded"},
    ],
)
def test_email_verification_terminal_null_states_rejected_by_postgresql(
    postgresql_session: DatabaseSession, overrides: dict[str, object]
) -> None:
    user = create_user(postgresql_session)
    user_email = create_user_email(postgresql_session, user, uuid.uuid4().hex)
    values = challenge_values(user_email.id, "code")
    values.update(overrides)

    with pytest.raises(IntegrityError):
        with postgresql_session.begin_nested():
            insert_email_verification_challenge(postgresql_session, values)

def test_sensitive_models_have_no_plaintext_credential_fields() -> None:
    prohibited_fields = {"plaintext_token", "raw_token", "secret"}
    for model in (
        User,
        UserEmail,
        PasswordCredential,
        EmailVerificationChallenge,
        Session,
        AccessToken,
        RefreshToken,
    ):
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
