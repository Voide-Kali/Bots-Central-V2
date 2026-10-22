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
