"""Action PIN (ADR-016 addendum): set with password, approve, lockout."""

# ruff: noqa: F811
import base64
from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy import delete, text
from test_device_commands import _signed, setup  # noqa: F401
from test_device_telemetry import pg_cleanup  # noqa: F401
from test_telegram import CHAT

from app.auth import action_pin
from app.auth.abuse_control import AbuseControlKey
from app.auth.passwords import hash_password
from app.auth.registration import PASSWORD_HASH_VERSION
from app.db.models import ActionPin, PasswordCredential
from app.devices import commands

KEY = AbuseControlKey(base64.urlsafe_b64encode(b"p" * 32).decode().rstrip("="))
PASSWORD = "senha muito longa para teste"


@pytest.mark.parametrize("pin", ["", "12345", "1234567", "abcdef", "000000", "123456", "999999"])
def test_weak_or_malformed_pins_are_refused(pin: str) -> None:
    with pytest.raises(action_pin.PinPolicyError):
        action_pin.validate_pin(pin)


@pytest.fixture
def pinned(setup: Any) -> Generator[Any, None, None]:
    """``setup`` plus a password; cleans the credential before ``setup`` tears down."""
    factory, user_id, _, _ = setup
    with factory() as session, session.begin():
        session.add(
            PasswordCredential(
                user_id=user_id,
                password_hash=hash_password(PASSWORD),
                password_hash_version=PASSWORD_HASH_VERSION,
            )
        )
    yield setup
    with factory() as session, session.begin():
        session.execute(delete(PasswordCredential).where(PasswordCredential.user_id == user_id))


@pytest.mark.postgresql
def test_pin_needs_password_and_approves_only_the_latest_request(pinned: Any) -> None:
    factory, user_id, device_id, private = pinned
    with pytest.raises(action_pin.WrongPassword):
        action_pin.set_pin(factory, KEY, user_id=user_id, password="errada", pin="482913")
    action_pin.set_pin(factory, KEY, user_id=user_id, password=PASSWORD, pin="482913")
    with factory() as session:
        row = session.get(ActionPin, user_id)
        assert row is not None and b"482913" not in row.pin_mac

    first = commands.request_action(
        factory,
        KEY,
        user_id=user_id,
        chat_id=CHAT,
        kind="lock_screen",
        device_id=device_id,
        by_pin=True,
    )
    second = commands.request_action(
        factory,
        KEY,
        user_id=user_id,
        chat_id=CHAT,
        kind="webcam_photo",
        device_id=device_id,
        by_pin=True,
    )
    approved, check = commands.approve_with_pin(factory, KEY, user_id=user_id, pin="482913")
    assert check.ok and approved is not None and approved.id == second.command_id
    with factory() as session:
        status = session.scalar(
            text("SELECT status FROM device_commands WHERE id = :i"), {"i": first.command_id}
        )
    assert status == "expired"  # the older request can no longer be approved
    command = commands.next_command(
        factory, device_id=device_id, jws=_signed(private, device_id, 201, commands.POLL_AUDIENCE)
    )
    assert command is not None and command["type"] == "webcam_photo"


@pytest.mark.postgresql
def test_five_wrong_pins_lock_for_fifteen_minutes(pinned: Any) -> None:
    factory, user_id, device_id, _ = pinned
    action_pin.set_pin(factory, KEY, user_id=user_id, password=PASSWORD, pin="482913")
    commands.request_action(
        factory,
        KEY,
        user_id=user_id,
        chat_id=CHAT,
        kind="lock_screen",
        device_id=device_id,
        by_pin=True,
    )
    for left in (4, 3, 2, 1):
        approved, check = commands.approve_with_pin(factory, KEY, user_id=user_id, pin="111222")
        assert approved is None and not check.ok and check.remaining == left
    approved, check = commands.approve_with_pin(factory, KEY, user_id=user_id, pin="111222")
    assert approved is None and check.locked_until is not None
    approved, check = commands.approve_with_pin(factory, KEY, user_id=user_id, pin="482913")
    assert approved is None and check.locked_until is not None  # right PIN, still locked
    with factory() as session:
        configured, locked = action_pin.status(session, user_id)
    assert configured and locked is not None


@pytest.mark.postgresql
def test_pin_without_open_request_does_nothing(pinned: Any) -> None:
    factory, user_id, _, _ = pinned
    action_pin.set_pin(factory, KEY, user_id=user_id, password=PASSWORD, pin="482913")
    approved, check = commands.approve_with_pin(factory, KEY, user_id=user_id, pin="482913")
    assert approved is None and not check.ok


def _say(factory: Any, text_: str, mailer: Any, message_id: int = 77) -> Any:
    from test_telegram import _Admission, _msg

    from app.telegram.commands import ActionDeps, handle_update

    update = _msg(text_)
    update["message"]["message_id"] = message_id
    reply = handle_update(
        update,
        session_factory=factory,
        admission=_Admission(),
        actions=ActionDeps(key=KEY, mailer=mailer),
    )
    assert reply is not None
    return reply


@pytest.mark.postgresql
def test_plain_portuguese_request_and_pin_in_telegram(pinned: Any) -> None:
    from test_device_commands import _Mailer

    factory, user_id, _, _ = pinned
    mailer = _Mailer()
    # Without a PIN the code goes by e-mail and the owner is told to create one.
    no_pin = _say(factory, "bloqueia o telemetry-agent", mailer)
    assert "/aprovar" in no_pin.text and "crie um PIN" in no_pin.text and len(mailer.sent) == 1

    action_pin.set_pin(factory, KEY, user_id=user_id, password=PASSWORD, pin="482913")
    asked = _say(factory, "tira uma foto do telemetry-agent", mailer)
    assert "digite seu PIN" in asked.text and len(mailer.sent) == 1  # no new e-mail
    wrong = _say(factory, "111222", mailer, message_id=90)
    assert "Restam 4" in wrong.text and wrong.delete_message_id == 90
    done = _say(factory, "482913", mailer, message_id=91)
    assert done.text.startswith("Aprovado: tirar uma foto") and done.delete_message_id == 91
    again = _say(factory, "482913", mailer, message_id=92)
    assert again.text == "Nenhum pedido esperando PIN agora."
    question = _say(factory, "qual computador está mais quente?", mailer)
    assert "IA" in question.text  # questions still go to the assistant (disabled here)


@pytest.mark.postgresql
def test_several_actions_in_a_row_are_not_rate_limited_like_linking(pinned: Any) -> None:
    """Regression (E2E 22/10): actions shared the 5-per-10-min linking budget."""
    from test_device_commands import _Mailer
    from test_telegram import _msg

    from app.auth.abuse_control import AbuseController
    from app.db.models import AuthAbuseBucket
    from app.telegram.commands import ActionDeps, handle_update

    factory, user_id, _, _ = pinned
    action_pin.set_pin(factory, KEY, user_id=user_id, password=PASSWORD, pin="482913")
    admission = AbuseController(factory, KEY)
    try:
        for index in range(8):
            update = _msg("bloqueia o telemetry-agent")
            update["message"]["message_id"] = 200 + index
            reply = handle_update(
                update,
                session_factory=factory,
                admission=admission,
                actions=ActionDeps(key=KEY, mailer=_Mailer()),
            )
            assert reply is not None and "digite seu PIN" in reply.text, reply
    finally:
        with factory() as session, session.begin():
            session.execute(delete(AuthAbuseBucket))


@pytest.mark.anyio
async def test_reading_the_pin_status_is_not_blocked_by_the_body_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression (E2E 22/10): GET /me/action-pin got 415 from the JSON body middleware,
    so the panel could never show 'Criar PIN'."""
    import uuid

    from httpx import ASGITransport, AsyncClient
    from test_admin import _client_app

    from app.auth import authentication

    principal = authentication.AuthenticatedPrincipal(uuid.uuid4(), uuid.uuid4(), "a@b.c", "user")
    monkeypatch.setattr(authentication, "authenticate_access", lambda *_: principal)
    monkeypatch.setattr(action_pin, "status", lambda *_: (False, None))

    class _Session:
        def __enter__(self) -> "_Session":
            return self

        def __exit__(self, *_: object) -> None:
            return None

    app = _client_app(lambda: _Session())  # type: ignore[arg-type]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.get(
            "/api/v1/me/action-pin", headers={"Authorization": "Bearer " + "A" * 43}
        )
    assert response.status_code == 200, response.text
    assert response.json()["configured"] is False
