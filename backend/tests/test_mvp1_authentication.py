"""PostgreSQL integration coverage for the MVP-1 session foundation."""

import base64
import hashlib
import uuid
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Barrier

import anyio
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import delete, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1.routes import auth as auth_route
from app.auth import authentication, device_online
from app.auth.abuse_control import AbuseControlKey, AbuseController
from app.auth.passwords import hash_password
from app.core.config import Settings
from app.db.enums import AccountStatus, DeviceLifecycleStatus, SessionRevocationReason
from app.db.models import (
    AccessToken,
    Device,
    DevicePairingToken,
    PasswordCredential,
    RefreshToken,
    User,
    UserEmail,
)
from app.db.models import Session as DbSession
from app.main import create_app

pytestmark = pytest.mark.postgresql


@contextmanager
def active_user(
    engine: Engine, status: AccountStatus = AccountStatus.ACTIVE
) -> Generator[tuple[uuid.UUID, str, str], None, None]:
    user_id = uuid.uuid4()
    email = f"mvp1-{uuid.uuid4()}@example.com"
    password = "a sufficiently strong MVP1 password"
    try:
        with Session(engine) as session, session.begin():
            user = User(id=user_id, status=status, security_version=0)
            session.add(user)
            session.flush()
            session.add(
                UserEmail(
                    user_id=user_id,
                    email_canonical=email,
                    email_display=email,
                    is_primary=True,
                )
            )
            session.add(
                PasswordCredential(
                    user_id=user_id,
                    password_hash=hash_password(password),
                    password_hash_version="argon2id",
                    password_hash_metadata={},
                )
            )
        yield user_id, email, password
    finally:
        with Session(engine) as session, session.begin():
            ids = list(session.scalars(select(DbSession.id).where(DbSession.user_id == user_id)))
            if ids:
                session.execute(delete(AccessToken).where(AccessToken.session_id.in_(ids)))
                session.execute(delete(RefreshToken).where(RefreshToken.session_id.in_(ids)))
                session.execute(
                    delete(DevicePairingToken).where(
                        DevicePairingToken.initiating_session_id.in_(ids)
                    )
                )
                session.execute(delete(DbSession).where(DbSession.id.in_(ids)))
            session.execute(delete(Device).where(Device.user_id == user_id))
            session.execute(delete(PasswordCredential).where(PasswordCredential.user_id == user_id))
            session.execute(delete(UserEmail).where(UserEmail.user_id == user_id))
            session.execute(delete(User).where(User.id == user_id))


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine)


def http_app(engine: Engine) -> FastAPI:
    settings = Settings(
        public_origin="http://localhost:8000",
        abuse_control_hmac_key=SecretStr(
            base64.urlsafe_b64encode(b"m" * 32).decode("ascii").rstrip("=")
        ),
    )
    factory = session_factory(engine)
    app = create_app()
    app.state.auth_runtime = auth_route.AuthHttpRuntime(
        session_factory=factory,
        abuse_controller=AbuseController(factory, AbuseControlKey.from_settings(settings)),
        keyring=None,
        delivery_adapter=None,
        settings=settings,
        password_limiter=anyio.CapacityLimiter(1),
    )
    return app


def assert_user_has_no_session_or_tokens(engine: Engine, user_id: uuid.UUID) -> None:
    with Session(engine) as session:
        session_ids = list(
            session.scalars(select(DbSession.id).where(DbSession.user_id == user_id))
        )
        assert session_ids == []
        assert (
            session.scalar(
                select(text("count(*)"))
                .select_from(AccessToken)
                .where(AccessToken.session_id.in_(session_ids))
            )
            == 0
        )
        assert (
            session.scalar(
                select(text("count(*)"))
                .select_from(RefreshToken)
                .where(RefreshToken.session_id.in_(session_ids))
            )
            == 0
        )


def test_login_persists_digests_and_authenticates(migrated_postgresql_engine: Engine) -> None:
    with active_user(migrated_postgresql_engine) as (user_id, email, password):
        factory = session_factory(migrated_postgresql_engine)
        result = authentication.login(factory, email=email, password=password)
        assert result.user_id == user_id
        assert result.access_expires_in == 600
        assert (
            authentication.authenticate_access(
                factory, result.access_token.get_secret_value()
            ).user_id
            == user_id
        )
        with Session(migrated_postgresql_engine) as session:
            access = session.scalar(
                select(AccessToken).where(AccessToken.session_id == result.session_id)
            )
            refresh = session.scalar(
                select(RefreshToken).where(RefreshToken.session_id == result.session_id)
            )
            assert access is not None and refresh is not None
            assert access.token_digest == authentication._digest_token(
                result.access_token.get_secret_value()
            )
            assert refresh.token_digest == authentication._digest_token(
                result.refresh_token.get_secret_value()
            )


def test_unknown_and_wrong_password_are_generic(migrated_postgresql_engine: Engine) -> None:
    with active_user(migrated_postgresql_engine) as (user_id, email, password):
        factory = session_factory(migrated_postgresql_engine)
        for candidate_email, candidate_password in (
            ("unknown@example.com", password),
            (email, "wrong"),
        ):
            with pytest.raises(authentication.InvalidCredentials):
                authentication.login(factory, email=candidate_email, password=candidate_password)
        assert_user_has_no_session_or_tokens(migrated_postgresql_engine, user_id)


@pytest.mark.parametrize(
    "status",
    [
        AccountStatus.PENDING_VERIFICATION,
        AccountStatus.LOCKED,
        AccountStatus.DISABLED,
    ],
)
def test_non_active_login_creates_no_session_or_tokens(
    migrated_postgresql_engine: Engine, status: AccountStatus
) -> None:
    with active_user(migrated_postgresql_engine, status) as (user_id, email, password):
        with pytest.raises(authentication.InvalidCredentials):
            authentication.login(
                session_factory(migrated_postgresql_engine), email=email, password=password
            )
        assert_user_has_no_session_or_tokens(migrated_postgresql_engine, user_id)


def test_refresh_rotation_records_consumption_and_successor(
    migrated_postgresql_engine: Engine,
) -> None:
    with active_user(migrated_postgresql_engine) as (_, email, password):
        factory = session_factory(migrated_postgresql_engine)
        login = authentication.login(factory, email=email, password=password)
        rotated = authentication.refresh(factory, login.refresh_token.get_secret_value())
        assert rotated.success and rotated.refresh_token is not None
        with Session(migrated_postgresql_engine) as session:
            old = session.scalar(
                select(RefreshToken).where(
                    RefreshToken.token_digest
                    == authentication._digest_token(login.refresh_token.get_secret_value())
                )
            )
            assert old is not None and old.consumed_at is not None
            successor = session.get(RefreshToken, old.replaced_by_id)
            assert successor is not None
            assert successor.generation == old.generation + 1


def test_refresh_replay_revokes_family_and_session(migrated_postgresql_engine: Engine) -> None:
    with active_user(migrated_postgresql_engine) as (_, email, password):
        factory = session_factory(migrated_postgresql_engine)
        login = authentication.login(factory, email=email, password=password)
        assert authentication.refresh(factory, login.refresh_token.get_secret_value()).success
        replay = authentication.refresh(factory, login.refresh_token.get_secret_value())
        assert not replay.success and replay.reuse_detected
        with Session(migrated_postgresql_engine) as session:
            db_session = session.get(DbSession, login.session_id)
            assert db_session is not None
            assert db_session.revocation_reason is SessionRevocationReason.REFRESH_REUSE_DETECTED
        with pytest.raises(authentication.InvalidAccessToken):
            authentication.authenticate_access(factory, login.access_token.get_secret_value())


def test_unknown_refresh_is_not_rotated(migrated_postgresql_engine: Engine) -> None:
    with active_user(migrated_postgresql_engine) as (_, _, _):
        assert not authentication.refresh(
            session_factory(migrated_postgresql_engine), "A" * 43
        ).success


def test_expired_refresh_is_not_rotated(migrated_postgresql_engine: Engine) -> None:
    with active_user(migrated_postgresql_engine) as (_, email, password):
        factory = session_factory(migrated_postgresql_engine)
        login = authentication.login(factory, email=email, password=password)
        with Session(migrated_postgresql_engine) as session, session.begin():
            refresh = session.scalar(
                select(RefreshToken).where(RefreshToken.session_id == login.session_id)
            )
            now = session.scalar(text("SELECT clock_timestamp()"))
            assert refresh is not None and now is not None
            refresh.created_at = now - timedelta(minutes=10)
            refresh.expires_at = now - timedelta(minutes=1)
        before = Session(migrated_postgresql_engine)
        try:
            refresh_count = before.scalar(
                select(text("count(*)"))
                .select_from(RefreshToken)
                .where(RefreshToken.session_id == login.session_id)
            )
            access_count = before.scalar(
                select(text("count(*)"))
                .select_from(AccessToken)
                .where(AccessToken.session_id == login.session_id)
            )
        finally:
            before.close()
        assert not authentication.refresh(factory, login.refresh_token.get_secret_value()).success
        with Session(migrated_postgresql_engine) as session:
            assert (
                session.scalar(
                    select(text("count(*)"))
                    .select_from(RefreshToken)
                    .where(RefreshToken.session_id == login.session_id)
                )
                == refresh_count
            )
            assert (
                session.scalar(
                    select(text("count(*)"))
                    .select_from(AccessToken)
                    .where(AccessToken.session_id == login.session_id)
                )
                == access_count
            )


def test_revoked_refresh_is_not_rotated(migrated_postgresql_engine: Engine) -> None:
    with active_user(migrated_postgresql_engine) as (_, email, password):
        factory = session_factory(migrated_postgresql_engine)
        login = authentication.login(factory, email=email, password=password)
        with Session(migrated_postgresql_engine) as session, session.begin():
            refresh = session.scalar(
                select(RefreshToken).where(RefreshToken.session_id == login.session_id)
            )
            now = session.scalar(text("SELECT clock_timestamp()"))
            assert refresh is not None and now is not None
            refresh.revoked_at = now
        with Session(migrated_postgresql_engine) as session:
            refresh_count = session.scalar(
                select(text("count(*)"))
                .select_from(RefreshToken)
                .where(RefreshToken.session_id == login.session_id)
            )
            access_count = session.scalar(
                select(text("count(*)"))
                .select_from(AccessToken)
                .where(AccessToken.session_id == login.session_id)
            )
        result = authentication.refresh(factory, login.refresh_token.get_secret_value())
        assert not result.success
        with Session(migrated_postgresql_engine) as session:
            assert (
                session.scalar(
                    select(text("count(*)"))
                    .select_from(RefreshToken)
                    .where(RefreshToken.session_id == login.session_id)
                )
                == refresh_count
            )
            assert (
                session.scalar(
                    select(text("count(*)"))
                    .select_from(AccessToken)
                    .where(AccessToken.session_id == login.session_id)
                )
                == access_count
            )


def test_logout_is_idempotent_and_revokes_all_tokens(migrated_postgresql_engine: Engine) -> None:
    with active_user(migrated_postgresql_engine) as (_, email, password):
        factory = session_factory(migrated_postgresql_engine)
        login = authentication.login(factory, email=email, password=password)
        authentication.logout(factory, login.access_token.get_secret_value())
        authentication.logout(factory, login.access_token.get_secret_value())
        assert not authentication.refresh(factory, login.refresh_token.get_secret_value()).success
        with Session(migrated_postgresql_engine) as session:
            db_session = session.get(DbSession, login.session_id)
            accesses = session.scalars(
                select(AccessToken).where(AccessToken.session_id == login.session_id)
            ).all()
            refreshes = session.scalars(
                select(RefreshToken).where(RefreshToken.session_id == login.session_id)
            ).all()
            assert db_session is not None
            assert db_session.revocation_reason is SessionRevocationReason.LOGOUT
            assert all(item.revoked_at is not None for item in accesses)
            assert all(item.revoked_at is not None for item in refreshes)
        with pytest.raises(authentication.InvalidAccessToken):
            authentication.authenticate_access(factory, login.access_token.get_secret_value())


@pytest.mark.anyio
async def test_logout_refresh_authority_and_bearer_fallback(
    migrated_postgresql_engine: Engine,
) -> None:
    """A known refresh chooses its session; unknown cookie material may fall back to bearer."""
    headers = {"Origin": "http://localhost:8000", "Sec-Fetch-Site": "same-origin"}
    factory = session_factory(migrated_postgresql_engine)
    app = http_app(migrated_postgresql_engine)
    with active_user(migrated_postgresql_engine) as (_, email, password):
        known = authentication.login(factory, email=email, password=password)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            client.cookies.set(
                "refresh_token", known.refresh_token.get_secret_value(), path="/api/v1/auth"
            )
            response = await client.post(
                "/api/v1/auth/logout",
                headers={
                    **headers,
                    "Authorization": f"Bearer {known.access_token.get_secret_value()}",
                },
            )
            assert response.status_code == 204
            assert (
                await client.get(
                    "/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {known.access_token.get_secret_value()}"},
                )
            ).status_code == 401
            assert (await client.post("/api/v1/auth/refresh", headers=headers)).status_code == 401

        refresh_only = authentication.login(factory, email=email, password=password)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            client.cookies.set(
                "refresh_token", refresh_only.refresh_token.get_secret_value(), path="/api/v1/auth"
            )
            assert (await client.post("/api/v1/auth/logout", headers=headers)).status_code == 204
        with pytest.raises(authentication.InvalidAccessToken):
            authentication.authenticate_access(
                factory, refresh_only.access_token.get_secret_value()
            )

        expired = authentication.login(factory, email=email, password=password)
        with Session(migrated_postgresql_engine) as session, session.begin():
            access = session.scalar(
                select(AccessToken).where(AccessToken.session_id == expired.session_id)
            )
            now = session.scalar(text("SELECT clock_timestamp()"))
            assert access is not None and now is not None
            access.created_at = now - timedelta(minutes=10)
            access.expires_at = now - timedelta(minutes=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            client.cookies.set(
                "refresh_token", expired.refresh_token.get_secret_value(), path="/api/v1/auth"
            )
            assert (
                await client.post(
                    "/api/v1/auth/logout",
                    headers={
                        **headers,
                        "Authorization": f"Bearer {expired.access_token.get_secret_value()}",
                    },
                )
            ).status_code == 204
        assert not authentication.refresh(factory, expired.refresh_token.get_secret_value()).success

        fallback = authentication.login(factory, email=email, password=password)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            client.cookies.set("refresh_token", "Z" * 43, path="/api/v1/auth")
            assert (
                await client.post(
                    "/api/v1/auth/logout",
                    headers={
                        **headers,
                        "Authorization": f"Bearer {fallback.access_token.get_secret_value()}",
                    },
                )
            ).status_code == 204
        with pytest.raises(authentication.InvalidAccessToken):
            authentication.authenticate_access(factory, fallback.access_token.get_secret_value())

        untouched = authentication.login(factory, email=email, password=password)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            client.cookies.set("refresh_token", "Y" * 43, path="/api/v1/auth")
            assert (await client.post("/api/v1/auth/logout", headers=headers)).status_code == 204
            assert (await client.post("/api/v1/auth/logout", headers=headers)).status_code == 204
        assert (
            authentication.authenticate_access(
                factory, untouched.access_token.get_secret_value()
            ).session_id
            == untouched.session_id
        )


@pytest.mark.anyio
async def test_pairing_revoke_http_is_owner_and_initiating_session_scoped(
    migrated_postgresql_engine: Engine,
) -> None:
    factory = session_factory(migrated_postgresql_engine)
    with active_user(migrated_postgresql_engine) as (_, email, password):
        with active_user(migrated_postgresql_engine) as (_, other_email, other_password):
            initiating = authentication.login(factory, email=email, password=password)
            same_owner_other_session = authentication.login(factory, email=email, password=password)
            other_owner = authentication.login(factory, email=other_email, password=other_password)
            pairing = device_online.create_pairing(
                factory, user_id=initiating.user_id, session_id=initiating.session_id
            )
            app = http_app(migrated_postgresql_engine)
            same_owner_headers = {
                "Authorization": (
                    f"Bearer {same_owner_other_session.access_token.get_secret_value()}"
                )
            }
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                route = f"/api/v1/devices/pairings/{pairing.id}"
                other = await client.delete(
                    route,
                    headers={
                        "Authorization": f"Bearer {other_owner.access_token.get_secret_value()}"
                    },
                )
                second = await client.delete(
                    route,
                    headers=same_owner_headers,
                )
                owner = await client.delete(
                    route,
                    headers={
                        "Authorization": f"Bearer {initiating.access_token.get_secret_value()}"
                    },
                )
                repeated = await client.delete(
                    route,
                    headers={
                        "Authorization": f"Bearer {initiating.access_token.get_secret_value()}"
                    },
                )
            assert other.status_code == second.status_code == 404
            assert owner.status_code == repeated.status_code == 204
            with Session(migrated_postgresql_engine) as session:
                assert session.get(DevicePairingToken, pairing.id).revoked_at is not None  # type: ignore[union-attr]


@pytest.mark.anyio
async def test_cross_user_approve_and_reject_do_not_mutate_pending_device(
    migrated_postgresql_engine: Engine,
) -> None:
    factory = session_factory(migrated_postgresql_engine)
    with active_user(migrated_postgresql_engine) as (owner_id, _, _):
        with active_user(migrated_postgresql_engine) as (_, other_email, other_password):
            fingerprint = "SHA256:" + "x" * 43
            device_id = uuid.uuid4()
            with Session(migrated_postgresql_engine) as session, session.begin():
                session.add(
                    Device(
                        id=device_id,
                        user_id=owner_id,
                        name="pending",
                        platform="linux",
                        lifecycle_status=DeviceLifecycleStatus.PENDING,
                        public_key=b"x" * 32,
                        public_key_fingerprint=fingerprint,
                    )
                )
            other = authentication.login(factory, email=other_email, password=other_password)
            app = http_app(migrated_postgresql_engine)
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                headers = {"Authorization": f"Bearer {other.access_token.get_secret_value()}"}
                approve = await client.post(
                    f"/api/v1/devices/{device_id}/approve",
                    json={"fingerprint": fingerprint},
                    headers=headers,
                )
                reject = await client.post(
                    f"/api/v1/devices/{device_id}/reject",
                    json={"fingerprint": fingerprint},
                    headers=headers,
                )
            assert approve.status_code == reject.status_code == 404
            with Session(migrated_postgresql_engine) as session:
                device = session.get(Device, device_id)
                assert device is not None
                assert device.lifecycle_status is DeviceLifecycleStatus.PENDING


@pytest.mark.anyio
async def test_invalid_token_responses_do_not_echo_or_log_persisted_token_material(
    migrated_postgresql_engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    with active_user(migrated_postgresql_engine) as (_, email, password):
        factory = session_factory(migrated_postgresql_engine)
        login = authentication.login(factory, email=email, password=password)
        access_token = login.access_token.get_secret_value()
        refresh_token = login.refresh_token.get_secret_value()
        with Session(migrated_postgresql_engine) as session:
            access = session.scalar(
                select(AccessToken).where(AccessToken.session_id == login.session_id)
            )
            refresh = session.scalar(
                select(RefreshToken).where(RefreshToken.session_id == login.session_id)
            )
            assert access is not None and refresh is not None
            access_digest = access.token_digest.hex()
            refresh_digest = refresh.token_digest.hex()
        assert access_digest == authentication._digest_token(access_token).hex()
        assert refresh_digest == authentication._digest_token(refresh_token).hex()

        authentication.logout(factory, access_token)
        caplog.clear()
        headers = {"Origin": "http://localhost:8000", "Sec-Fetch-Site": "same-origin"}
        async with AsyncClient(
            transport=ASGITransport(app=http_app(migrated_postgresql_engine)),
            base_url="http://test",
        ) as client:
            me = await client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
            )
            client.cookies.set("refresh_token", refresh_token, path="/api/v1/auth")
            refresh_response = await client.post("/api/v1/auth/refresh", headers=headers)

        assert me.status_code == refresh_response.status_code == 401
        for secret in (access_token, refresh_token, access_digest, refresh_digest):
            assert secret not in me.text
            assert secret not in refresh_response.text
            assert secret not in str(me.headers)
            assert secret not in str(refresh_response.headers)
            assert secret not in caplog.text


def _make_historically_expired_session(engine: Engine, session_id: uuid.UUID) -> None:
    with Session(engine) as session, session.begin():
        db_session = session.get(DbSession, session_id)
        now = session.scalar(text("SELECT clock_timestamp()"))
        assert db_session is not None and now is not None
        db_session.created_at = now - timedelta(days=3)
        db_session.last_seen_at = now - timedelta(days=2)
        db_session.idle_expires_at = now - timedelta(days=2)
        db_session.expires_at = now - timedelta(days=1)


def test_access_rejects_historically_expired_session(migrated_postgresql_engine: Engine) -> None:
    with active_user(migrated_postgresql_engine) as (_, email, password):
        factory = session_factory(migrated_postgresql_engine)
        login = authentication.login(factory, email=email, password=password)
        _make_historically_expired_session(migrated_postgresql_engine, login.session_id)
        with pytest.raises(authentication.InvalidAccessToken):
            authentication.authenticate_access(factory, login.access_token.get_secret_value())


def test_access_rejects_own_expiry_while_session_remains_valid(
    migrated_postgresql_engine: Engine,
) -> None:
    with active_user(migrated_postgresql_engine) as (_, email, password):
        factory = session_factory(migrated_postgresql_engine)
        login = authentication.login(factory, email=email, password=password)
        with Session(migrated_postgresql_engine) as session, session.begin():
            access = session.scalar(
                select(AccessToken).where(AccessToken.session_id == login.session_id)
            )
            now = session.scalar(text("SELECT clock_timestamp()"))
            assert access is not None and now is not None
            access.created_at = now - timedelta(minutes=10)
            access.expires_at = now - timedelta(minutes=1)
        with pytest.raises(authentication.InvalidAccessToken):
            authentication.authenticate_access(factory, login.access_token.get_secret_value())


def test_unknown_access_token_is_rejected(migrated_postgresql_engine: Engine) -> None:
    with active_user(migrated_postgresql_engine) as (_, _, _):
        with pytest.raises(authentication.InvalidAccessToken):
            authentication.authenticate_access(
                session_factory(migrated_postgresql_engine), "A" * 43
            )


def test_refresh_renews_idle_window_and_issues_access_ttl(
    migrated_postgresql_engine: Engine,
) -> None:
    with active_user(migrated_postgresql_engine) as (_, email, password):
        factory = session_factory(migrated_postgresql_engine)
        login = authentication.login(factory, email=email, password=password)
        with Session(migrated_postgresql_engine) as session, session.begin():
            db_session = session.get(DbSession, login.session_id)
            now = session.scalar(text("SELECT clock_timestamp()"))
            assert db_session is not None and now is not None
            prior_idle_expiry = now + timedelta(seconds=5)
            db_session.idle_expires_at = prior_idle_expiry
        result = authentication.refresh(factory, login.refresh_token.get_secret_value())
        assert result.success and result.access_expires_in is not None
        assert result.access_expires_in == int(authentication.ACCESS_TTL.total_seconds())

        with Session(migrated_postgresql_engine) as session:
            db_session = session.get(DbSession, login.session_id)
            access = session.scalar(
                select(AccessToken)
                .where(AccessToken.session_id == login.session_id)
                .order_by(AccessToken.created_at.desc(), AccessToken.id.desc())
            )
            assert db_session is not None and access is not None
            assert db_session.idle_expires_at > prior_idle_expiry
            assert db_session.idle_expires_at == db_session.last_seen_at + authentication.IDLE_TTL
            assert access.expires_at == db_session.last_seen_at + authentication.ACCESS_TTL
            assert access.expires_at <= db_session.idle_expires_at
            assert access.expires_at <= db_session.expires_at


def test_refresh_expires_in_respects_absolute_session_boundary(
    migrated_postgresql_engine: Engine,
) -> None:
    with active_user(migrated_postgresql_engine) as (_, email, password):
        factory = session_factory(migrated_postgresql_engine)
        login = authentication.login(factory, email=email, password=password)
        with Session(migrated_postgresql_engine) as session, session.begin():
            db_session = session.get(DbSession, login.session_id)
            now = session.scalar(text("SELECT clock_timestamp()"))
            assert db_session is not None and now is not None
            absolute_expiry = now + timedelta(seconds=5)
            db_session.expires_at = absolute_expiry
            db_session.idle_expires_at = absolute_expiry
        result = authentication.refresh(factory, login.refresh_token.get_secret_value())
        assert result.success and result.access_expires_in is not None
        assert 0 < result.access_expires_in <= 5
        with Session(migrated_postgresql_engine) as session:
            db_session = session.get(DbSession, login.session_id)
            assert db_session is not None
            assert db_session.expires_at == absolute_expiry
            assert db_session.idle_expires_at == absolute_expiry


def test_access_rejects_idle_session_expiry(migrated_postgresql_engine: Engine) -> None:
    with active_user(migrated_postgresql_engine) as (_, email, password):
        factory = session_factory(migrated_postgresql_engine)
        login = authentication.login(factory, email=email, password=password)
        with Session(migrated_postgresql_engine) as session, session.begin():
            db_session = session.get(DbSession, login.session_id)
            now = session.scalar(text("SELECT clock_timestamp()"))
            assert db_session is not None and now is not None
            db_session.created_at = now - timedelta(days=3)
            db_session.last_seen_at = now - timedelta(days=2)
            db_session.idle_expires_at = now - timedelta(days=1)
            db_session.expires_at = now + timedelta(days=1)
        with pytest.raises(authentication.InvalidAccessToken):
            authentication.authenticate_access(factory, login.access_token.get_secret_value())


def test_session_usable_rejects_absolute_expiry_before_idle_expiry() -> None:
    """A DB-persisted absolute-only state is impossible: idle <= absolute."""
    now = datetime(2030, 1, 1, tzinfo=UTC)
    user_id = uuid.uuid4()
    user = User(id=user_id, status=AccountStatus.ACTIVE, security_version=0)
    db_session = DbSession(
        id=uuid.uuid4(),
        user_id=user_id,
        created_at=now - timedelta(days=1),
        last_seen_at=now - timedelta(hours=1),
        expires_at=now - timedelta(seconds=1),
        idle_expires_at=now + timedelta(seconds=1),
        security_version=0,
        authentication_methods=["password"],
    )
    assert not authentication._session_usable(user, db_session, now)


def test_idle_timeout_is_one_hour_and_logs_out_after_inactivity() -> None:
    """ADR-025: one hour of inactivity ends the session; an active window stays valid."""
    assert authentication.IDLE_TTL == timedelta(hours=1)
    assert authentication.IDLE_TTL <= authentication.SESSION_TTL
    now = datetime(2030, 1, 1, tzinfo=UTC)
    user_id = uuid.uuid4()
    user = User(id=user_id, status=AccountStatus.ACTIVE, security_version=0)

    def built(idle_expires_at: datetime) -> DbSession:
        return DbSession(
            id=uuid.uuid4(),
            user_id=user_id,
            created_at=now - timedelta(days=1),
            last_seen_at=now - timedelta(minutes=5),
            expires_at=now + timedelta(days=10),
            idle_expires_at=idle_expires_at,
            security_version=0,
            authentication_methods=["password"],
        )

    # Still inside the hour: usable. Past the idle window by a second: logged out.
    assert authentication._session_usable(user, built(now + timedelta(minutes=30)), now)
    assert not authentication._session_usable(user, built(now - timedelta(seconds=1)), now)


def test_access_rejects_security_version_and_account_state(
    migrated_postgresql_engine: Engine,
) -> None:
    with active_user(migrated_postgresql_engine) as (user_id, email, password):
        factory = session_factory(migrated_postgresql_engine)
        login = authentication.login(factory, email=email, password=password)
        with Session(migrated_postgresql_engine) as session, session.begin():
            user = session.get(User, user_id)
            assert user is not None
            user.security_version += 1
        with pytest.raises(authentication.InvalidAccessToken):
            authentication.authenticate_access(factory, login.access_token.get_secret_value())
        replacement = authentication.login(factory, email=email, password=password)
        with Session(migrated_postgresql_engine) as session, session.begin():
            user = session.get(User, user_id)
            assert user is not None
            user.status = AccountStatus.LOCKED
        with pytest.raises(authentication.InvalidAccessToken):
            authentication.authenticate_access(factory, replacement.access_token.get_secret_value())


def test_refresh_concurrency_is_serialized_and_replay_revokes_family(
    migrated_postgresql_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    with active_user(migrated_postgresql_engine) as (_, email, password):
        factory = session_factory(migrated_postgresql_engine)
        login = authentication.login(factory, email=email, password=password)
        token = login.refresh_token.get_secret_value()
        original_lock_context = authentication._load_locked_session_context
        before_authoritative_locks = Barrier(2, timeout=10)

        def gated_lock_context(*args: object, **kwargs: object) -> object:
            before_authoritative_locks.wait()
            return original_lock_context(*args, **kwargs)  # type: ignore[arg-type]

        with monkeypatch.context() as concurrent_refresh_patch:
            concurrent_refresh_patch.setattr(
                authentication, "_load_locked_session_context", gated_lock_context
            )
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(authentication.refresh, factory, token) for _ in range(2)
                ]
                results = [future.result(timeout=15) for future in futures]
        assert sum(result.success for result in results) == 1
        assert sum(result.reuse_detected for result in results) == 1
        successor = next(result for result in results if result.success)
        assert successor.refresh_token is not None
        assert not authentication.refresh(
            factory, successor.refresh_token.get_secret_value()
        ).success
        with Session(migrated_postgresql_engine) as session:
            db_session = session.get(DbSession, login.session_id)
            refreshes = session.scalars(
                select(RefreshToken).where(RefreshToken.session_id == login.session_id)
            ).all()
            accesses = session.scalars(
                select(AccessToken).where(AccessToken.session_id == login.session_id)
            ).all()
            assert db_session is not None
            assert db_session.revocation_reason is SessionRevocationReason.REFRESH_REUSE_DETECTED
            assert len(refreshes) == 2
            assert len(accesses) == 2
            assert all(item.revoked_at is not None for item in refreshes)
            assert all(item.revoked_at is not None for item in accesses)


def test_device_lifecycle_is_separate_from_presence(migrated_postgresql_engine: Engine) -> None:
    with active_user(migrated_postgresql_engine) as (user_id, _, _):
        with Session(migrated_postgresql_engine) as session, session.begin():
            session.add(
                Device(
                    user_id=user_id,
                    name="test device",
                    platform="linux",
                    lifecycle_status=DeviceLifecycleStatus.ACTIVE,
                )
            )
        with Session(migrated_postgresql_engine) as session:
            device = session.scalar(select(Device).where(Device.user_id == user_id))
            assert device is not None
            assert device.lifecycle_status is DeviceLifecycleStatus.ACTIVE


@pytest.mark.anyio
async def test_me_accepts_only_current_valid_access(migrated_postgresql_engine: Engine) -> None:
    with active_user(migrated_postgresql_engine) as (user_id, email, password):
        factory = session_factory(migrated_postgresql_engine)
        login = authentication.login(factory, email=email, password=password)
        app = http_app(migrated_postgresql_engine)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            valid = await client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {login.access_token.get_secret_value()}"},
            )
            invalid = await client.get(
                "/api/v1/auth/me", headers={"Authorization": "Bearer " + "A" * 43}
            )
        assert valid.status_code == 200
        assert valid.json() == {"id": str(user_id), "email": email, "role": "user"}
        assert invalid.status_code == 401
        assert "security_version" not in valid.text
        assert "digest" not in valid.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    "state", ["expired_access", "revoked_session", "security_version", "locked"]
)
async def test_me_rejects_invalid_authority_state(
    migrated_postgresql_engine: Engine, state: str
) -> None:
    with active_user(migrated_postgresql_engine) as (user_id, email, password):
        factory = session_factory(migrated_postgresql_engine)
        login = authentication.login(factory, email=email, password=password)
        with Session(migrated_postgresql_engine) as session, session.begin():
            now = session.scalar(text("SELECT clock_timestamp()"))
            assert now is not None
            if state == "expired_access":
                access = session.scalar(
                    select(AccessToken).where(AccessToken.session_id == login.session_id)
                )
                assert access is not None
                access.created_at = now - timedelta(minutes=10)
                access.expires_at = now - timedelta(minutes=1)
            elif state == "revoked_session":
                db_session = session.get(DbSession, login.session_id)
                assert db_session is not None
                db_session.revoked_at = now
                db_session.revocation_reason = SessionRevocationReason.LOGOUT
            else:
                user = session.get(User, user_id)
                assert user is not None
                if state == "security_version":
                    user.security_version += 1
                else:
                    user.status = AccountStatus.LOCKED
        async with AsyncClient(
            transport=ASGITransport(app=http_app(migrated_postgresql_engine)),
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {login.access_token.get_secret_value()}"},
            )
        assert response.status_code == 401


@pytest.mark.anyio
async def test_devices_are_scoped_to_authenticated_user(migrated_postgresql_engine: Engine) -> None:
    with active_user(migrated_postgresql_engine) as (user_a, email_a, password_a):
        with active_user(migrated_postgresql_engine) as (user_b, _, _):
            public_key = b"a" * 32
            fingerprint = "SHA256:" + base64.urlsafe_b64encode(
                hashlib.sha256(public_key).digest()
            ).decode("ascii").rstrip("=")
            revoked_fingerprint = "SHA256:" + base64.urlsafe_b64encode(
                hashlib.sha256(b"b" * 32).digest()
            ).decode("ascii").rstrip("=")
            with Session(migrated_postgresql_engine) as session, session.begin():
                session.add_all(
                    [
                        Device(
                            user_id=user_a,
                            name="A1",
                            platform="linux",
                            lifecycle_status=DeviceLifecycleStatus.PENDING,
                            public_key=public_key,
                            public_key_fingerprint=fingerprint,
                        ),
                        Device(
                            user_id=user_a,
                            name="A2",
                            platform="windows",
                            lifecycle_status=DeviceLifecycleStatus.ACTIVE,
                        ),
                        Device(
                            user_id=user_a,
                            name="A3",
                            platform="linux",
                            lifecycle_status=DeviceLifecycleStatus.REVOKED,
                            public_key=b"b" * 32,
                            public_key_fingerprint=revoked_fingerprint,
                        ),
                        Device(
                            user_id=user_b,
                            name="B1",
                            platform="macos",
                            lifecycle_status=DeviceLifecycleStatus.ACTIVE,
                        ),
                    ]
                )
            login = authentication.login(
                session_factory(migrated_postgresql_engine), email=email_a, password=password_a
            )
            app = http_app(migrated_postgresql_engine)
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    "/api/v1/devices",
                    headers={"Authorization": f"Bearer {login.access_token.get_secret_value()}"},
                )
            assert response.status_code == 200
            devices = response.json()["devices"]
            assert {device["name"] for device in devices} == {"A1", "A2", "A3"}
            assert all(device["status"] == "offline" for device in devices)
            assert {device["lifecycle_status"] for device in devices} == {
                "active",
                "pending",
                "revoked",
            }
            assert all(device["last_seen_at"] is None for device in devices)
            assert all("user_id" not in device for device in devices)
            by_name = {device["name"]: device for device in devices}
            assert by_name["A1"]["fingerprint"] == fingerprint
            assert by_name["A2"]["fingerprint"] is None
            assert by_name["A3"]["fingerprint"] == revoked_fingerprint
            for device in devices:
                assert not {"public_key", "private_key", "pairing", "proof", "jws"} & set(device)


@pytest.mark.anyio
async def test_devices_empty_list(migrated_postgresql_engine: Engine) -> None:
    with active_user(migrated_postgresql_engine) as (_, email, password):
        login = authentication.login(
            session_factory(migrated_postgresql_engine), email=email, password=password
        )
        async with AsyncClient(
            transport=ASGITransport(app=http_app(migrated_postgresql_engine)),
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/api/v1/devices",
                headers={"Authorization": f"Bearer {login.access_token.get_secret_value()}"},
            )
        assert response.status_code == 200
        assert response.json() == {"devices": []}
