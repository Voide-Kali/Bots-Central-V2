# ruff: noqa: F811
"""Panel action control (ADR-021): same PIN core as Telegram, result read back by the panel."""

from typing import Any

import pytest
from test_action_pin import KEY, PASSWORD, pinned  # noqa: F401
from test_device_commands import _result, _signed, setup  # noqa: F401
from test_device_telemetry import pg_cleanup  # noqa: F401

from app.auth import action_pin
from app.devices import commands


def _poll(factory: Any, private: Any, device_id: Any, seq: int) -> Any:
    return commands.next_command(
        factory, device_id=device_id, jws=_signed(private, device_id, seq, commands.POLL_AUDIENCE)
    )


@pytest.mark.postgresql
def test_web_lock_screen_runs_with_pin_and_reports_done(pinned: Any) -> None:
    factory, user_id, device_id, private = pinned
    action_pin.set_pin(factory, KEY, user_id=user_id, password=PASSWORD, pin="482913")
    command_id, check = commands.start_web_action(
        factory, KEY, user_id=user_id, device_id=device_id, kind="lock_screen", pin="482913"
    )
    assert check.ok and command_id is not None
    # The command carries no chat_id, so the Telegram delivery never touches it.
    assert commands.pending_deliveries(factory) == ([], [])
    command = _poll(factory, private, device_id, 101)
    assert command is not None and command["type"] == "lock_screen"
    _result(factory, private, device_id, command_id, 102, b"")
    status = commands.web_action_status(
        factory, user_id=user_id, device_id=device_id, command_id=command_id
    )
    assert status is not None and status.status == "completed"
    assert status.message == "Tela de telemetry-agent bloqueada."


@pytest.mark.postgresql
def test_web_wrong_pin_leaves_no_stale_request(pinned: Any) -> None:
    factory, user_id, device_id, private = pinned
    action_pin.set_pin(factory, KEY, user_id=user_id, password=PASSWORD, pin="482913")
    command_id, check = commands.start_web_action(
        factory, KEY, user_id=user_id, device_id=device_id, kind="lock_screen", pin="000000"
    )
    assert command_id is None and not check.ok
    # A wrong PIN must not leave an open command behind: the next correct request still works.
    ok_id, ok_check = commands.start_web_action(
        factory, KEY, user_id=user_id, device_id=device_id, kind="lock_screen", pin="482913"
    )
    assert ok_check.ok and ok_id is not None


@pytest.mark.postgresql
def test_web_network_scan_returns_text_once(pinned: Any) -> None:
    factory, user_id, device_id, private = pinned
    action_pin.set_pin(factory, KEY, user_id=user_id, password=PASSWORD, pin="482913")
    command_id, _ = commands.start_web_action(
        factory, KEY, user_id=user_id, device_id=device_id, kind="network_scan", pin="482913"
    )
    assert command_id is not None
    _poll(factory, private, device_id, 101)
    _result(factory, private, device_id, command_id, 102, b"2 aparelhos:\n192.168.1.1 - gw")
    first = commands.web_action_status(
        factory, user_id=user_id, device_id=device_id, command_id=command_id
    )
    assert first is not None and "192.168.1.1 - gw" in (first.text or "")
    # Delivered once: the scan text is dropped from the database.
    second = commands.web_action_status(
        factory, user_id=user_id, device_id=device_id, command_id=command_id
    )
    assert second is not None and second.status == "delivered" and second.text is None


@pytest.mark.postgresql
def test_web_webcam_photo_is_handed_over_once(pinned: Any) -> None:
    factory, user_id, device_id, private = pinned
    action_pin.set_pin(factory, KEY, user_id=user_id, password=PASSWORD, pin="482913")
    command_id, _ = commands.start_web_action(
        factory, KEY, user_id=user_id, device_id=device_id, kind="webcam_photo", pin="482913"
    )
    assert command_id is not None
    _poll(factory, private, device_id, 101)
    _result(factory, private, device_id, command_id, 102, b"\xff\xd8jpeg-bytes")
    status = commands.web_action_status(
        factory, user_id=user_id, device_id=device_id, command_id=command_id
    )
    assert status is not None and status.has_photo is True
    photo = commands.web_action_photo(
        factory, user_id=user_id, device_id=device_id, command_id=command_id
    )
    assert photo == b"\xff\xd8jpeg-bytes"
    # The photo leaves the database after one hand-over.
    assert commands.web_action_photo(
        factory, user_id=user_id, device_id=device_id, command_id=command_id
    ) is None


@pytest.mark.postgresql
def test_web_action_hidden_from_other_users(pinned: Any) -> None:
    factory, user_id, device_id, private = pinned
    action_pin.set_pin(factory, KEY, user_id=user_id, password=PASSWORD, pin="482913")
    command_id, _ = commands.start_web_action(
        factory, KEY, user_id=user_id, device_id=device_id, kind="lock_screen", pin="482913"
    )
    assert command_id is not None
    import uuid

    stranger = commands.web_action_status(
        factory, user_id=uuid.uuid4(), device_id=device_id, command_id=command_id
    )
    assert stranger is None  # never reveal another user's command
