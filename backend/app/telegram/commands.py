"""Command handling for linked and unlinked private chats.

Every reply is plain text. Unlinked chats only learn how to link; they never
see whether a code, user, or device exists.

Buttons are inline keyboards under the message (Kali-Bunker style): a button
press goes through exactly the same private-chat and linked-account checks as a
typed command. There is no persistent bottom keyboard.
"""

import unicodedata
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
    "Pode escrever do seu jeito que eu entendo:\n\n"
    "Exemplos:\n"
    "- bloqueia o Mac\n"
    "- tira uma foto do servidor\n"
    "- mostra quem ta na rede\n"
    "- suspende o Mac / reinicia o servidor / desliga o PC\n"
    "- manda o relatorio.pdf do Mac\n"
    "- qual computador esta mais quente? (a IA responde)\n\n"
    "Toda acao pede o seu PIN de 6 numeros. Se voce ainda nao criou, "
    "entre no painel do Aval e crie um na secao PIN.\n"
    "Sem PIN, o codigo vai por e-mail.\n\n"
    "Comandos diretos:\n"
    "/painel — menu principal\n"
    "/computadores — seus PCs\n"
    "/historico — acoes recentes\n"
    "/bloquear PC — bloqueia a tela\n"
    "/foto PC — foto pela webcam\n"
    "/scan PC — quem esta na rede\n"
    "/suspender PC · /reiniciar PC · /desligar PC\n"
    "/enviar PC arquivo — buscar um arquivo\n"
    "/desvincular — desvincular este chat"
)
NOT_LINKED = (
    "Este chat ainda nao esta vinculado a sua conta.\n\n"
    "Para vincular:\n"
    "1. Abra o painel do Aval no navegador\n"
    "2. Va em Vincular Telegram e gere um codigo\n"
    "3. Envie aqui: /vincular SEU-CODIGO\n\n"
    "Depois disso voce controla seus computadores por aqui."
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
ACTION_BUTTONS = {"lock": "lock_screen", "photo": "webcam_photo", "scan": "network_scan"}
# Power has no one-tap button on purpose: it is typed, so it cannot be hit by accident.
POWER_COMMANDS = {"/desligar": "shutdown", "/reiniciar": "reboot", "/suspender": "suspend"}
CALLBACKS = {
    "menu:home": "/painel",
    "menu:status": "/computadores",
    "menu:ia": "/ia",
    "menu:hist": "/historico",
    "menu:arquivo": "/arquivo",
    "menu:help": "/ajuda",
}
AI_HINT = (
    "Pode me perguntar qualquer coisa sobre os seus computadores.\n"
    "Escreva normalmente, por exemplo:\n\n"
    "- qual computador esta mais quente?\n"
    "- quanto de memoria o Mac esta usando?\n"
    "- algum computador esta offline?\n"
    "- esta tudo normal com os meus PCs?\n\n"
    "Eu leio os dados dos seus computadores e respondo. "
    "Nao consigo executar nenhuma acao — para isso, use os comandos."
)
FILE_HINT = (
    "Para receber um arquivo de um computador:\n\n"
    "1. Coloque o arquivo na pasta compartilhada do computador\n"
    "   Mac: ~/Aval-Compartilhado\n"
    "   Linux: /srv/aval-compartilhado\n\n"
    "2. Escreva aqui o que voce quer, por exemplo:\n"
    "   manda o relatorio.pdf do Mac\n"
    "   pega o backup.zip do servidor\n\n"
    "3. Confirme com o seu PIN de 6 numeros.\n\n"
    "Nenhum arquivo sai do computador sem a sua confirmacao."
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
        return (
            "Voce ainda nao tem computadores cadastrados.\n"
            "Para adicionar, instale o agente Aval no computador e faca o pareamento pelo painel."
        )
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
    status_word = "Tudo certo" if safe else "Atencao"
    header = (
        f"AVAL — {status_word}\n"
        f"{online} de {active} computador(es) online"
        + (f"\n{waiting} aguardando aprovacao no painel" if waiting else "")
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
        return Reply(chat_id, "Computador nao encontrado. Use /computadores para ver seus PCs.")
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
        rows.append([_button("Rede", f"act:scan:{device.id}")])
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
    conversations: assistant.Conversations | None = None,
) -> Reply | None:
    parsed = _private_message(update)
    if parsed is None:
        return None
    chat_id, telegram_user_id, body, callback_id, message_id = parsed
    reply = _dispatch(
        chat_id, telegram_user_id, body, session_factory, admission, model, actions, conversations
    )
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
    conversations: assistant.Conversations | None = None,
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
    action_names = {"/enviar", "/aprovar", "/bloquear", "/foto", "/scan", "/_acao", *POWER_COMMANDS}
    if intent is None and not body.startswith("/"):
        if _is_greeting(body):
            return Reply(chat_id, GREETING_REPLY, MAIN_MENU)
        return _ask(chat_id, user_id, body, session_factory, admission, model, conversations)
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
        if name in POWER_COMMANDS:
            if not argument:
                return Reply(chat_id, f"Use: {name} NOME-DO-PC")
            return _start_action(
                chat_id,
                user_id,
                "power",
                session_factory,
                actions,
                device_name=argument,
                argument=POWER_COMMANDS[name],
            )
        if name in {"/bloquear", "/foto", "/scan"}:
            if not argument:
                return Reply(chat_id, f"Use: {name} NOME-DO-PC")
            kind = {"/bloquear": "lock_screen", "/foto": "webcam_photo", "/scan": "network_scan"}[
                name
            ]
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
        if conversations is not None:
            conversations.forget(chat_id)
        return Reply(chat_id, "Chat desvinculado. Você não receberá mais alertas aqui.")
    return Reply(chat_id, HELP, {"inline_keyboard": [[BACK_BUTTON]]})


# A bare greeting does not need the language model: answering it instantly keeps the bot
# snappy and avoids loading the model (which is slow on CPU) just to say hello.
_GREETINGS = frozenset(
    {
        "oi", "ola", "opa", "eai", "e ai", "hey", "hello", "alo", "salve", "bom dia",
        "boa tarde", "boa noite", "tudo bem", "tudo bom", "blz", "beleza", "boa",
    }
)
GREETING_REPLY = (
    "Oi! Eu sou o Aval, cuido dos seus computadores.\n\n"
    "Pode me perguntar qualquer coisa ou pedir uma acao.\n"
    "Exemplos:\n"
    "- como esta o Mac?\n"
    "- bloqueia o servidor\n"
    "- tira uma foto do tropa\n\n"
    "Ou toque em /painel para ver o menu."
)


def _is_greeting(body: str) -> bool:
    decomposed = unicodedata.normalize("NFKD", body.lower())
    folded = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    kept = "".join(ch if ch.isalnum() else " " for ch in folded)
    text = " ".join(kept.split())
    return 0 < len(text) <= 20 and text in _GREETINGS


def _ask(
    chat_id: int,
    user_id: Any,
    question: str,
    session_factory: SessionFactory,
    admission: LinkAdmission,
    model: assistant.ChatModel | None,
    conversations: assistant.Conversations | None = None,
) -> Reply:
    if model is None:
        return Reply(chat_id, "A IA não está ativada neste servidor.\n\n" + HELP)
    try:
        if not admission.admit_assistant(chat_id=chat_id):
            return Reply(chat_id, "Muitas perguntas seguidas. Aguarde alguns minutos.")
    except AbuseControlUnavailable:
        return Reply(chat_id, "Serviço indisponível no momento. Tente mais tarde.")
    history = conversations.recent(chat_id) if conversations else None
    try:
        text_reply = assistant.answer(
            session_factory, model, user_id=user_id, question=question, history=history
        )
    except AssistantUnavailable:
        return Reply(chat_id, "A IA não respondeu a tempo. Tente de novo em instantes.")
    if conversations is not None:
        conversations.remember(chat_id, question, text_reply)
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
        example = device_names[0] if device_names else "Mac"
        return Reply(
            chat_id,
            f"Em qual computador? Diga o nome junto.\nExemplo: bloqueia o {example}",
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
    return commands.action_verb(kind, argument)


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
            f"Entendido: {what} {where}.\n"
            "Digite seu PIN de 6 numeros para confirmar.\n"
            "(Vale 5 minutos. A mensagem com o PIN e apagada em seguida.)",
        )
    subject, body = commands.approval_email(intent)
    try:
        actions.mailer.send_plain(recipient=intent.recipient, subject=subject, body=body)
    except Exception:
        commands.cancel_request(session_factory, command_id=intent.command_id)
        return Reply(chat_id, "Nao consegui enviar o e-mail com o codigo. Tente de novo.")
    return Reply(
        chat_id,
        f"Entendido: {what} {where}.\n"
        "Enviei um codigo para o seu e-mail. Responda aqui:\n"
        "/aprovar CODIGO\n\n"
        "(Vale 5 minutos. Dica: crie um PIN no painel para aprovar sem e-mail.)",
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
            f"Aprovado. O computador vai {what} em ate 1 minuto.",
            delete_message_id=-1,
        )
    if check.locked_until is not None:
        return Reply(
            chat_id,
            "PIN errado muitas vezes. As acoes ficam travadas por 15 minutos.\n"
            "Tente de novo depois.",
            delete_message_id=-1,
        )
    if check.remaining:
        return Reply(
            chat_id,
            f"PIN incorreto. Voce ainda tem {check.remaining} tentativa(s).",
            delete_message_id=-1,
        )
    return Reply(
        chat_id,
        "Nao tem nenhum pedido esperando PIN agora.\n"
        "Primeiro peca uma acao (ex: bloqueia o Mac), depois digite o PIN.",
        delete_message_id=-1,
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
        f"Aprovado. O computador vai enviar {command.file_name} em até 1 minuto.",
    )
