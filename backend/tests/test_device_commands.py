"""Human-approved file transfer (ADR-015)."""

import base64
import hashlib
import uuid
from collections.abc import Generator
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import delete, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from test_device_telemetry import _active_device, _beat, pg_cleanup  # noqa: F401
from test_telegram import CHAT, _Admission, _link, _msg

from app.audit import events as audit
from app.auth import device_online
from app.auth.abuse_control import AbuseControlKey
from app.db.models import CommandPayload, DeviceCommand, TelegramLink, UserEmail
from app.devices import commands
from app.telegram.commands import ActionDeps, handle_update

KEY = AbuseControlKey(base64.urlsafe_b64encode(b"c" * 32).decode().rstrip("="))
FILE = b"conteudo do relatorio\n" * 100


class _Mailer:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def send_plain(self, *, recipient: str, subject: str, body: str) -> None:
        self.sent.append({"recipient": recipient, "subject": subject, "body": body})

    def last_code(self) -> str:
        body = self.sent[-1]["body"]
        return "".join(ch for ch in body.split("Código de aprovação: ")[1][:9] if ch.isdigit())


@pytest.mark.parametrize(
    ("name", "ok"),
    [
        ("relatorio.pdf", True),
        ("foto 01.jpg", True),
        ("../etc/passwd", False),
        ("a/b.txt", False),
        ("a\\b.txt", False),
        (".ssh", False),
        ("", False),
        (" espaço.txt", False),
        ("x" * 256, False),
        ("nul\x00.txt", False),
    ],
)
def test_file_name_rules(name: str, ok: bool) -> None:
    assert commands.valid_file_name(name) is ok


@pytest.fixture
def setup(
    migrated_postgresql_engine: Engine, request: pytest.FixtureRequest
) -> Generator[tuple[sessionmaker[Session], uuid.UUID, uuid.UUID, Ed25519PrivateKey], None, None]:
    request.getfixturevalue("pg_cleanup")
    factory = sessionmaker(bind=migrated_postgresql_engine)
    user_id, device_id, private = _active_device(factory)
    email = f"cmd-{uuid.uuid4().hex[:8]}@example.com"
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
    _link(factory, user_id)
    yield factory, user_id, device_id, private
    with factory() as session, session.begin():
        session.execute(delete(TelegramLink).where(TelegramLink.chat_id == CHAT))
        session.execute(delete(DeviceCommand).where(DeviceCommand.user_id == user_id))
        session.execute(delete(UserEmail).where(UserEmail.user_id == user_id))


def _send(factory: sessionmaker[Session], text_: str, mailer: _Mailer) -> str:
    reply = handle_update(
        _msg(text_),
        session_factory=factory,
        admission=_Admission(),
        actions=ActionDeps(key=KEY, mailer=mailer),
    )
    assert reply is not None
    return reply.text


def _signed(
    private: Ed25519PrivateKey, device_id: uuid.UUID, seq: int, aud: str, **extra: Any
) -> str:
    return jwt.encode(
        {"aud": aud, "sub": str(device_id), "seq": seq, **extra}, private, algorithm="EdDSA"
    )


def _result(
    factory: sessionmaker[Session],
    private: Ed25519PrivateKey,
    device_id: uuid.UUID,
    command_id: uuid.UUID,
    seq: int,
    content: bytes,
    *,
    claimed: bytes | None = None,
) -> None:
    signed_bytes = content if claimed is None else claimed
    commands.submit_result(
        factory,
        device_id=device_id,
        command_id=command_id,
        jws=_signed(
            private,
            device_id,
            seq,
            commands.RESULT_AUDIENCE,
            cid=str(command_id),
            status="ok",
            size=len(signed_bytes),
            sha256=hashlib.sha256(signed_bytes).hexdigest(),
        ),
        content_b64=base64.b64encode(content).decode(),
    )


@pytest.mark.postgresql
def test_full_flow_request_approve_poll_result_deliver(setup: Any) -> None:
    factory, user_id, device_id, private = setup
    mailer = _Mailer()
    text_ = _send(factory, "/enviar TELEMETRY-AGENT relatorio.pdf", mailer)
    assert "código para o seu e-mail" in text_
    assert "relatorio.pdf" in mailer.sent[0]["body"] and "telemetry-agent" in mailer.sent[0]["body"]
    code = mailer.last_code()

    # Not approved yet: the agent sees nothing.
    assert (
        commands.next_command(
            factory, device_id=device_id, jws=_signed(private, device_id, 1, commands.POLL_AUDIENCE)
        )
        is None
    )

    wrong = f"{(int(code) + 1) % 10**8:08d}"
    assert "inválido" in _send(factory, f"/aprovar {wrong}", mailer)
    assert "Aprovado" in _send(factory, f"/aprovar {code[:4]} {code[4:]}", mailer)

    command = commands.next_command(
        factory, device_id=device_id, jws=_signed(private, device_id, 2, commands.POLL_AUDIENCE)
    )
    assert command is not None and command["file_name"] == "relatorio.pdf"
    command_id = uuid.UUID(command["id"])
    assert (
        commands.next_command(
            factory, device_id=device_id, jws=_signed(private, device_id, 3, commands.POLL_AUDIENCE)
        )
        is None
    )

    _result(factory, private, device_id, command_id, 4, FILE)
    deliveries, notices = commands.pending_deliveries(factory)
    assert notices == [] and len(deliveries) == 1
    assert deliveries[0].content == FILE and deliveries[0].chat_id == CHAT
    commands.mark_delivered(factory, command_id=command_id)
    with factory() as session:
        assert session.get(CommandPayload, command_id) is None
        assert session.get(DeviceCommand, command_id).status == "delivered"
        actions = [e.action for e in reversed(audit.list_for_user(session, user_id=user_id))]
    assert actions[-6:] == [
        "action.requested",
        "action.approval_failed",
        "action.approved",
        "action.dispatched",
        "action.completed",
        "action.delivered",
    ]


@pytest.mark.postgresql
def test_tampered_or_replayed_device_requests_are_rejected(setup: Any) -> None:
    factory, _user_id, device_id, private = setup
    mailer = _Mailer()
    _send(factory, "/enviar telemetry-agent a.txt", mailer)
    _send(factory, f"/aprovar {mailer.last_code()}", mailer)
    poll = _signed(private, device_id, 10, commands.POLL_AUDIENCE)
    command = commands.next_command(factory, device_id=device_id, jws=poll)
    assert command is not None
    command_id = uuid.UUID(command["id"])
    with pytest.raises(device_online.StaleHeartbeat):
        commands.next_command(factory, device_id=device_id, jws=poll)
    with pytest.raises(device_online.StaleHeartbeat):  # shared sequence with heartbeats
        device_online.heartbeat(factory, device_id=device_id, jws=_beat(private, device_id, 10))
    with pytest.raises(device_online.InvalidProof):  # wrong audience
        commands.next_command(
            factory,
            device_id=device_id,
            jws=_signed(private, device_id, 11, "bots-central:heartbeat:v1"),
        )
    with pytest.raises(device_online.InvalidProof):  # bytes differ from the signed hash
        _result(factory, private, device_id, command_id, 12, FILE, claimed=b"other bytes")
    other = Ed25519PrivateKey.generate()
    with pytest.raises(device_online.InvalidProof):  # not the device key
        _result(factory, other, device_id, command_id, 13, FILE)
    _result(factory, private, device_id, command_id, 14, FILE)
    with pytest.raises(commands.CommandError):  # already completed
        _result(factory, private, device_id, command_id, 15, FILE)


@pytest.mark.postgresql
def test_denied_after_five_wrong_codes_and_expiry_and_failure_notices(setup: Any) -> None:
    factory, user_id, device_id, private = setup
    mailer = _Mailer()
    _send(factory, "/enviar telemetry-agent x.txt", mailer)
    code = mailer.last_code()
    wrong = f"{(int(code) + 3) % 10**8:08d}"
    for _ in range(commands.MAX_ATTEMPTS):
        _send(factory, f"/aprovar {wrong}", mailer)
    assert "inválido" in _send(factory, f"/aprovar {code}", mailer)
    _, notices = commands.pending_deliveries(factory)
    assert [n.text for n in notices] == [
        "⛔ Pedido de x.txt bloqueado: código errado demais vezes."
    ]
    assert commands.pending_deliveries(factory)[1] == []  # reported once

    _send(factory, "/enviar telemetry-agent y.txt", mailer)
    with factory() as session, session.begin():
        session.execute(
            update(DeviceCommand)
            .where(DeviceCommand.user_id == user_id, DeviceCommand.status == "pending_approval")
            .values(approval_expires_at=text("clock_timestamp() - interval '1 second'"))
        )
    assert "inválido" in _send(factory, f"/aprovar {mailer.last_code()}", mailer)
    assert [n.text for n in commands.pending_deliveries(factory)[1]] == [
        "⌛ Pedido de y.txt expirou sem ser concluído."
    ]

    _send(factory, "/enviar telemetry-agent z.txt", mailer)
    _send(factory, f"/aprovar {mailer.last_code()}", mailer)
    command = commands.next_command(
        factory, device_id=device_id, jws=_signed(private, device_id, 30, commands.POLL_AUDIENCE)
    )
    assert command is not None
    commands.submit_result(
        factory,
        device_id=device_id,
        command_id=uuid.UUID(command["id"]),
        jws=_signed(
            private,
            device_id,
            31,
            commands.RESULT_AUDIENCE,
            cid=command["id"],
            status="error",
            error="not_found",
        ),
        content_b64=None,
    )
    assert [n.text for n in commands.pending_deliveries(factory)[1]] == [
        "❌ Não foi possível enviar z.txt: o arquivo não está na pasta compartilhada."
    ]


@pytest.mark.postgresql
def test_bad_requests_are_explained_and_create_nothing(setup: Any) -> None:
    factory, user_id, _device_id, _ = setup
    mailer = _Mailer()
    assert "Use:" in _send(factory, "/enviar", mailer)
    assert "Nome de arquivo inválido" in _send(
        factory, "/enviar telemetry-agent ../senhas.txt", mailer
    )
    assert "não encontrado" in _send(factory, "/enviar PC-DE-OUTRO a.txt", mailer)
    assert (
        "Ações não estão ativadas"
        in (
            handle_update(
                _msg("/enviar telemetry-agent a.txt"),
                session_factory=factory,
                admission=_Admission(),
            )
            or pytest.fail("no reply")
        ).text
    )
    assert mailer.sent == []
    with factory() as session:
        assert (
            session.scalars(select(DeviceCommand).where(DeviceCommand.user_id == user_id)).all()
            == []
        )
