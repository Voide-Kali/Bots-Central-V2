"""Command handling for linked and unlinked private chats.

Every reply is plain text. Unlinked chats only learn how to link; they never
see whether a code, user, or device exists.

Buttons are inline keyboards under the message (Kali-Bunker style): a button
press goes through exactly the same private-chat and linked-account checks as a
typed command. There is no persistent bottom keyboard.
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
from app.auth import action_pin, device_online
from app.auth.abuse_control import AbuseControlKey, AbuseControlUnavailable
from app.db.models import Device
from app.devices import commands, telemetry
from app.telegram import intents, linking
from app.telegram.formatting import device_card, device_line

SessionFactory = Callable[[], Session]

HELP = (
    "Escreva do seu jeito e o Aval entende:\n"
    "- qual computador esta mais quente? (a IA responde)\n"
    "- bloqueia o Mac / tira uma foto do servidor\n"
    "- manda o relatorio.pdf do Mac\n\n"
    "Toda acao pede o seu PIN (crie no painel do Aval). Sem PIN, o codigo vai por e-mail.\n\n"
    "Comandos: /painel (menu) /computadores /historico /bloquear PC /foto PC "
    "/enviar PC arquivo /desvincular /ajuda"
)
NOT_LINKED = (
    "Este chat nao esta vinculado.\n"
    "No painel do Aval, gere um codigo em Vincular Telegram e envie aqui:\n"
    "/vincular SEU-CODIGO"
)


class LinkAdmission(Protocol):
    def admit_telegram_link(self, *, chat_id: int) -> bool: ...

    def admit_assistant(self, *, chat_id: int) -> bool: ...

    def admit_telegram_action(self, *, chat_id: int) -> bool: ...


@dataclass(frozen=True)
class Reply:
    chat_id: int
    text: str
    keyboard: dict[str, Any] | None = None
    callback_id: str | None = None
    delete_message_id: int | None = None  # e.g. the owner's PIN message
    edit_message_id: int | None = None  # navigation buttons update their own message
    remove_reply_keyboard: bool = False  # clear the old persistent bottom keyboard once


# Labels of the computers screen (the old "Painel"). "Painel" is now the button menu.
MENU_PANEL = "Computadores"
MENU_AI = "IA"
MENU_HISTORY = "Histórico"
MENU_FILE = "Arquivo"
MENU_HELP = "Ajuda"

PANEL_TEXT = "Painel do Aval"

# Main menu: inline buttons under the message, Kali-Bunker style, two per row, no emojis.
def _menu_button(text: str, data: str) -> dict[str, str]:
    return {"text": text, "callback_data": data}


MAIN_MENU: dict[str, Any] = {
    "inline_keyboard": [
        [_menu_button(MENU_PANEL, "menu:status"), _menu_button(MENU_AI, "menu:ia")],
        [_menu_button(MENU_HISTORY, "menu:hist"), _menu_button(MENU_FILE, "menu:arquivo")],
        [_menu_button(MENU_HELP, "menu:help")],
    ]
}
# A message carrying this clears any leftover persistent keyboard from older bot versions.
REMOVE_KEYBOARD: dict[str, Any] = {"remove_keyboard": True}
BACK_BUTTON = {"text": "Voltar", "callback_data": "menu:home"}

# Typed labels still work as shortcuts (and old emoji buttons map after their glyph is stripped).
MENU_ALIASES = {
    "Painel": "/painel",
    "Menu": "/painel",
    MENU_PANEL: "/computadores",
    MENU_AI: "/ia",
    MENU_HISTORY: "/historico",
    MENU_HELP: "/ajuda",
    MENU_FILE: "/arquivo",
}
ACTION_BUTTONS = {"lock": "lock_screen", "photo": "webcam_photo"}
CALLBACKS = {
    "menu:home": "/painel",
    "menu:status": "/computadores",
    "menu:ia": "/ia",
    "menu:hist": "/historico",
    "menu:arquivo": "/arquivo",
    "menu:help": "/ajuda",
}
AI_HINT = (
    "Escreva sua pergunta em texto livre, por exemplo:\n"
    "- qual computador está mais quente?\n"
    "- quanto de memória o Mac está usando?\n"
    "- algum computador está offline?\n\n"
    "A IA só lê os dados dos seus computadores. Ela não consegue executar nada."
)
FILE_HINT = (
    "Para receber um arquivo de um computador:\n"
    "1. Coloque o arquivo na pasta compartilhada do computador "
    "(Mac: ~/Aval-Compartilhado, Linux: /srv/aval-compartilhado).\n"
    "2. Escreva aqui, por exemplo: manda o relatorio.pdf do Mac\n"
    "3. Confirme com o seu PIN.\n\n"
    "Sem a sua confirmação, nenhum arquivo sai do computador."
)


def _button(text: str, data: str) -> dict[str, str]:
    return {"text": text[:60], "callback_data": data}


def _private_message(
    update: dict[str, Any],
) -> tuple[int, int, str, str | None, int | None] | None:
    """(chat_id, user_id, text, callback_id, message_id) for a message or a button press."""
    callback_id: str | None = None
    message_id: int | None = None
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
        raw_message_id = message.get("message_id")
        message_id = raw_message_id if isinstance(raw_message_id, int) else None
    else:
        message = update.get("message")
        if not isinstance(message, dict):
            return None
        chat = message.get("chat")
        sender = message.get("from")
        body = message.get("text")
        raw_message_id = message.get("message_id")
        message_id = raw_message_id if isinstance(raw_message_id, int) else None
    if not isinstance(chat, dict) or not isinstance(sender, dict) or not isinstance(body, str):
        return None
    if chat.get("type") != "private" or sender.get("is_bot") is True:
        return None
    chat_id, user_id = chat.get("id"), sender.get("id")
    if not isinstance(chat_id, int) or not isinstance(user_id, int) or chat_id != user_id:
        return None
    stripped = body.strip()
    # Old keyboards prefixed labels with an emoji (e.g. "[chart] Painel"); drop any leading
    # non-letters so a tap on a leftover button still maps to the right command.
    label = stripped
    while label and not (label[0].isalnum() or label[0] == "/"):
        label = label[1:]
    label = label.strip()
    body = MENU_ALIASES.get(stripped, MENU_ALIASES.get(label, body))
    return chat_id, user_id, body[:512], callback_id, message_id


def _callback_command(data: str) -> str | None:
    if data in CALLBACKS:
        return CALLBACKS[data]
    if data.startswith("dev:"):
        try:
            return f"/pc {uuid.UUID(data[4:])}"
        except ValueError:
            return None
    if data.startswith("act:"):
        _, _, rest = data.partition(":")
        button, _, raw_id = rest.partition(":")
        if button in ACTION_BUTTONS:
            try:
                return f"/_acao {ACTION_BUTTONS[button]} {uuid.UUID(raw_id)}"
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
    active = sum(1 for item in devices if item.lifecycle_status.value == "active")
    waiting = sum(1 for item in devices if item.lifecycle_status.value == "pending")
    safe = online == active and waiting == 0
    header = (
        f"AVAL — {'PROTEGIDO' if safe else 'ATENÇÃO'}\n"
        f"Computadores online: {online} de {active}"
        + (f"\nAguardando aprovação no painel: {waiting}" if waiting else "")
    )
    lines = [
        device_line(item, presence, latest.get(item.id))
        for item, presence in zip(devices, presences, strict=True)
    ]
    return header + "\n\n" + "\n\n".join(lines)


def status_keyboard(session: Session, user_id: Any) -> dict[str, Any]:
    _, devices = _user_devices(session, user_id)
    rows = [[_button(f"{item.name}", f"dev:{item.id}")] for item in devices[:20]]
    rows.append([_button("Atualizar", "menu:status"), _button("Histórico", "menu:hist")])
    rows.append([BACK_BUTTON])
    return {"inline_keyboard": rows}


def device_reply(session: Session, user_id: Any, chat_id: int, raw_id: str) -> Reply:
    """The card of one of the owner's computers, by id (buttons) or by name (/pc tropa)."""
    now, devices = _user_devices(session, user_id)
    try:
        device_id = uuid.UUID(raw_id)
        device = next((item for item in devices if item.id == device_id), None)
    except ValueError:
        wanted = raw_id.strip().casefold()
        device = next((item for item in devices if item.name.casefold() == wanted), None)
    if device is None:  # never reveal other users' devices
        return Reply(chat_id, "Computador não encontrado.")
    sample = telemetry.latest_for_devices(session, [device.id]).get(device.id)
    card = device_card(device, device_online.presence(now, device), sample, now)
    rows: list[list[dict[str, str]]] = []
    if device.lifecycle_status.value == "active":
        rows.append(
            [
                _button("Bloquear tela", f"act:lock:{device.id}"),
                _button("Foto", f"act:photo:{device.id}"),
            ]
        )
    rows.append(
        [
            _button("Atualizar", f"dev:{device.id}"),
            _button("Voltar", "menu:status"),
        ]
    )
    return Reply(chat_id, card, {"inline_keyboard": rows})


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
    chat_id, telegram_user_id, body, callback_id, message_id = parsed
    reply = _dispatch(chat_id, telegram_user_id, body, session_factory, admission, model, actions)
    if callback_id is not None:
        # Panel, card and history buttons redraw the same message instead of piling up
        # new ones; action buttons still answer with a new message.
        navigation = body.startswith(
            ("/painel", "/menu", "/computadores", "/status", "/pc ", "/historico",
             "/ia", "/arquivo", "/ajuda")
        )
        edit = message_id if navigation and reply.keyboard is not None else None
        return Reply(reply.chat_id, reply.text, reply.keyboard, callback_id, edit_message_id=edit)
    if reply.delete_message_id == -1:  # placeholder: delete the message just received
        return Reply(reply.chat_id, reply.text, reply.keyboard, None, message_id)
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
        return Reply(
            chat_id,
            "Chat vinculado à sua conta. Use /painel para abrir o menu.",
            REMOVE_KEYBOARD,
            remove_reply_keyboard=True,
        )

    with session_factory() as session:
        user_id = linking.linked_user_id(
            session, chat_id=chat_id, telegram_user_id=telegram_user_id
        )
        if user_id is None:
            return Reply(chat_id, NOT_LINKED)
        if name in {"/painel", "/menu", "/start"}:
            # The menu home: a button message, and it clears any old bottom keyboard.
            return Reply(chat_id, PANEL_TEXT, MAIN_MENU, remove_reply_keyboard=name == "/start")
        if name in {"/computadores", "/status"}:
            return Reply(chat_id, status_text(session, user_id), status_keyboard(session, user_id))
        if name == "/pc":
            return device_reply(session, user_id, chat_id, argument)
        device_names = [
            item.name
            for item in _user_devices(session, user_id)[1]
            if item.lifecycle_status.value == "active"
        ]
        if name == "/historico":
            rows = audit.list_for_user(session, user_id=user_id, limit=10)
            body_text = "\n".join(audit.label(row) for row in rows) or "Nenhuma ação registrada."
            return Reply(
                chat_id,
                "Últimas ações:\n" + body_text,
                {"inline_keyboard": [[BACK_BUTTON]]},
            )
    if name == "/ia":
        return Reply(chat_id, AI_HINT, {"inline_keyboard": [[BACK_BUTTON]]})
    if name == "/arquivo":
        return Reply(chat_id, FILE_HINT, {"inline_keyboard": [[BACK_BUTTON]]})
    if not body.startswith("/") and action_pin.looks_like_pin(body):
        return _pin_reply(chat_id, user_id, body, session_factory, actions)
    intent = None if body.startswith("/") else intents.parse(body, device_names)
    action_names = {"/enviar", "/aprovar", "/bloquear", "/foto", "/_acao"}
    if intent is None and not body.startswith("/"):
        return _ask(chat_id, user_id, body, session_factory, admission, model)
    if intent is not None or name in action_names:
        if actions is None:
            return Reply(chat_id, "Ações não estão ativadas neste servidor.")
        try:
            if not admission.admit_telegram_action(chat_id=chat_id):
                return Reply(chat_id, "Muitas tentativas. Aguarde alguns minutos.")
        except AbuseControlUnavailable:
            return Reply(chat_id, "Serviço indisponível no momento. Tente mais tarde.")
        if intent is not None:
            return _intent_reply(chat_id, user_id, intent, device_names, session_factory, actions)
        if name == "/aprovar":
            return _approve(chat_id, user_id, argument, session_factory, actions)
        if name == "/_acao":
            kind, _, raw_id = argument.partition(" ")
            try:
                target = uuid.UUID(raw_id)
            except ValueError:
                return Reply(chat_id, "Computador não encontrado.")
            return _start_action(chat_id, user_id, kind, session_factory, actions, device_id=target)
        if name in {"/bloquear", "/foto"}:
            if not argument:
                return Reply(chat_id, f"Use: {name} NOME-DO-PC")
            kind = "lock_screen" if name == "/bloquear" else "webcam_photo"
            return _start_action(
                chat_id, user_id, kind, session_factory, actions, device_name=argument
            )
        device_name, _, file_name = argument.partition(" ")
        if not device_name or not file_name.strip():
            return Reply(chat_id, "Use: /enviar NOME-DO-PC nome-do-arquivo.pdf")
        return _start_action(
            chat_id,
            user_id,
            "send_file",
            session_factory,
            actions,
            device_name=device_name,
            argument=file_name.strip(),
        )
    if name == "/desvincular":
        linking.unlink_chat(session_factory, chat_id=chat_id)
        return Reply(chat_id, "Chat desvinculado. Você não receberá mais alertas aqui.")
    return Reply(chat_id, HELP, {"inline_keyboard": [[BACK_BUTTON]]})


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
    return Reply(chat_id, text_reply)


def _intent_reply(
    chat_id: int,
    user_id: Any,
    intent: intents.Intent,
    device_names: list[str],
    session_factory: SessionFactory,
    actions: ActionDeps,
) -> Reply:
    device = intent.device_hint
    if device is None and len(device_names) == 1:
        device = device_names[0]
    if device is None:
        return Reply(
            chat_id,
            "Em qual computador? Diga o nome, por exemplo: “bloqueia o "
            + (device_names[0] if device_names else "Mac")
            + "”.",
        )
    return _start_action(
        chat_id,
        user_id,
        intent.kind,
        session_factory,
        actions,
        device_name=device,
        argument=intent.argument,
    )


def _what(kind: str, argument: str) -> str:
    if kind == "send_file":
        return f"enviar o arquivo {argument}"
    return commands.ACTIONS[kind].verb


def _start_action(
    chat_id: int,
    user_id: Any,
    kind: str,
    session_factory: SessionFactory,
    actions: ActionDeps,
    *,
    device_name: str | None = None,
    device_id: uuid.UUID | None = None,
    argument: str = "",
) -> Reply:
    if kind == "send_file" and not commands.valid_file_name(argument):
        return Reply(chat_id, commands.InvalidFileName.message)
    with session_factory() as session:
        has_pin, _ = action_pin.status(session, user_id)
    try:
        intent = commands.request_action(
            session_factory,
            actions.key,
            user_id=user_id,
            chat_id=chat_id,
            kind=kind,
            device_name=device_name,
            device_id=device_id,
            argument=argument,
            by_pin=has_pin,
        )
    except commands.CommandError as error:
        return Reply(chat_id, error.message)
    what = _what(kind, argument)
    where = ("do " if kind == "send_file" else "no ") + intent.device_name
    if has_pin:
        return Reply(
            chat_id,
            f"Para {what} {where}, digite seu PIN (6 números).\n"
            "Vale 5 minutos. A mensagem com o PIN é apagada em seguida.",
        )
    subject, body = commands.approval_email(intent)
    try:
        actions.mailer.send_plain(recipient=intent.recipient, subject=subject, body=body)
    except Exception:
        commands.cancel_request(session_factory, command_id=intent.command_id)
        return Reply(chat_id, "Não consegui enviar o e-mail com o código. Tente de novo.")
    return Reply(
        chat_id,
        f"Enviei um código para o seu e-mail para {what} {where}. "
        "Responda aqui: /aprovar CÓDIGO (vale 5 minutos).\n"
        "Dica: crie um PIN no painel do Aval para aprovar sem e-mail.",
    )


def _pin_reply(
    chat_id: int,
    user_id: Any,
    pin: str,
    session_factory: SessionFactory,
    actions: ActionDeps | None,
) -> Reply:
    if actions is None:
        return Reply(chat_id, "Ações não estão ativadas neste servidor.", delete_message_id=-1)
    command, check = commands.approve_with_pin(
        session_factory, actions.key, user_id=user_id, pin=pin
    )
    if command is not None:
        what = _what(command.kind, command.file_name)
        return Reply(
            chat_id,
            f"Aprovado: {what}. O computador faz isso em até 1 minuto.",
            delete_message_id=-1,
        )
    if check.locked_until is not None:
        return Reply(
            chat_id,
            "PIN errado demais vezes. As ações ficam travadas por 15 minutos.",
            delete_message_id=-1,
        )
    if check.remaining:
        return Reply(
            chat_id,
            f"PIN incorreto. Restam {check.remaining} tentativas.",
            delete_message_id=-1,
        )
    return Reply(chat_id, "Nenhum pedido esperando PIN agora.", delete_message_id=-1)


def _approve(
    chat_id: int, user_id: Any, argument: str, session_factory: SessionFactory, actions: ActionDeps
) -> Reply:
    try:
        command = commands.approve(session_factory, actions.key, user_id=user_id, code=argument)
    except commands.CommandError as error:
        return Reply(chat_id, error.message)
    return Reply(
        chat_id,
        f"Aprovado. O computador vai enviar {command.file_name} em até 1 minuto.",
    )
