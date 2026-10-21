"""Command handling for linked and unlinked private chats.

Every reply is plain text. Unlinked chats only learn how to link; they never
see whether a code, user, or device exists.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, cast

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.auth import device_online
from app.auth.abuse_control import AbuseControlUnavailable
from app.db.models import Device
from app.devices import telemetry
from app.telegram import linking
from app.telegram.formatting import device_line

SessionFactory = Callable[[], Session]

HELP = (
    "Comandos:\n"
    "/status — estado e telemetria dos seus dispositivos\n"
    "/desvincular — desliga este chat da sua conta\n"
    "/ajuda — esta mensagem"
)
NOT_LINKED = (
    "Este chat não está vinculado.\n"
    "No painel do Bots Central, gere um código em “Vincular Telegram” e envie aqui:\n"
    "/vincular SEU-CODIGO"
)


class LinkAdmission(Protocol):
    def admit_telegram_link(self, *, chat_id: int) -> bool: ...


@dataclass(frozen=True)
class Reply:
    chat_id: int
    text: str


def _private_message(update: dict[str, Any]) -> tuple[int, int, str] | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    sender = message.get("from")
    body = message.get("text")
    if not isinstance(chat, dict) or not isinstance(sender, dict) or not isinstance(body, str):
        return None
    if chat.get("type") != "private" or sender.get("is_bot") is True:
        return None
    chat_id, user_id = chat.get("id"), sender.get("id")
    if not isinstance(chat_id, int) or not isinstance(user_id, int) or chat_id != user_id:
        return None
    return chat_id, user_id, body[:512]


def _command(body: str) -> tuple[str, str]:
    head, _, rest = body.strip().partition(" ")
    name = head.split("@", 1)[0].lower()
    return name, rest.strip()


def status_text(session: Session, user_id: Any) -> str:
    now = cast(datetime, session.scalar(text("SELECT clock_timestamp()")))
    devices = session.scalars(
        select(Device).where(Device.user_id == user_id).order_by(Device.created_at, Device.id)
    ).all()
    if not devices:
        return "Você ainda não tem dispositivos. Adicione um pelo painel."
    latest = telemetry.latest_for_devices(session, [item.id for item in devices])
    lines = [
        device_line(item, device_online.presence(now, item), latest.get(item.id))
        for item in devices
    ]
    return "\n".join(lines)


def handle_update(
    update: dict[str, Any], *, session_factory: SessionFactory, admission: LinkAdmission
) -> Reply | None:
    parsed = _private_message(update)
    if parsed is None:
        return None
    chat_id, telegram_user_id, body = parsed
    name, argument = _command(body)

    if name in {"/vincular", "/start"} and argument:
        try:
            if not admission.admit_telegram_link(chat_id=chat_id):
                return Reply(chat_id, "Muitas tentativas. Aguarde alguns minutos.")
        except AbuseControlUnavailable:
            return Reply(chat_id, "Serviço indisponível no momento. Tente mais tarde.")
        try:
            linking.consume_link_code(
                session_factory,
                raw_code=argument,
                chat_id=chat_id,
                telegram_user_id=telegram_user_id,
            )
        except (linking.InvalidLinkCode, linking.AlreadyLinked):
            return Reply(chat_id, "Código inválido ou expirado. Gere um novo no painel.")
        return Reply(chat_id, "✅ Chat vinculado à sua conta.\n\n" + HELP)

    with session_factory() as session:
        user_id = linking.linked_user_id(
            session, chat_id=chat_id, telegram_user_id=telegram_user_id
        )
        if user_id is None:
            return Reply(chat_id, NOT_LINKED)
        if name == "/status":
            return Reply(chat_id, status_text(session, user_id))
    if name == "/desvincular":
        linking.unlink_chat(session_factory, chat_id=chat_id)
        return Reply(chat_id, "Chat desvinculado. Você não receberá mais alertas aqui.")
    return Reply(chat_id, HELP)
