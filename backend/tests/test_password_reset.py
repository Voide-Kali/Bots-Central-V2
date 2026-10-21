"""Password recovery by one-time e-mail code (ADR-014)."""

import base64
import uuid
from collections.abc import Generator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from test_device_telemetry import _active_device, _app, pg_cleanup  # noqa: F401
from test_telegram import _link

from app.audit import events as audit
from app.auth import authentication, password_reset
from app.auth.abuse_control import AbuseControlKey
from app.auth.passwords import PasswordPolicyError, hash_password
from app.auth.registration import PASSWORD_HASH_VERSION
from app.db.models import PasswordCredential, PasswordResetCode, UserEmail
from app.telegram import linking

KEY = AbuseControlKey(base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("="))
OLD = "old password that is long enough"
NEW = "brand new password that is long"


@pytest.mark.anyio
async def test_routes_reject_bad_bodies_without_touching_anything() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as client:
        bad_code = await client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"email": "a@example.com", "code": "123", "new_password": NEW},
        )
        assert bad_code.status_code == 422
        extra = await client.post(
            "/api/v1/auth/password-reset/request", json={"email": "a@example.com", "x": 1}
        )
        assert extra.status_code == 422
        # No abuse controller configured in this runtime: fail closed.
        closed = await client.post(
            "/api/v1/auth/password-reset/request", json={"email": "a@example.com"}
        )
        assert closed.status_code == 503


@pytest.fixture
def account(
    migrated_postgresql_engine: Engine, request: pytest.FixtureRequest
) -> Generator[tuple[sessionmaker[Session], uuid.UUID, str], None, None]:
    request.getfixturevalue("pg_cleanup")
    factory = sessionmaker(bind=migrated_postgresql_engine)
    user_id, _, _ = _active_device(factory)
    email = f"reset-{uuid.uuid4().hex[:10]}@example.com"
    with factory() as session, session.begin():
        session.add(
            UserEmail(
                user_id=user_id,
                email_canonical=email,
                email_display=email,
                is_primary=True,
                verified_at=session.scalar(text("SELECT clock_timestamp()")),
            )
        )
        session.add(
            PasswordCredential(
                user_id=user_id,
                password_hash=hash_password(OLD),
                password_hash_version=PASSWORD_HASH_VERSION,
            )
        )
    yield factory, user_id, email
    with factory() as session, session.begin():
        for table in ("access_tokens", "refresh_tokens"):
            session.execute(
                text(
                    f"DELETE FROM {table} WHERE session_id IN "
                    "(SELECT id FROM sessions WHERE user_id = :u)"
                ),
                {"u": user_id},
            )
        session.execute(delete(PasswordResetCode).where(PasswordResetCode.user_id == user_id))
        session.execute(delete(UserEmail).where(UserEmail.user_id == user_id))
        session.execute(delete(PasswordCredential).where(PasswordCredential.user_id == user_id))


@pytest.mark.postgresql
def test_unknown_unverified_or_invalid_email_gets_no_code(
    account: tuple[sessionmaker[Session], uuid.UUID, str],
) -> None:
    factory, user_id, email = account
    assert password_reset.request_reset(factory, KEY, email="nobody@example.com") is None
    assert password_reset.request_reset(factory, KEY, email="not-an-email") is None
    with factory() as session, session.begin():
        session.execute(
            update(UserEmail).where(UserEmail.user_id == user_id).values(verified_at=None)
        )
    assert password_reset.request_reset(factory, KEY, email=email) is None


@pytest.mark.postgresql
def test_successful_reset_replaces_password_and_kills_sessions(
    account: tuple[sessionmaker[Session], uuid.UUID, str],
) -> None:
    factory, user_id, email = account
    login = authentication.login(factory, email=email, password=OLD)
    _link(factory, user_id)  # an attacker-linked Telegram must not survive the reset
    assert linking.is_linked(factory, user_id=user_id)
    intent = password_reset.request_reset(factory, KEY, email=email.upper())
    assert intent is not None and intent.recipient == email
    code = intent.code.get_secret_value()
    with factory() as session:
        stored = session.query(PasswordResetCode).filter_by(user_id=user_id).one()
        assert code.encode() not in stored.code_mac and len(stored.code_mac) == 32
    assert password_reset.confirm_reset(factory, KEY, email=email, code=code, new_password=NEW)
    with pytest.raises(authentication.InvalidAccessToken):
        authentication.authenticate_access(factory, login.access_token.get_secret_value())
    with pytest.raises(authentication.InvalidCredentials):
        authentication.login(factory, email=email, password=OLD)
    authentication.login(factory, email=email, password=NEW)
    assert not linking.is_linked(factory, user_id=user_id)
    assert not password_reset.confirm_reset(
        factory, KEY, email=email, code=code, new_password=OLD + "x"
    )  # single use
    with factory() as session:
        actions = [e.action for e in audit.list_for_user(session, user_id=user_id)]
    assert "auth.password_reset_requested" in actions
    assert "auth.password_reset_completed" in actions


@pytest.mark.postgresql
def test_wrong_guesses_are_counted_and_lock_the_code(
    account: tuple[sessionmaker[Session], uuid.UUID, str],
) -> None:
    factory, _, email = account
    intent = password_reset.request_reset(factory, KEY, email=email)
    assert intent is not None
    code = intent.code.get_secret_value()
    wrong = f"{(int(code) + 1) % 10**8:08d}"
    for _ in range(password_reset.MAX_ATTEMPTS):
        assert not password_reset.confirm_reset(
            factory, KEY, email=email, code=wrong, new_password=NEW
        )
    assert not password_reset.confirm_reset(factory, KEY, email=email, code=code, new_password=NEW)
    authentication.login(factory, email=email, password=OLD)  # unchanged
    fresh = password_reset.request_reset(factory, KEY, email=email)
    assert fresh is not None
    assert password_reset.confirm_reset(
        factory, KEY, email=email, code=fresh.code.get_secret_value(), new_password=NEW
    )


@pytest.mark.postgresql
def test_weak_password_expired_code_and_superseded_code(
    account: tuple[sessionmaker[Session], uuid.UUID, str],
) -> None:
    factory, user_id, email = account
    first = password_reset.request_reset(factory, KEY, email=email)
    assert first is not None
    with pytest.raises(PasswordPolicyError):
        password_reset.confirm_reset(
            factory, KEY, email=email, code=first.code.get_secret_value(), new_password="short"
        )
    second = password_reset.request_reset(factory, KEY, email=email)
    assert second is not None
    assert not password_reset.confirm_reset(
        factory, KEY, email=email, code=first.code.get_secret_value(), new_password=NEW
    )
    with factory() as session, session.begin():
        session.execute(
            update(PasswordResetCode)
            .where(PasswordResetCode.user_id == user_id)
            .values(
                created_at=PasswordResetCode.created_at - password_reset.CODE_TTL * 2,
                expires_at=PasswordResetCode.created_at - password_reset.CODE_TTL,
            )
        )
    assert not password_reset.confirm_reset(
        factory, KEY, email=email, code=second.code.get_secret_value(), new_password=NEW
    )


class _Mailer:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def deliver(self, intent: object) -> None:  # verification adapter protocol
        raise AssertionError("not used here")

    def send_plain(self, *, recipient: str, subject: str, body: str) -> None:
        self.sent.append({"recipient": recipient, "subject": subject, "body": body})


@pytest.mark.postgresql
@pytest.mark.anyio
async def test_http_flow_is_generic_and_end_to_end(
    account: tuple[sessionmaker[Session], uuid.UUID, str],
    migrated_postgresql_engine: Engine,
) -> None:
    import anyio
    from pydantic import SecretStr

    from app.api.v1.routes import auth as auth_route
    from app.auth.abuse_control import AbuseController
    from app.core.config import Settings
    from app.main import create_app

    factory, _, email = account
    key_text = base64.urlsafe_b64encode(b"z" * 32).decode().rstrip("=")
    settings = Settings(
        public_origin="http://localhost:8000", abuse_control_hmac_key=SecretStr(key_text)
    )
    mailer = _Mailer()
    app = create_app()
    app.state.auth_runtime = auth_route.AuthHttpRuntime(
        session_factory=factory,
        abuse_controller=AbuseController(factory, AbuseControlKey.from_settings(settings)),
        keyring=None,
        delivery_adapter=mailer,
        settings=settings,
        password_limiter=anyio.CapacityLimiter(1),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        unknown = await client.post(
            "/api/v1/auth/password-reset/request", json={"email": "ghost@example.com"}
        )
        known = await client.post("/api/v1/auth/password-reset/request", json={"email": email})
        assert unknown.status_code == known.status_code == 202
        assert unknown.json() == known.json()
        assert len(mailer.sent) == 1 and mailer.sent[0]["recipient"] == email
        digits = "".join(
            ch for ch in mailer.sent[0]["body"].split("Código: ")[1][:9] if ch.isdigit()
        )
        wrong = await client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"email": email, "code": f"{(int(digits) + 7) % 10**8:08d}", "new_password": NEW},
        )
        assert wrong.status_code == 400
        weak = await client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"email": email, "code": digits, "new_password": "short"},
        )
        assert weak.status_code == 422
        done = await client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"email": email, "code": digits, "new_password": NEW},
        )
        assert done.status_code == 200
    authentication.login(factory, email=email, password=NEW)
    assert migrated_postgresql_engine is not None
