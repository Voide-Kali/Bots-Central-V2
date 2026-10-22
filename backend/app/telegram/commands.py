"""Command handling for linked and unlinked private chats.

Every reply is plain text. Unlinked chats only learn how to link; they never
see whether a code, user, or device exists.

Buttons (inline keyboards and the persistent menu) are only shortcuts for the
same commands: a button press goes through exactly the same private-chat and
linked-account checks as a typed message.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, cast

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.assistant import assistant
from app.assistant.ollama import AssistantUnavailable
from app.audit import events as audit
from app.auth import device_online
from app.auth.abuse_control import AbuseControlKey, AbuseControlUnavailable
from app.db.models import Device
from app.devices import commands, telemetry
from app.telegram import linking
from app.telegram.formatting import device_card, device_line

SessionFactory = Callable[[], Session]

HELP = (
    "Pergunte em texto livre (ex.: “qual PC está mais quente?”) e a IA responde.\n\n"
    "Comandos:\n"
    "/status — estado e telemetria dos seus dispositivos\n"
    "/historico — últimas ações na sua conta\n"
    "/enviar PC arquivo — pede um arquivo da pasta compartilhada (código no e-mail)\n"
    "/aprovar 12345678 — confirma o pedido com o código do e-mail\n"
    "/desvincular — desliga este chat da sua conta\n"
    "/ajuda — esta mensagem\n\n"
    "Ou use os botões do menu aqui embaixo."
)
NOT_LINKED = (
    "Este chat não está vinculado.\n"
    "No painel do Aval, gere um código em “Vincular Telegram” e envie aqui:\n"
    "/vincular SEU-CODIGO"
)


class LinkAdmission(Protocol):
    def admit_telegram_link(self, *, chat_id: int) -> bool: ...

    def admit_assistant(self, *, chat_id: int) -> bool: ...


@dataclass(frozen=True)
class Reply:
    chat_id: int
    text: str
    keyboard: dict[str, Any] | None = None
    callback_id: str | None = None


MENU_PANEL = "📊 Painel"
MENU_AI = "🤖 IA"
MENU_HISTORY = "🧾 Histórico"
MENU_FILE = "📎 Arquivo"
MENU_HELP = "❓ Ajuda"
MENU_KEYBOARD: dict[str, Any] = {
    "keyboard": [
        [{"text": MENU_PANEL}, {"text": MENU_AI}],
        [{"text": MENU_HISTORY}, {"text": MENU_FILE}],
        [{"text": MENU_HELP}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}
MENU_ALIASES = {
    MENU_PANEL: "/status",
    MENU_HISTORY: "/historico",
    MENU_HELP: "/ajuda",
    MENU_AI: "/ia",
    MENU_FILE: "/arquivo",
}
CALLBACKS = {"menu:status": "/status", "menu:hist": "/historico", "menu:help": "/ajuda"}
AI_HINT = (
    "🤖 Escreva sua pergunta em texto livre, por exemplo:\n"
    "• qual computador está mais quente?\n"
    "• quanto de memória o Mac está usando?\n"
    "• algum computador está offline?\n\n"
    "A IA só lê os dados dos seus computadores. Ela não consegue executar nada."
)
FILE_HINT = (
    "📎 Para receber um arquivo de um computador:\n"
    "1. Coloque o arquivo na pasta compartilhada do computador "
    "(Mac: ~/Aval-Compartilhado · Linux: /srv/aval-compartilhado).\n"
    "2. Envie aqui: /enviar NOME-DO-PC nome-do-arquivo.pdf\n"
    "3. Chega um código no seu e-mail. Responda: /aprovar CÓDIGO\n\n"
    "Sem o seu código, nenhum arquivo sai do computador."
)


def _button(text: str, data: str) -> dict[str, str]:
    return {"text": text[:60], "callback_data": data}


def _private_message(update: dict[str, Any]) -> tuple[int, int, str, str | None] | None:
    """(chat_id, user_id, text, callback_id) for a private message or a button press."""
    callback_id: str | None = None
    callback = update.get("callback_query")
    if isinstance(callback, dict):
        message = callback.get("message")
        sender = callback.get("from")
        data = callback.get("data")
        raw_id = callback.get("id")
        if not isinstance(message, dict) or not isinstance(data, str):
            return None
        if not isinstance(raw_id, str):
            return None
        chat = message.get("chat")
        body = _callback_command(data)
        if body is None:
            return None
        callback_id = raw_id
    else:
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
    body = MENU_ALIASES.get(body.strip(), body)
    return chat_id, user_id, body[:512], callback_id


def _callback_command(data: str) -> str | None:
    if data in CALLBACKS:
        return CALLBACKS[data]
    if data.startswith("dev:"):
        try:
            return f"/pc {uuid.UUID(data[4:])}"
        except ValueError:
            return None
    return None


def _command(body: str) -> tuple[str, str]:
    head, _, rest = body.strip().partition(" ")
    name = head.split("@", 1)[0].lower()
    return name, rest.strip()


def _user_devices(session: Session, user_id: Any) -> tuple[datetime, list[Device]]:
    now = cast(datetime, session.scalar(text("SELECT clock_timestamp()")))
    devices = session.scalars(
        select(Device).where(Device.user_id == user_id).order_by(Device.created_at, Device.id)
    ).all()
    return now, list(devices)


def status_text(session: Session, user_id: Any) -> str:
    now, devices = _user_devices(session, user_id)
    if not devices:
        return "Você ainda não tem computadores. Adicione um pelo painel do Aval."
    latest = telemetry.latest_for_devices(session, [item.id for item in devices])
    presences = [device_online.presence(now, item) for item in devices]
    online = sum(
        1
        for item, presence in zip(devices, presences, strict=True)
        if presence == "online" and item.lifecycle_status.value == "active"
    )
    header = f"📊 Seus computadores — {online} de {len(devices)} online"
    lines = [
        device_line(item, presence, latest.get(item.id))
        for item, presence in zip(devices, presences, strict=True)
    ]
    return header + "\n\n" + "\n\n".join(lines)


def status_keyboard(session: Session, user_id: Any) -> dict[str, Any]:
    _, devices = _user_devices(session, user_id)
    rows = [[_button(f"🔍 {item.name}", f"dev:{item.id}")] for item in devices[:20]]
    rows.append([_button("🔄 Atualizar", "menu:status"), _button("🧾 Histórico", "menu:hist")])
    return {"inline_keyboard": rows}


def device_reply(session: Session, user_id: Any, chat_id: int, raw_id: str) -> Reply:
    try:
        device_id = uuid.UUID(raw_id)
    except ValueError:
        return Reply(chat_id, "Computador não encontrado.")
    now, devices = _user_devices(session, user_id)
    device = next((item for item in devices if item.id == device_id), None)
    if device is None:  # never reveal other users' devices
        return Reply(chat_id, "Computador não encontrado.")
    sample = telemetry.latest_for_devices(session, [device.id]).get(device.id)
    card = device_card(device, device_online.presence(now, device), sample, now)
    keyboard = {
        "inline_keyboard": [
            [
                _button("🔄 Atualizar", f"dev:{device.id}"),
                _button("‹ Voltar ao painel", "menu:status"),
            ]
        ]
    }
    return Reply(chat_id, card, keyboard)


class Mailer(Protocol):
    def send_plain(self, *, recipient: str, subject: str, body: str) -> None: ...


@dataclass(frozen=True)
class ActionDeps:
    key: AbuseControlKey
    mailer: Mailer


def handle_update(
    update: dict[str, Any],
    *,
    session_factory: SessionFactory,
    admission: LinkAdmission,
    model: assistant.ChatModel | None = None,
    actions: ActionDeps | None = None,
) -> Reply | None:
    parsed = _private_message(update)
    if parsed is None:
        return None
    chat_id, telegram_user_id, body, callback_id = parsed
    reply = _dispatch(chat_id, telegram_user_id, body, session_factory, admission, model, actions)
    if callback_id is not None:
        return Reply(reply.chat_id, reply.text, reply.keyboard, callback_id)
    return reply


def _dispatch(
    chat_id: int,
    telegram_user_id: int,
    body: str,
    session_factory: SessionFactory,
    admission: LinkAdmission,
    model: assistant.ChatModel | None,
    actions: ActionDeps | None,
) -> Reply:
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
        return Reply(chat_id, "✅ Chat vinculado à sua conta.\n\n" + HELP, MENU_KEYBOARD)

    with session_factory() as session:
        user_id = linking.linked_user_id(
            session, chat_id=chat_id, telegram_user_id=telegram_user_id
        )
        if user_id is None:
            return Reply(chat_id, NOT_LINKED)
        if name == "/status":
            return Reply(chat_id, status_text(session, user_id), status_keyboard(session, user_id))
        if name == "/pc":
            return device_reply(session, user_id, chat_id, argument)
        if name == "/historico":
            rows = audit.list_for_user(session, user_id=user_id, limit=10)
            body_text = "\n".join(audit.label(row) for row in rows) or "Nenhuma ação registrada."
            return Reply(
                chat_id,
                "🧾 Últimas ações:\n" + body_text,
                {"inline_keyboard": [[_button("‹ Voltar ao painel", "menu:status")]]},
            )
    if name == "/ia":
        return Reply(chat_id, AI_HINT)
    if name == "/arquivo":
        return Reply(chat_id, FILE_HINT)
    if not body.startswith("/"):
        return _ask(chat_id, user_id, body, session_factory, admission, model)
    if name in {"/enviar", "/aprovar"}:
        if actions is None:
            return Reply(chat_id, "Ações não estão ativadas neste servidor.")
        try:
            if not admission.admit_telegram_link(chat_id=chat_id):
                return Reply(chat_id, "Muitas tentativas. Aguarde alguns minutos.")
        except AbuseControlUnavailable:
            return Reply(chat_id, "Serviço indisponível no momento. Tente mais tarde.")
        if name == "/enviar":
            return _request_file(chat_id, user_id, argument, session_factory, actions)
        return _approve(chat_id, user_id, argument, session_factory, actions)
    if name == "/desvincular":
        linking.unlink_chat(session_factory, chat_id=chat_id)
        return Reply(chat_id, "Chat desvinculado. Você não receberá mais alertas aqui.")
    return Reply(chat_id, HELP, MENU_KEYBOARD)


def _ask(
    chat_id: int,
    user_id: Any,
    question: str,
    session_factory: SessionFactory,
    admission: LinkAdmission,
    model: assistant.ChatModel | None,
) -> Reply:
    if model is None:
        return Reply(chat_id, "A IA não está ativada neste servidor.\n\n" + HELP)
    try:
        if not admission.admit_assistant(chat_id=chat_id):
            return Reply(chat_id, "Muitas perguntas seguidas. Aguarde alguns minutos.")
    except AbuseControlUnavailable:
        return Reply(chat_id, "Serviço indisponível no momento. Tente mais tarde.")
    try:
        text_reply = assistant.answer(session_factory, model, user_id=user_id, question=question)
    except AssistantUnavailable:
        return Reply(chat_id, "A IA não respondeu a tempo. Tente de novo em instantes.")
    return Reply(chat_id, "🤖 " + text_reply)


def _request_file(
    chat_id: int, user_id: Any, argument: str, session_factory: SessionFactory, actions: ActionDeps
) -> Reply:
    device_name, _, file_name = argument.partition(" ")
    if not device_name or not file_name.strip():
        return Reply(chat_id, "Use: /enviar NOME-DO-PC nome-do-arquivo.pdf")
    try:
        intent = commands.request_send_file(
            session_factory,
            actions.key,
            user_id=user_id,
            chat_id=chat_id,
            device_name=device_name,
            file_name=file_name.strip(),
        )
    except commands.CommandError as error:
        return Reply(chat_id, error.message)
    code = intent.code.get_secret_value()
    try:
        actions.mailer.send_plain(
            recipient=intent.recipient,
            subject=f"Aval — aprovar envio de {intent.file_name}",
            body=(
                "Pedido no Aval:\n\n"
                f"  Ação: enviar o arquivo {intent.file_name}\n"
                f"  Do computador: {intent.device_name}\n"
                "  Para: o seu Telegram vinculado\n\n"
                f"Código de aprovação: {code[:4]} {code[4:]}\n"
                "Vale 5 minutos e só para esta ação. Responda ao bot: /aprovar CÓDIGO\n\n"
                "Se não foi você, NÃO use o código e desvincule o Telegram no painel.\n"
            ),
        )
    except Exception:
        commands.cancel_request(session_factory, command_id=intent.command_id)
        return Reply(chat_id, "Não consegui enviar o e-mail com o código. Tente de novo.")
    return Reply(
        chat_id,
        f"📧 Enviei um código para o seu e-mail para aprovar o envio de {intent.file_name} "
        f"do {intent.device_name}. Responda aqui: /aprovar CÓDIGO (vale 5 minutos).",
    )


def _approve(
    chat_id: int, user_id: Any, argument: str, session_factory: SessionFactory, actions: ActionDeps
) -> Reply:
    try:
        command = commands.approve(session_factory, actions.key, user_id=user_id, code=argument)
    except commands.CommandError as error:
        return Reply(chat_id, error.message)
    return Reply(
        chat_id,
        f"✅ Aprovado. O computador vai enviar {command.file_name} em até 1 minuto.",
    )
