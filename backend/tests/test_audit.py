"""Append-only audit trail: recording, isolation, immutability and read endpoints."""

import uuid
from collections.abc import Generator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker
from test_device_telemetry import _active_device, _app, pg_cleanup  # noqa: F401
from test_telegram import CHAT, _Admission, _link, _msg

from app.audit import events as audit
from app.auth import authentication
from app.auth.passwords import hash_password
from app.auth.registration import PASSWORD_HASH_VERSION
from app.db.models import AuditEvent, PasswordCredential, TelegramLink, User, UserEmail
from app.telegram import commands


def test_record_refuses_secret_looking_details() -> None:
    class _NoSession:
        def scalar(self, *_: object) -> None:
            raise AssertionError("must fail before touching the database")

    for key in ("pairing_token", "code", "new_password", "private_key"):
        with pytest.raises(ValueError):
            audit.record(
                _NoSession(),  # type: ignore[arg-type]
                user_id=None,
                action="x",
                actor="system",
                details={key: "v"},
            )


@pytest.mark.anyio
async def test_audit_route_requires_auth_and_bounds_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = authentication.AuthenticatedPrincipal(uuid.uuid4(), uuid.uuid4(), "a@example.com")
    monkeypatch.setattr(authentication, "authenticate_access", lambda *_: principal)
    bearer = {"Authorization": "Bearer " + "A" * 43}
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as client:
        assert (await client.get("/api/v1/audit")).status_code == 401
        for bad in ("0", "101", "-1", "x"):
            response = await client.get("/api/v1/audit", params={"limit": bad}, headers=bearer)
            assert response.status_code == 400, bad


@pytest.fixture
def factory(
    migrated_postgresql_engine: Engine, request: pytest.FixtureRequest
) -> Generator[sessionmaker[Session], None, None]:
    request.getfixturevalue("pg_cleanup")
    made = sessionmaker(bind=migrated_postgresql_engine)
    yield made
    with made() as session, session.begin():
        session.execute(delete(TelegramLink).where(TelegramLink.chat_id == CHAT))


def _actions(factory: sessionmaker[Session], user_id: uuid.UUID) -> list[str]:
    with factory() as session:
        return [e.action for e in reversed(audit.list_for_user(session, user_id=user_id))]


@pytest.mark.postgresql
def test_device_and_telegram_actions_are_audited_in_order(
    factory: sessionmaker[Session],
) -> None:
    user_id, device_id, _ = _active_device(factory)
    _link(factory, user_id)
    commands.handle_update(_msg("/desvincular"), session_factory=factory, admission=_Admission())
    assert _actions(factory, user_id) == [
        "device.pairing_created",
        "device.enrolled",
        "device.approved",
        "telegram.linked",
        "telegram.unlinked",
    ]
    with factory() as session:
        approved = [
            e
            for e in audit.list_for_user(session, user_id=user_id)
            if e.action == "device.approved"
        ][0]
        assert approved.target_id == str(device_id)
        assert approved.details == {"name": "telemetry-agent"}
        other_user = uuid.uuid4()
        assert audit.list_for_user(session, user_id=other_user) == []


@pytest.mark.postgresql
def test_rejected_device_and_historico_command(factory: sessionmaker[Session]) -> None:
    user_id, _device, _ = _active_device(factory)
    second_user, _, _ = _active_device(factory)
    _link(factory, user_id)
    reply = commands.handle_update(
        _msg("/historico"), session_factory=factory, admission=_Admission()
    )
    assert reply is not None and reply.text.startswith("Últimas ações:")
    assert "Dispositivo aprovado (telemetry-agent)" in reply.text
    assert "Telegram vinculado" in reply.text
    assert second_user != user_id


@pytest.mark.postgresql
def test_successful_login_is_audited(factory: sessionmaker[Session]) -> None:
    user_id, _, _ = _active_device(factory)
    email = f"audit-{uuid.uuid4().hex[:10]}@example.com"
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
                password_hash=hash_password("correct horse battery staple"),
                password_hash_version=PASSWORD_HASH_VERSION,
            )
        )
    result = authentication.login(factory, email=email, password="correct horse battery staple")
    with pytest.raises(authentication.InvalidCredentials):
        authentication.login(factory, email=email, password="wrong password 12345")
    actions = _actions(factory, user_id)
    assert actions.count("auth.login") == 1
    with factory() as session:
        login_event = audit.list_for_user(session, user_id=user_id, limit=1)[0]
        assert login_event.target_id == str(result.session_id)
    with factory() as session, session.begin():
        for table in ("access_tokens", "refresh_tokens"):
            session.execute(
                text(
                    f"DELETE FROM {table} WHERE session_id IN "
                    "(SELECT id FROM sessions WHERE user_id = :u)"
                ),
                {"u": user_id},
            )
        session.execute(delete(UserEmail).where(UserEmail.user_id == user_id))
        session.execute(delete(PasswordCredential).where(PasswordCredential.user_id == user_id))


@pytest.mark.postgresql
def test_audit_rows_cannot_be_rewritten_or_deleted(factory: sessionmaker[Session]) -> None:
    user_id, _, _ = _active_device(factory)
    with pytest.raises(DBAPIError):
        with factory() as session, session.begin():
            session.execute(
                text("UPDATE audit_events SET action = 'forged' WHERE user_id = :u"),
                {"u": user_id},
            )
    with pytest.raises(DBAPIError):
        with factory() as session, session.begin():
            session.execute(text("DELETE FROM audit_events WHERE user_id = :u"), {"u": user_id})
    assert "device.approved" in _actions(factory, user_id)
    # The pg_cleanup fixture then deletes the user: events must survive anonymized
    # (ON DELETE SET NULL is the only permitted update).


@pytest.mark.postgresql
def test_deleting_a_user_keeps_anonymized_events(
    factory: sessionmaker[Session], migrated_postgresql_engine: Engine
) -> None:
    user_id, _, _ = _active_device(factory)
    with factory() as session:
        ids = [e.id for e in audit.list_for_user(session, user_id=user_id)]
    assert ids
    with factory() as session, session.begin():
        session.execute(
            text("DELETE FROM device_pairing_tokens WHERE user_id = :u"), {"u": user_id}
        )
        session.execute(text("DELETE FROM devices WHERE user_id = :u"), {"u": user_id})
        session.execute(text("DELETE FROM sessions WHERE user_id = :u"), {"u": user_id})
        session.execute(delete(User).where(User.id == user_id))
    with factory() as session:
        rows = session.query(AuditEvent).filter(AuditEvent.id.in_(ids)).all()
        assert len(rows) == len(ids) and all(row.user_id is None for row in rows)
