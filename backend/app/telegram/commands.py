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

from app.assistant import assistant
from app.assistant.ollama import AssistantUnavailable
from app.audit import events as audit
from app.auth import device_online
from app.auth.abuse_control import AbuseControlKey, AbuseControlUnavailable
from app.db.models import Device
from app.devices import commands, telemetry
from app.telegram import linking
from app.telegram.formatting import device_line

SessionFactory = Callable[[], Session]

HELP = (
    "Pergunte em texto livre (ex.: “qual PC está mais quente?”) e a IA responde.\n\n"
    "Comandos:\n"
    "/status — estado e telemetria dos seus dispositivos\n"
    "/historico — últimas ações na sua conta\n"
    "/enviar PC arquivo — pede um arquivo da pasta compartilhada (código no e-mail)\n"
    "/aprovar 12345678 — confirma o pedido com o código do e-mail\n"
    "/desvincular — desliga este chat da sua conta\n"
    "/menu — abre os botões do Aval\n"
    "/ajuda — esta mensagem"
)
MENU_KEYBOARD = [
    [{"text": "💻 Computadores", "callback_data": "menu:status"}],
    [
        {"text": "📜 Histórico", "callback_data": "menu:history"},
        {"text": "📤 Enviar arquivo", "callback_data": "menu:send"},
    ],
    [
        {"text": "❔ Ajuda", "callback_data": "menu:help"},
        {"text": "⚙️ Conta", "callback_data": "menu:account"},
    ],
]
ACCOUNT_KEYBOARD = [
    [{"text": "🔌 Desvincular Telegram", "callback_data": "account:unlink"}],
    [{"text": "↩️ Voltar", "callback_data": "menu:home"}],
]
UNLINK_KEYBOARD = [[
    {"text": "✅ Sim, desvincular", "callback_data": "unlink:confirm"},
    {"text": "↩️ Cancelar", "callback_data": "unlink:cancel"},
]]
NOT_LINKED = (
    "Este chat não está vinculado.\n"
    "No painel do Bots Central, gere um código em “Vincular Telegram” e envie aqui:\n"
    "/vincular SEU-CODIGO"
)


class LinkAdmission(Protocol):
    def admit_telegram_link(self, *, chat_id: int) -> bool: ...

    def admit_assistant(self, *, chat_id: int) -> bool: ...


@dataclass(frozen=True)
class Reply:
    chat_id: int
    text: str
    inline_keyboard: list[list[dict[str, str]]] | None = None
    callback_query_id: str | None = None


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


def _private_callback(update: dict[str, Any]) -> tuple[str, int, int, str] | None:
    callback = update.get("callback_query")
    if not isinstance(callback, dict):
        return None
    message = callback.get("message")
    sender = callback.get("from")
    query_id = callback.get("id")
    data = callback.get("data")
    if not isinstance(message, dict) or not isinstance(sender, dict):
        return None
    chat = message.get("chat")
    chat_id = chat.get("id") if isinstance(chat, dict) else None
    user_id = sender.get("id")
    if (
        not isinstance(query_id, str)
        or not isinstance(data, str)
        or len(data) > 64
        or not isinstance(chat, dict)
        or chat.get("type") != "private"
        or not isinstance(chat_id, int)
        or not isinstance(user_id, int)
        or chat_id != user_id
        or sender.get("is_bot") is True
    ):
        return None
    return query_id, chat_id, user_id, data


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
    callback = _private_callback(update)
    if callback is not None:
        return _handle_callback(
            callback,
            session_factory=session_factory,
            actions=actions,
        )
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
        return Reply(
            chat_id,
            "✅ Chat vinculado à sua conta.\n\n" + HELP,
            inline_keyboard=MENU_KEYBOARD,
        )

    with session_factory() as session:
        user_id = linking.linked_user_id(
            session, chat_id=chat_id, telegram_user_id=telegram_user_id
        )
        if user_id is None:
            return Reply(chat_id, NOT_LINKED)
        if name in {"/start", "/menu"}:
            return Reply(chat_id, "🏠 Painel do Aval\nEscolha uma opção:", MENU_KEYBOARD)
        if name == "/status":
            return Reply(chat_id, status_text(session, user_id))
        if name == "/historico":
            rows = audit.list_for_user(session, user_id=user_id, limit=10)
            body_text = "\n".join(audit.label(row) for row in rows) or "Nenhuma ação registrada."
            return Reply(chat_id, "🧾 Últimas ações:\n" + body_text)
        if name == "/ajuda":
            return Reply(chat_id, HELP, MENU_KEYBOARD)
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
    return Reply(chat_id, HELP)


def _handle_callback(
    callback: tuple[str, int, int, str],
    *,
    session_factory: SessionFactory,
    actions: ActionDeps | None,
) -> Reply:
    query_id, chat_id, telegram_user_id, data = callback
    with session_factory() as session:
        user_id = linking.linked_user_id(
            session, chat_id=chat_id, telegram_user_id=telegram_user_id
        )
        if user_id is None:
            return Reply(chat_id, NOT_LINKED, callback_query_id=query_id)
        if data == "menu:home":
            return Reply(
                chat_id, "🏠 Painel do Aval\nEscolha uma opção:", MENU_KEYBOARD, query_id
            )
        if data == "menu:status":
            return Reply(
                chat_id, status_text(session, user_id), MENU_KEYBOARD, query_id
            )
        if data == "menu:history":
            rows = audit.list_for_user(session, user_id=user_id, limit=10)
            text_reply = "\n".join(audit.label(row) for row in rows) or "Nenhuma ação registrada."
            return Reply(chat_id, "🧾 Últimas ações:\n" + text_reply, MENU_KEYBOARD, query_id)
        if data == "menu:send":
            if actions is None:
                text_reply = "Envio de arquivo não está ativado neste servidor."
            else:
                text_reply = (
                    "📤 Para pedir um arquivo, envie:\n"
                    "/enviar NOME-DO-PC nome-do-arquivo.pdf\n\n"
                    "O pedido só é executado depois da aprovação pelo código enviado ao seu e-mail."
                )
            return Reply(chat_id, text_reply, MENU_KEYBOARD, query_id)
        if data == "menu:help":
            return Reply(chat_id, HELP, MENU_KEYBOARD, query_id)
        if data == "menu:account":
            return Reply(chat_id, "⚙️ Conta\nEscolha uma opção:", ACCOUNT_KEYBOARD, query_id)
        if data == "account:unlink":
            return Reply(
                chat_id,
                "Quer mesmo desvincular este Telegram? Alertas e pedidos em andamento "
                "serão cancelados.",
                UNLINK_KEYBOARD,
                query_id,
            )
        if data == "unlink:cancel":
            return Reply(
                chat_id, "Desvinculação cancelada.", MENU_KEYBOARD, query_id
            )
        if data == "unlink:confirm":
            linking.unlink_chat(session_factory, chat_id=chat_id)
            return Reply(
                chat_id,
                "🔌 Telegram desvinculado. Você não receberá mais alertas aqui.",
                callback_query_id=query_id,
            )
    return Reply(
        chat_id,
        "Esse botão expirou. Envie /menu para abrir o menu novamente.",
        callback_query_id=query_id,
    )


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
