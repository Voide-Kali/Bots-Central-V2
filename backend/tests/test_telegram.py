"""Telegram bot (ADR-011): parsing, linking, commands, alerts, client hygiene."""

import urllib.error
import uuid
from collections.abc import Generator
from datetime import timedelta
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from test_device_telemetry import VALID, _active_device, _beat, pg_cleanup  # noqa: F401

from app.auth import device_online
from app.auth.abuse_control import AbuseControlUnavailable
from app.db.models import Device, TelegramLink, TelegramLinkCode
from app.telegram import client as telegram_client
from app.telegram import commands, linking
from app.telegram.alerts import collect_presence_alerts

CHAT = 424242


def _msg(
    text: str, *, chat: int = CHAT, sender: int | None = None, kind: str = "private"
) -> dict[str, Any]:
    return {
        "update_id": 1,
        "message": {
            "chat": {"id": chat, "type": kind},
            "from": {"id": chat if sender is None else sender, "is_bot": False},
            "text": text,
        },
    }


class _Admission:
    def __init__(self, result: bool | None = True) -> None:
        self.result = result
        self.calls = 0

    def admit_telegram_link(self, *, chat_id: int) -> bool:
        self.calls += 1
        if self.result is None:
            raise AbuseControlUnavailable("down")
        return self.result

    def admit_assistant(self, *, chat_id: int) -> bool:
        return self.admit_telegram_link(chat_id=chat_id)


# --- pure ------------------------------------------------------------------------------


def test_code_normalization() -> None:
    assert linking.normalize_code("abcd-efgh 23") == "ABCDEFGH23"
    assert linking.normalize_code("ABCDEFGH2") is None
    assert linking.normalize_code("ABCDEFGH20") is None  # 0 is not in the alphabet
    assert linking.normalize_code("ÁBCDEFGH23") is None


@pytest.mark.parametrize(
    "update",
    [
        {},
        {"message": "x"},
        _msg("/status", kind="group"),
        _msg("/status", sender=CHAT + 1),
        {
            "message": {
                "chat": {"id": CHAT, "type": "private"},
                "from": {"id": CHAT, "is_bot": True},
                "text": "/status",
            }
        },
        {"message": {"chat": {"id": CHAT, "type": "private"}, "from": {"id": CHAT}, "photo": []}},
    ],
)
def test_ignored_updates_produce_no_reply_and_no_database_access(update: dict[str, Any]) -> None:
    def no_db() -> Session:
        raise AssertionError("database must not be reached")

    assert commands.handle_update(update, session_factory=no_db, admission=_Admission()) is None


def test_link_attempt_is_rate_limited_before_database() -> None:
    def no_db() -> Session:
        raise AssertionError("database must not be reached")

    denied = commands.handle_update(
        _msg("/vincular ABCDEFGH23"), session_factory=no_db, admission=_Admission(False)
    )
    assert denied is not None and "Muitas tentativas" in denied.text
    down = commands.handle_update(
        _msg("/vincular ABCDEFGH23"), session_factory=no_db, admission=_Admission(None)
    )
    assert down is not None and "indisponível" in down.text


def test_client_rejects_bad_tokens_and_never_leaks_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    for bad in ("", "a b", "x/y"):
        with pytest.raises(ValueError):
            telegram_client.TelegramClient(SecretStr(bad))
    secret = "123456:SECRET-token"
    client = telegram_client.TelegramClient(SecretStr(secret))

    def boom(*_args: object, **_kwargs: object) -> None:
        raise urllib.error.URLError(f"https://api.telegram.org/bot{secret}/getUpdates failed")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(telegram_client.TelegramUnavailable) as caught:
        client.get_updates(offset=None)
    assert secret not in repr(caught.value) and caught.value.__cause__ is None
    assert caught.value.__suppress_context__


# --- PostgreSQL ------------------------------------------------------------------------


@pytest.fixture
def factory(
    migrated_postgresql_engine: Engine, request: pytest.FixtureRequest
) -> Generator[sessionmaker[Session], None, None]:
    request.getfixturevalue("pg_cleanup")
    made = sessionmaker(bind=migrated_postgresql_engine)
    yield made
    with made() as session, session.begin():
        session.execute(delete(TelegramLink).where(TelegramLink.chat_id.in_([CHAT, CHAT + 7])))


def _link(factory: sessionmaker[Session], user_id: uuid.UUID, chat: int = CHAT) -> None:
    code = linking.create_link_code(factory, user_id=user_id)
    reply = commands.handle_update(
        _msg(f"/vincular {code.code}", chat=chat), session_factory=factory, admission=_Admission()
    )
    assert reply is not None and "vinculado" in reply.text


@pytest.mark.postgresql
def test_link_status_and_unlink_flow(factory: sessionmaker[Session]) -> None:
    user_id, device_id, private = _active_device(factory)
    device_online.heartbeat(factory, device_id=device_id, jws=_beat(private, device_id, 1, VALID))

    before = commands.handle_update(
        _msg("/status"), session_factory=factory, admission=_Admission()
    )
    assert before is not None and before.text == commands.NOT_LINKED

    code = linking.create_link_code(factory, user_id=user_id)
    linked = commands.handle_update(
        _msg(f"/vincular {code.code.lower()}"), session_factory=factory, admission=_Admission()
    )
    assert linked is not None and "vinculado" in linked.text

    reused = commands.handle_update(
        _msg(f"/vincular {code.code}", chat=CHAT + 7),
        session_factory=factory,
        admission=_Admission(),
    )
    assert reused is not None and "inválido" in reused.text

    status = commands.handle_update(
        _msg("/status"), session_factory=factory, admission=_Admission()
    )
    assert status is not None
    assert "telemetry-agent — online" in status.text
    assert "CPU 12%" in status.text and "RAM 6,0/16,0 GB" in status.text and "48 °C" in status.text

    with factory() as session, session.begin():
        session.execute(
            update(TelegramLink).where(TelegramLink.chat_id == CHAT).values(telegram_user_id=1)
        )
    spoofed = commands.handle_update(
        _msg("/status"), session_factory=factory, admission=_Admission()
    )
    assert spoofed is not None and spoofed.text == commands.NOT_LINKED
    with factory() as session, session.begin():
        session.execute(
            update(TelegramLink).where(TelegramLink.chat_id == CHAT).values(telegram_user_id=CHAT)
        )

    bye = commands.handle_update(
        _msg("/desvincular"), session_factory=factory, admission=_Admission()
    )
    assert bye is not None and "desvinculado" in bye.text
    after = commands.handle_update(_msg("/status"), session_factory=factory, admission=_Admission())
    assert after is not None and after.text == commands.NOT_LINKED


@pytest.mark.postgresql
def test_expired_and_superseded_codes_fail(factory: sessionmaker[Session]) -> None:
    user_id, _, _ = _active_device(factory)
    first = linking.create_link_code(factory, user_id=user_id)
    second = linking.create_link_code(factory, user_id=user_id)
    with pytest.raises(linking.InvalidLinkCode):
        linking.consume_link_code(factory, raw_code=first.code, chat_id=CHAT, telegram_user_id=CHAT)
    with factory() as session, session.begin():
        session.execute(
            update(TelegramLinkCode)
            .where(TelegramLinkCode.user_id == user_id)
            .values(
                created_at=TelegramLinkCode.created_at - timedelta(hours=1),
                expires_at=TelegramLinkCode.created_at - timedelta(minutes=50),
            )
        )
    with pytest.raises(linking.InvalidLinkCode):
        linking.consume_link_code(
            factory, raw_code=second.code, chat_id=CHAT, telegram_user_id=CHAT
        )


@pytest.mark.postgresql
def test_chat_linked_to_another_user_cannot_be_stolen(factory: sessionmaker[Session]) -> None:
    first_user, _, _ = _active_device(factory)
    second_user, _, _ = _active_device(factory)
    _link(factory, first_user)
    code = linking.create_link_code(factory, user_id=second_user)
    with pytest.raises(linking.AlreadyLinked):
        linking.consume_link_code(factory, raw_code=code.code, chat_id=CHAT, telegram_user_id=CHAT)
    assert linking.is_linked(factory, user_id=first_user)
    assert not linking.is_linked(factory, user_id=second_user)


@pytest.mark.postgresql
def test_presence_alerts_fire_once_per_transition(factory: sessionmaker[Session]) -> None:
    user_id, device_id, private = _active_device(factory)
    device_online.heartbeat(factory, device_id=device_id, jws=_beat(private, device_id, 1))
    assert [r for r in collect_presence_alerts(factory) if r.chat_id == CHAT] == []
    _link(factory, user_id)
    assert [r for r in collect_presence_alerts(factory) if r.chat_id == CHAT] == []  # first sight
    with factory() as session, session.begin():
        session.execute(
            update(Device)
            .where(Device.id == device_id)
            .values(last_seen_at=Device.last_seen_at - timedelta(minutes=10))
        )
    offline = [r for r in collect_presence_alerts(factory) if r.chat_id == CHAT]
    assert [r.text for r in offline] == ["🔴 telemetry-agent ficou offline."]
    assert [r for r in collect_presence_alerts(factory) if r.chat_id == CHAT] == []
    device_online.heartbeat(factory, device_id=device_id, jws=_beat(private, device_id, 2))
    online = [r for r in collect_presence_alerts(factory) if r.chat_id == CHAT]
    assert [r.text for r in online] == ["🟢 telemetry-agent voltou a ficar online."]


def test_empty_telegram_settings_are_treated_as_unset() -> None:
    from app.core.config import Settings

    settings = Settings(telegram_bot_username="", telegram_bot_token="  ")
    assert settings.telegram_bot_username is None and settings.telegram_bot_token is None
    assert Settings(telegram_bot_username="@my_bot_1").telegram_bot_username == "my_bot_1"
    with pytest.raises(ValueError):
        Settings(telegram_bot_username="no spaces allowed")


def test_send_document_builds_a_safe_multipart_upload(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import json as _json

    captured: dict[str, Any] = {}

    class _Response(io.BytesIO):
        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *_: object) -> None:
            return None

    def fake(request: Any, timeout: float, context: Any) -> _Response:
        captured["url"] = request.full_url
        captured["type"] = request.headers["Content-type"]
        captured["body"] = request.data
        return _Response(_json.dumps({"ok": True, "result": {}}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake)
    client = telegram_client.TelegramClient(SecretStr("123:abc"))
    client.send_document(42, 'rel"\r\natorio.pdf', b"\x00PDF-bytes", caption="📎 teste")
    assert captured["url"].endswith("/sendDocument")
    boundary = captured["type"].split("boundary=")[1]
    body: bytes = captured["body"]
    assert body.endswith(f"--{boundary}--\r\n".encode())
    assert b'filename="rel\'atorio.pdf"' in body  # quotes and CR/LF neutralized
    assert b"\x00PDF-bytes" in body and b"42" in body


def _press(data: str, *, chat: int = CHAT, sender: int | None = None) -> dict[str, Any]:
    return {
        "update_id": 2,
        "callback_query": {
            "id": "cb-1",
            "from": {"id": chat if sender is None else sender, "is_bot": False},
            "message": {"chat": {"id": chat, "type": "private"}},
            "data": data,
        },
    }


@pytest.mark.parametrize("data", ["", "rm -rf", "dev:not-a-uuid", "menu:unknown", "x" * 70])
def test_unknown_button_data_is_ignored_without_database(data: str) -> None:
    def no_db() -> Session:
        raise AssertionError("database must not be reached")

    assert (
        commands.handle_update(_press(data), session_factory=no_db, admission=_Admission()) is None
    )


def test_button_from_another_telegram_user_is_ignored() -> None:
    def no_db() -> Session:
        raise AssertionError("database must not be reached")

    update = _press("menu:status", sender=CHAT + 1)
    assert commands.handle_update(update, session_factory=no_db, admission=_Admission()) is None


@pytest.mark.postgresql
def test_menu_buttons_and_device_card_flow(factory: sessionmaker[Session]) -> None:
    user_id, device_id, private = _active_device(factory)
    device_online.heartbeat(factory, device_id=device_id, jws=_beat(private, device_id, 1, VALID))
    _link(factory, user_id)

    panel = commands.handle_update(
        _msg(commands.MENU_PANEL), session_factory=factory, admission=_Admission()
    )
    assert panel is not None and panel.text.startswith("🛡️ AVAL — PROTEGIDO")
    assert "Computadores online: 1 de 1" in panel.text
    assert panel.keyboard is not None
    buttons = [b for row in panel.keyboard["inline_keyboard"] for b in row]
    assert {"text": "🔍 telemetry-agent", "callback_data": f"dev:{device_id}"} in buttons

    card = commands.handle_update(
        _press(f"dev:{device_id}"), session_factory=factory, admission=_Admission()
    )
    assert card is not None and card.callback_id == "cb-1"
    assert card.text.startswith("🖥️ telemetry-agent") and "ONLINE" in card.text
    assert "RAM: 6,0 de 16,0 GB" in card.text and "Temperatura: 48 °C" in card.text
    assert card.keyboard is not None
    card_buttons = [b["callback_data"] for row in card.keyboard["inline_keyboard"] for b in row]
    assert f"act:lock:{device_id}" in card_buttons and f"act:photo:{device_id}" in card_buttons

    other_user, other_device, _ = _active_device(factory)
    foreign = commands.handle_update(
        _press(f"dev:{other_device}"), session_factory=factory, admission=_Admission()
    )
    assert foreign is not None and foreign.text == "Computador não encontrado."
    assert other_user != user_id

    hint = commands.handle_update(
        _msg("🤖 IA"), session_factory=factory, admission=_Admission()
    )  # button from an older keyboard still answers
    assert hint is not None and "Escreva sua pergunta" in hint.text
