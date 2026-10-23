# ruff: noqa: F811
"""ADR-016 catalogue actions: lock_screen and webcam_photo."""

import hashlib
import uuid
from typing import Any

import pytest
from test_device_commands import KEY, _result, _signed, setup  # noqa: F401, F811
from test_device_telemetry import pg_cleanup  # noqa: F401
from test_telegram import CHAT

from app.auth import device_online
from app.devices import commands


def test_digest_vector_matches_the_agent() -> None:
    device = uuid.UUID("11111111-1111-4111-8111-111111111111")
    expected = hashlib.sha256(f"aval-action-v1\nlock_screen\n{device}\n".encode()).hexdigest()
    assert commands.action_digest("lock_screen", device, "") == expected


@pytest.mark.postgresql
def test_unknown_action_and_parameters_are_refused(setup: Any) -> None:
    factory, user_id, device_id, _ = setup
    for kind, argument in (("run_shell", ""), ("lock_screen", "x"), ("webcam_photo", "a.jpg")):
        with pytest.raises(commands.UnknownAction):
            commands.request_action(
                factory,
                KEY,
                user_id=user_id,
                chat_id=CHAT,
                kind=kind,
                device_id=device_id,
                argument=argument,
            )
    with pytest.raises(commands.DeviceNotFoundForUser):
        commands.request_action(
            factory,
            KEY,
            user_id=user_id,
            chat_id=CHAT,
            kind="lock_screen",
            device_id=uuid.uuid4(),
        )


def _approve_and_poll(setup: Any, kind: str) -> tuple[uuid.UUID, dict[str, str]]:
    factory, user_id, device_id, private = setup
    intent = commands.request_action(
        factory, KEY, user_id=user_id, chat_id=CHAT, kind=kind, device_id=device_id
    )
    subject, body = commands.approval_email(intent)
    assert intent.device_name in subject and commands.ACTIONS[kind].risk in body
    commands.approve(factory, KEY, user_id=user_id, code=intent.code.get_secret_value())
    command = commands.next_command(
        factory,
        device_id=device_id,
        jws=_signed(private, device_id, 101, commands.POLL_AUDIENCE),
    )
    assert command is not None
    assert command["digest"] == commands.action_digest(kind, device_id, "")
    return intent.command_id, command


@pytest.mark.postgresql
def test_lock_screen_completes_without_bytes_and_notifies_once(setup: Any) -> None:
    factory, _, device_id, private = setup
    command_id, command = _approve_and_poll(setup, "lock_screen")
    assert command["type"] == "lock_screen" and command["file_name"] == ""
    with pytest.raises(device_online.InvalidProof):  # a status-only action carries no bytes
        _result(factory, private, device_id, command_id, 102, b"x")
    _result(factory, private, device_id, command_id, 103, b"")
    deliveries, notices = commands.pending_deliveries(factory)
    assert [d for d in deliveries if d.chat_id == CHAT] == []
    assert [n.text for n in notices if n.chat_id == CHAT] == ["Tela de telemetry-agent bloqueada."]
    assert [n for n in commands.pending_deliveries(factory)[1] if n.chat_id == CHAT] == []


@pytest.mark.postgresql
def test_webcam_photo_is_delivered_as_a_jpg(setup: Any) -> None:
    factory, _, device_id, private = setup
    command_id, _ = _approve_and_poll(setup, "webcam_photo")
    _result(factory, private, device_id, command_id, 102, b"\xff\xd8jpeg-bytes")
    deliveries, _ = commands.pending_deliveries(factory)
    mine = [d for d in deliveries if d.chat_id == CHAT]
    assert len(mine) == 1 and mine[0].content == b"\xff\xd8jpeg-bytes"
    assert mine[0].file_name.startswith("foto-") and mine[0].file_name.endswith(".jpg")


@pytest.mark.postgresql
def test_agent_errors_become_friendly_notices(setup: Any) -> None:
    factory, _, device_id, private = setup
    command_id, _ = _approve_and_poll(setup, "lock_screen")
    commands.submit_result(
        factory,
        device_id=device_id,
        command_id=command_id,
        jws=_signed(
            private,
            device_id,
            102,
            commands.RESULT_AUDIENCE,
            cid=str(command_id),
            status="error",
            error="unsupported",
        ),
        content_b64=None,
    )
    texts = [n.text for n in commands.pending_deliveries(factory)[1] if n.chat_id == CHAT]
    assert texts == [
        "Não foi possível bloquear a tela: falta o programa ou o aparelho no computador."
    ]
