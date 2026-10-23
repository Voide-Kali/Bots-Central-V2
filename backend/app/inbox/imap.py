"""Read-only IMAP provider (ADR-024). Works with Gmail using an app password (no OAuth).

The mailbox is opened in read-only mode (EXAMINE, readonly=True), so looking at a message
never sets the \\Seen flag: the owner's own unread state is left exactly as it was. Only
headers and a bounded text snippet are read, in memory; nothing is written back to the server
and nothing but the opaque Message-ID is stored.
"""

import email
import hashlib
import imaplib
from email.message import Message
from email.utils import parseaddr

from app.inbox.inbox import MAX_SNIPPET_CHARS, EmailMessage

RECENT_COUNT = 15  # how many of the newest messages to look at per poll
MAX_FETCH_BYTES = 256 * 1024  # cap on the raw message pulled per e-mail


def _snippet(message: Message) -> str:
    """The first text/plain part, as a bounded preview. Attachments are ignored."""
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, "replace")[:MAX_SNIPPET_CHARS]
        return ""
    payload = message.get_payload(decode=True)
    if isinstance(payload, bytes):
        charset = message.get_content_charset() or "utf-8"
        return payload.decode(charset, "replace")[:MAX_SNIPPET_CHARS]
    return ""


def parse_message(raw: bytes) -> EmailMessage:
    """Turn a raw RFC822 message into an EmailMessage. Pure and testable."""
    message = email.message_from_bytes(raw)
    message_id = (message.get("Message-ID") or "").strip()
    if not message_id:
        # No Message-ID: derive a stable opaque id from headers so dedup still works.
        basis = (message.get("Date", "") + message.get("From", "") + message.get("Subject", ""))
        message_id = "sha256:" + hashlib.sha256(basis.encode("utf-8", "replace")).hexdigest()
    sender = parseaddr(message.get("From", ""))[1] or (message.get("From", "") or "")
    subject = str(message.get("Subject", "") or "")
    return EmailMessage(
        message_id=message_id[:255],
        sender=sender,
        subject=subject,
        snippet=_snippet(message),
    )


class ImapProvider:
    """Reads the newest messages from one IMAP mailbox, read-only."""

    def __init__(self, host: str, user: str, password: str, *, port: int = 993) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password

    def fetch_recent(self, account: str) -> list[EmailMessage]:
        connection = imaplib.IMAP4_SSL(self._host, self._port)
        try:
            connection.login(self._user, self._password)
            # readonly=True opens the mailbox with EXAMINE: fetching never sets \Seen.
            status, _ = connection.select("INBOX", readonly=True)
            if status != "OK":
                return []
            status, data = connection.search(None, "ALL")
            if status != "OK" or not data or not data[0]:
                return []
            numbers = data[0].split()[-RECENT_COUNT:]
            messages: list[EmailMessage] = []
            for number in numbers:
                status, fetched = connection.fetch(number, "(BODY.PEEK[])")
                if status != "OK" or not fetched:
                    continue
                raw = next(
                    (
                        part[1]
                        for part in fetched
                        if isinstance(part, tuple) and isinstance(part[1], bytes)
                    ),
                    None,
                )
                if raw is not None:
                    messages.append(parse_message(raw[:MAX_FETCH_BYTES]))
            return messages
        finally:
            try:
                connection.logout()
            except (imaplib.IMAP4.error, OSError):
                pass
