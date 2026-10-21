"""Human-approved device commands (ADR-015). v0.1 supports only ``send_file``.

Lifecycle::

    pending_approval --(right e-mail code)--> approved --(agent polls)--> dispatched
        --(agent result ok)--> completed --(bot sends to Telegram)--> delivered
    pending_approval --(5 wrong codes)--> denied ;  any open state --(timeout)--> expired
    dispatched --(agent result error)--> failed

Security properties:

* the approval code is e-mailed, bound to this one command (HMAC over command id + code),
  valid for 5 minutes, at most 5 wrong guesses;
* the agent only learns about a command after approval, through a request signed with its
  own Ed25519 key that consumes the shared anti-replay sequence;
* the agent answers with the file bytes plus a *signed* SHA-256 and size, so the server
  stores only bytes that the device key vouched for;
* the AI assistant has no path to create or approve commands (ADR-013).
"""

import base64
import hashlib
import hmac
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from pydantic import SecretStr
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from app.audit import events as audit
from app.auth import device_online
from app.auth.abuse_control import AbuseControlKey
from app.db.enums import AccountStatus, DeviceLifecycleStatus
from app.db.models import CommandPayload, Device, DeviceCommand, User, UserEmail

SessionFactory = Callable[[], Session]

POLL_AUDIENCE = "bots-central:commands:v1"
RESULT_AUDIENCE = "bots-central:command-result:v1"
APPROVAL_TTL = timedelta(minutes=5)
EXECUTION_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_OPEN_PER_USER = 3
CODE_DIGITS = 8
ERROR_CODES = frozenset({"not_found", "not_regular", "too_large", "read_error", "disabled"})


class CommandError(Exception):
    """Base class; ``message`` is safe to show to the owner."""

    message = "Não foi possível concluir o pedido."


class DeviceNotFoundForUser(CommandError):
    message = "Dispositivo não encontrado ou não está ativo."


class InvalidFileName(CommandError):
    message = "Nome de arquivo inválido. Use só o nome, sem pastas (ex.: relatorio.pdf)."


class TooManyOpenCommands(CommandError):
    message = "Você já tem pedidos em andamento. Aguarde terminarem."


class NoEmail(CommandError):
    message = "Sua conta não tem e-mail verificado para receber o código."


class InvalidApproval(CommandError):
    message = "Código inválido ou expirado."


@dataclass(frozen=True)
class ApprovalIntent:
    command_id: uuid.UUID
    recipient: str = field(repr=False)
    code: SecretStr = field(repr=False)
    device_name: str
    file_name: str
    expires_at: datetime


def valid_file_name(name: str) -> bool:
    return (
        0 < len(name) <= 255
        and name == name.strip()
        and not name.startswith(".")
        and not any(ch in name for ch in ("/", "\\", "\x00"))
        and all(ch.isprintable() for ch in name)
    )


def _now(session: Session) -> datetime:
    value = session.scalar(text("SELECT clock_timestamp()"))
    assert isinstance(value, datetime)
    return value


def _mac(key: AbuseControlKey, command_id: uuid.UUID, code: str) -> bytes:
    return key.pseudonymize("device-command-approval", f"{command_id}:{code}")


# --- owner side (Telegram) --------------------------------------------------------------


def request_send_file(
    session_factory: SessionFactory,
    key: AbuseControlKey,
    *,
    user_id: uuid.UUID,
    chat_id: int,
    device_name: str,
    file_name: str,
) -> ApprovalIntent:
    if not valid_file_name(file_name):
        raise InvalidFileName
    code = f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"
    with session_factory() as session, session.begin():
        user = session.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None or user.status is not AccountStatus.ACTIVE:
            raise DeviceNotFoundForUser
        device = session.scalar(
            select(Device).where(
                Device.user_id == user_id,
                func.lower(Device.name) == device_name.strip().lower(),
                Device.lifecycle_status == DeviceLifecycleStatus.ACTIVE,
            )
        )
        if device is None:
            raise DeviceNotFoundForUser
        email = session.scalar(
            select(UserEmail).where(
                UserEmail.user_id == user_id,
                UserEmail.is_primary.is_(True),
                UserEmail.verified_at.is_not(None),
            )
        )
        if email is None:
            raise NoEmail
        now = _now(session)
        _expire(session, now)
        open_count = session.scalar(
            select(func.count())
            .select_from(DeviceCommand)
            .where(
                DeviceCommand.user_id == user_id,
                DeviceCommand.status.in_(("pending_approval", "approved", "dispatched")),
            )
        )
        if (open_count or 0) >= MAX_OPEN_PER_USER:
            raise TooManyOpenCommands
        command_id = uuid.uuid4()
        session.add(
            DeviceCommand(
                id=command_id,
                user_id=user_id,
                device_id=device.id,
                kind="send_file",
                file_name=file_name,
                status="pending_approval",
                approval_mac=_mac(key, command_id, code),
                chat_id=chat_id,
                created_at=now,
                approval_expires_at=now + APPROVAL_TTL,
            )
        )
        audit.record(
            session,
            user_id=user_id,
            action="action.requested",
            actor="telegram",
            target_type="command",
            target_id=str(command_id),
            details={"name": device.name, "file": file_name},
        )
        return ApprovalIntent(
            command_id=command_id,
            recipient=email.email_display,
            code=SecretStr(code),
            device_name=device.name,
            file_name=file_name,
            expires_at=now + APPROVAL_TTL,
        )


def approve(
    session_factory: SessionFactory, key: AbuseControlKey, *, user_id: uuid.UUID, code: str
) -> DeviceCommand:
    """Approve the user's most recent pending command with its e-mailed code.

    A wrong code is committed (attempt counter) and then reported as InvalidApproval.
    """
    cleaned = code.replace(" ", "")
    if len(cleaned) != CODE_DIGITS or not cleaned.isascii() or not cleaned.isdigit():
        raise InvalidApproval
    approved: DeviceCommand | None = None
    with session_factory() as session, session.begin():
        now = _now(session)
        command = session.scalar(
            select(DeviceCommand)
            .where(
                DeviceCommand.user_id == user_id,
                DeviceCommand.status == "pending_approval",
                DeviceCommand.approval_expires_at > now,
            )
            .order_by(DeviceCommand.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        if command is None or command.approval_mac is None:
            raise InvalidApproval
        if hmac.compare_digest(command.approval_mac, _mac(key, command.id, cleaned)):
            command.status = "approved"
            command.approved_at = now
            command.approval_mac = None
            audit.record(
                session,
                user_id=user_id,
                action="action.approved",
                actor="telegram",
                target_type="command",
                target_id=str(command.id),
                details={"file": command.file_name},
            )
            session.flush()
            session.expunge(command)  # keep loaded values after commit
            approved = command
        else:
            command.approval_attempts += 1
            if command.approval_attempts >= MAX_ATTEMPTS:
                command.status = "denied"
                command.approval_mac = None
                command.finished_at = now
            audit.record(
                session,
                user_id=user_id,
                action="action.approval_failed",
                actor="telegram",
                target_type="command",
                target_id=str(command.id),
                outcome="denied",
            )
    if approved is None:
        raise InvalidApproval
    return approved


def _expire(session: Session, now: datetime) -> None:
    session.execute(
        update(DeviceCommand)
        .where(
            DeviceCommand.status == "pending_approval",
            DeviceCommand.approval_expires_at <= now,
        )
        .values(status="expired", approval_mac=None, finished_at=now)
    )
    session.execute(
        update(DeviceCommand)
        .where(
            DeviceCommand.status.in_(("approved", "dispatched")),
            DeviceCommand.approved_at <= now - EXECUTION_TTL,
        )
        .values(status="expired", finished_at=now, error_code="timeout")
    )


# --- device side (signed by the agent key) ------------------------------------------------


def _verify_signed(
    session: Session, *, device_id: uuid.UUID, jws: str, audience: str
) -> tuple[Device, dict[str, Any]]:
    device = session.scalar(select(Device).where(Device.id == device_id))
    if device is None:
        raise device_online.DeviceNotFound
    if device.lifecycle_status is DeviceLifecycleStatus.REVOKED:
        raise device_online.DeviceRevoked
    if device.lifecycle_status is not DeviceLifecycleStatus.ACTIVE or device.public_key is None:
        raise device_online.DevicePending
    claims = device_online._verify_jws(jws, device.public_key, audience=audience)
    sequence = claims.get("seq")
    if claims.get("sub") != str(device_id) or (
        isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or not 0 <= sequence <= device_online.MAX_SEQUENCE
    ):
        raise device_online.InvalidProof
    # The command channel shares the heartbeat's monotonic sequence: every signed
    # request is single-use across both endpoints.
    advanced = session.execute(
        update(Device)
        .where(
            Device.id == device_id,
            Device.lifecycle_status == DeviceLifecycleStatus.ACTIVE,
            Device.public_key == device.public_key,
            (Device.last_heartbeat_seq.is_(None)) | (Device.last_heartbeat_seq < sequence),
        )
        .values(last_heartbeat_seq=sequence)
        .returning(Device.id)
    ).scalar_one_or_none()
    if advanced is None:
        raise device_online.StaleHeartbeat
    return device, claims


def next_command(
    session_factory: SessionFactory, *, device_id: uuid.UUID, jws: str
) -> dict[str, str] | None:
    with session_factory() as session, session.begin():
        _verify_signed(session, device_id=device_id, jws=jws, audience=POLL_AUDIENCE)
        now = _now(session)
        _expire(session, now)
        command = session.scalar(
            select(DeviceCommand)
            .where(DeviceCommand.device_id == device_id, DeviceCommand.status == "approved")
            .order_by(DeviceCommand.approved_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if command is None:
            return None
        command.status = "dispatched"
        command.dispatched_at = now
        audit.record(
            session,
            user_id=command.user_id,
            action="action.dispatched",
            actor="device",
            target_type="command",
            target_id=str(command.id),
        )
        return {"id": str(command.id), "type": command.kind, "file_name": command.file_name}


def submit_result(
    session_factory: SessionFactory,
    *,
    device_id: uuid.UUID,
    command_id: uuid.UUID,
    jws: str,
    content_b64: str | None,
) -> None:
    """Accept the agent's signed result; bytes must match the signed size and SHA-256."""
    with session_factory() as session, session.begin():
        _, claims = _verify_signed(session, device_id=device_id, jws=jws, audience=RESULT_AUDIENCE)
        if claims.get("cid") != str(command_id):
            raise device_online.InvalidProof
        command = session.scalar(
            select(DeviceCommand)
            .where(DeviceCommand.id == command_id, DeviceCommand.device_id == device_id)
            .with_for_update()
        )
        if command is None or command.status != "dispatched":
            raise CommandError
        now = _now(session)
        status = claims.get("status")
        if status == "error":
            code = claims.get("error")
            command.status = "failed"
            command.error_code = code if isinstance(code, str) and code in ERROR_CODES else "error"
            command.finished_at = now
            audit.record(
                session,
                user_id=command.user_id,
                action="action.failed",
                actor="device",
                target_type="command",
                target_id=str(command.id),
                outcome="failure",
                details={"error": command.error_code},
            )
            return
        size = claims.get("size")
        digest_text = claims.get("sha256")
        if (
            status != "ok"
            or content_b64 is None
            or isinstance(size, bool)
            or not isinstance(size, int)
            or not 0 <= size <= MAX_FILE_BYTES
            or not isinstance(digest_text, str)
        ):
            raise device_online.InvalidProof
        try:
            content = base64.b64decode(content_b64, validate=True)
            signed_digest = bytes.fromhex(digest_text)
        except ValueError as error:
            raise device_online.InvalidProof from error
        if (
            len(content) != size
            or len(signed_digest) != 32
            or not hmac.compare_digest(hashlib.sha256(content).digest(), signed_digest)
        ):
            raise device_online.InvalidProof
        session.add(
            CommandPayload(
                command_id=command.id,
                content=content,
                size_bytes=size,
                sha256=signed_digest,
                created_at=now,
            )
        )
        command.status = "completed"
        command.finished_at = now
        audit.record(
            session,
            user_id=command.user_id,
            action="action.completed",
            actor="device",
            target_type="command",
            target_id=str(command.id),
            details={"file": command.file_name, "size_bytes": size},
        )


# --- delivery (bot process) -------------------------------------------------------------


@dataclass(frozen=True)
class Delivery:
    command_id: uuid.UUID
    chat_id: int
    file_name: str
    device_name: str
    content: bytes = field(repr=False)


@dataclass(frozen=True)
class Notice:
    chat_id: int
    text: str


def pending_deliveries(session_factory: SessionFactory) -> tuple[list[Delivery], list[Notice]]:
    """Completed files to send, plus failure/expiry notices (each reported once)."""
    deliveries: list[Delivery] = []
    notices: list[Notice] = []
    with session_factory() as session, session.begin():
        now = _now(session)
        _expire(session, now)
        rows = session.execute(
            select(DeviceCommand, CommandPayload, Device.name)
            .join(CommandPayload, CommandPayload.command_id == DeviceCommand.id)
            .join(Device, Device.id == DeviceCommand.device_id)
            .where(DeviceCommand.status == "completed", DeviceCommand.chat_id.is_not(None))
            .limit(5)
        ).all()
        for command, payload, device_name in rows:
            assert command.chat_id is not None
            deliveries.append(
                Delivery(
                    command.id, command.chat_id, command.file_name, device_name, payload.content
                )
            )
        closed = session.scalars(
            select(DeviceCommand)
            .where(
                DeviceCommand.status.in_(("failed", "expired", "denied")),
                DeviceCommand.chat_id.is_not(None),
            )
            .with_for_update(skip_locked=True)
        ).all()
        for command in closed:
            assert command.chat_id is not None
            notices.append(Notice(command.chat_id, _closed_text(command)))
            command.chat_id = None  # report once
    return deliveries, notices


def _closed_text(command: DeviceCommand) -> str:
    if command.status == "denied":
        return f"⛔ Pedido de {command.file_name} bloqueado: código errado demais vezes."
    if command.status == "expired":
        return f"⌛ Pedido de {command.file_name} expirou sem ser concluído."
    reasons = {
        "not_found": "o arquivo não está na pasta compartilhada",
        "not_regular": "não é um arquivo comum",
        "too_large": "o arquivo passa de 10 MB",
        "disabled": "o envio de arquivos está desligado nesse computador",
    }
    reason = reasons.get(command.error_code or "", "erro ao ler o arquivo")
    return f"❌ Não foi possível enviar {command.file_name}: {reason}."


def mark_delivered(session_factory: SessionFactory, *, command_id: uuid.UUID) -> None:
    with session_factory() as session, session.begin():
        command = session.scalar(
            select(DeviceCommand).where(DeviceCommand.id == command_id).with_for_update()
        )
        if command is None or command.status != "completed":
            return
        session.execute(delete(CommandPayload).where(CommandPayload.command_id == command_id))
        command.status = "delivered"
        audit.record(
            session,
            user_id=command.user_id,
            action="action.delivered",
            actor="system",
            target_type="command",
            target_id=str(command.id),
            details={"file": command.file_name},
        )
