"""ADR-017: admin role, hidden routes, activate account, no user content exposed."""

# ruff: noqa: F811
import uuid
from typing import Any

import anyio
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from test_device_telemetry import pg_cleanup  # noqa: F401
from test_password_reset import account  # noqa: F401

from app.admin import service
from app.api.v1.routes import auth as auth_route
from app.auth import authentication
from app.core.config import Settings
from app.db.enums import AccountStatus
from app.db.models import User, UserEmail
from app.main import create_app


def _client_app(factory: sessionmaker[Session]) -> Any:
    app = create_app()
    app.state.auth_runtime = auth_route.AuthHttpRuntime(
        session_factory=factory,
        abuse_controller=None,
        keyring=None,
        delivery_adapter=None,
        settings=Settings(public_origin="http://localhost:8000"),
        password_limiter=anyio.CapacityLimiter(1),
    )
    return app


@pytest.mark.anyio
async def test_admin_routes_look_missing_for_normal_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = authentication.AuthenticatedPrincipal(uuid.uuid4(), uuid.uuid4(), "a@b.c", "user")
    monkeypatch.setattr(authentication, "authenticate_access", lambda *_: principal)
    app = _client_app(lambda: (_ for _ in ()).throw(AssertionError("no db")))  # type: ignore[arg-type]
    bearer = {"Authorization": "Bearer " + "A" * 43}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        for path in ("/api/v1/admin/overview", "/api/v1/admin/users", "/api/v1/admin/audit"):
            hidden = await client.get(path, headers=bearer)
            missing = await client.get("/api/v1/admin/nao-existe", headers=bearer)
            assert hidden.status_code == missing.status_code == 404
            assert hidden.json() == missing.json()
        no_token = await client.get("/api/v1/admin/users")
        assert no_token.status_code == 404


@pytest.mark.postgresql
@pytest.mark.anyio
async def test_promote_by_command_then_admin_sees_and_repairs(
    account: tuple[sessionmaker[Session], uuid.UUID, str],
    migrated_postgresql_engine: Engine,
) -> None:
    from test_password_reset import OLD

    factory, user_id, email = account
    login = authentication.login(factory, email=email, password=OLD)
    token = {"Authorization": "Bearer " + login.access_token.get_secret_value()}
    app = _client_app(factory)
    pending_id = uuid.uuid4()
    with factory() as session, session.begin():
        session.add(User(id=pending_id, status=AccountStatus.PENDING_VERIFICATION))
        session.flush()
        session.add(
            UserEmail(
                user_id=pending_id,
                email_canonical=f"pend-{pending_id.hex[:8]}@example.com",
                email_display=f"pend-{pending_id.hex[:8]}@example.com",
                is_primary=True,
            )
        )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        assert (await client.get("/api/v1/admin/users", headers=token)).status_code == 404
        assert service.set_role(factory, email=email.upper(), role="admin")
        me = await client.get("/api/v1/auth/me", headers=token)
        assert me.json()["role"] == "admin"
        users = (await client.get("/api/v1/admin/users", headers=token)).json()["users"]
        mine = next(u for u in users if u["id"] == str(user_id))
        assert set(mine) == {
            "id",
            "email",
            "status",
            "role",
            "created_at",
            "devices",
            "telegram",
            "pin",
        }
        overview = (await client.get("/api/v1/admin/overview", headers=token)).json()["overview"]
        assert overview["users"]["pending_verification"] >= 1
        done = await client.post(f"/api/v1/admin/users/{pending_id}/activate", headers=token)
        assert done.status_code == 204
        events = (await client.get("/api/v1/admin/audit", headers=token)).json()["events"]
        assert any(e["action"] == "admin.user_activated" for e in events)
    with factory() as session:
        status = session.scalar(text("SELECT status FROM users WHERE id = :i"), {"i": pending_id})
        verified = session.scalar(
            text("SELECT verified_at FROM user_emails WHERE user_id = :i"), {"i": pending_id}
        )
    assert status == "active" and verified is not None
    with factory() as session, session.begin():
        session.execute(update(User).where(User.id == user_id).values(role="user"))
        session.execute(text("DELETE FROM user_emails WHERE user_id = :i"), {"i": pending_id})
        session.execute(text("DELETE FROM users WHERE id = :i"), {"i": pending_id})
    assert migrated_postgresql_engine is not None
