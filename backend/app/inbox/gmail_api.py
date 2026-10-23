"""Read-only Gmail provider via the Gmail API (ADR-024).

A trimmed port of the Kali-Bunker Gmail client, reshaped as a MailProvider
(see inbox.py). It authenticates with an already-authorized OAuth token whose
scope is ``gmail.readonly``, so it can only LOOK: it lists the newest unread
INBOX messages and reads their headers and a bounded text body, in memory. It
never sends, deletes or marks anything, and only the opaque message id is ever
persisted (inbox.py records it so an e-mail is announced once). Which senders or
subjects are worth announcing is decided centrally by EmailFilter, not here.

The google libraries are imported lazily inside ``build_service`` so the lean
backend and its tests never depend on them unless Gmail notices are configured
(install the optional ``gmail`` extra on the host that runs the bot).
"""

import base64
import html
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.inbox.inbox import MAX_SNIPPET_CHARS, EmailMessage

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
RECENT_SCAN_LIMIT = 100  # how many of the newest messages to page through per poll

ServiceBuilder = Callable[[str, int], Any]


class GmailUnavailable(RuntimeError):
    """Gmail is not usable (libraries missing, or the OAuth token is gone/invalid)."""


def _decode_part(part: dict[str, Any]) -> str:
    data = part.get("body", {}).get("data", "")
    if not isinstance(data, str) or not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data).decode("utf-8", "ignore")
    except (ValueError, TypeError):
        return ""


def extract_body(payload: dict[str, Any]) -> str:
    """The first text/plain part, falling back to stripped HTML. Attachments are ignored."""
    body = ""
    html_body = ""
    parts = payload.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if not isinstance(part, dict):
                continue
            mime = part.get("mimeType", "")
            if mime == "text/plain":
                body = _decode_part(part)
                if body:
                    break
            elif mime == "text/html":
                html_body = html_body or _decode_part(part)
            elif isinstance(part.get("parts"), list):
                body = extract_body(part)
                if body:
                    break
    else:
        body = _decode_part(payload)
    if body:
        return body.strip()
    if html_body:
        text = html.unescape(re.sub(r"<[^>]+>", " ", html_body))
        return re.sub(r"\s+", " ", text).strip()
    return ""


def message_to_email(detail: dict[str, Any]) -> EmailMessage:
    """Map one Gmail API message (format=full) to an EmailMessage. Pure and testable."""
    payload = detail.get("payload", {})
    payload = payload if isinstance(payload, dict) else {}
    headers_raw = payload.get("headers", [])
    headers = {
        str(item.get("name", "")): str(item.get("value", ""))
        for item in headers_raw
        if isinstance(item, dict)
    }
    body = extract_body(payload) or str(detail.get("snippet", ""))
    return EmailMessage(
        message_id=str(detail.get("id", ""))[:255],
        sender=headers.get("From", ""),
        subject=headers.get("Subject", ""),
        snippet=body[:MAX_SNIPPET_CHARS],
    )


def build_service(token_file: str, timeout_seconds: int) -> Any:
    """Build a read-only Gmail client from an already-authorized token (non-interactive).

    Reuses a token.json produced by the OAuth consent flow (the same file the old
    Kali-Bunker bot used). A token write-back after refresh is best-effort, so a
    read-only mount still works for the access token's lifetime.
    """
    try:
        import httplib2
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_httplib2 import AuthorizedHttp
        from googleapiclient.discovery import build
    except ImportError as exc:  # the optional "gmail" extra is not installed
        raise GmailUnavailable("gmail libraries not installed (install the 'gmail' extra)") from exc

    token_path = Path(token_file)
    if not token_path.exists():
        raise GmailUnavailable(f"OAuth token missing: {token_file}")
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            try:
                token_path.write_text(creds.to_json(), encoding="utf-8")
                token_path.chmod(0o600)
            except OSError:
                logger.info("could not persist refreshed gmail token (read-only mount?)")
        else:
            raise GmailUnavailable("OAuth token invalid or expired without a refresh token")
    http = AuthorizedHttp(creds, http=httplib2.Http(timeout=max(3, timeout_seconds)))
    return build("gmail", "v1", http=http, cache_discovery=False)


def _list_unread_ids(service: Any, *, max_results: int, scan_limit: int) -> list[str]:
    """Ids of the newest unread INBOX messages, paging without downloading the whole box."""
    wanted = max(1, max_results)
    remaining = max(wanted, scan_limit)
    ids: list[str] = []
    page_token: str | None = None
    while len(ids) < wanted and remaining > 0:
        args: dict[str, Any] = {
            "userId": "me",
            "labelIds": ["INBOX", "UNREAD"],
            "maxResults": min(100, remaining),
        }
        if page_token:
            args["pageToken"] = page_token
        result = service.users().messages().list(**args).execute()
        page = result.get("messages", []) or []
        remaining -= len(page)
        for message in page:
            message_id = str(message.get("id", ""))
            if message_id:
                ids.append(message_id)
                if len(ids) >= wanted:
                    break
        page_token = result.get("nextPageToken")
        if not page_token or not page:
            break
    return ids


class GmailApiProvider:
    """A MailProvider backed by the Gmail API (read-only).

    The google client is built lazily and cached; any failure drops the cache so the
    next poll rebuilds it (covering a token refresh or a transient network blip). A
    poll never raises into the bot loop: on error it logs and returns no messages.
    """

    def __init__(
        self,
        *,
        token_file: str,
        timeout_seconds: int = 12,
        max_results: int = 5,
        scan_limit: int = RECENT_SCAN_LIMIT,
        service_builder: ServiceBuilder = build_service,
    ) -> None:
        self._token_file = token_file
        self._timeout = timeout_seconds
        self._max_results = max_results
        self._scan_limit = scan_limit
        self._build = service_builder
        self._service: Any | None = None

    def _ensure_service(self) -> Any:
        if self._service is None:
            self._service = self._build(self._token_file, self._timeout)
        return self._service

    def fetch_recent(self, account: str) -> list[EmailMessage]:
        try:
            service = self._ensure_service()
            ids = _list_unread_ids(
                service, max_results=self._max_results, scan_limit=self._scan_limit
            )
            messages: list[EmailMessage] = []
            for message_id in ids:
                detail = (
                    service.users()
                    .messages()
                    .get(userId="me", id=message_id, format="full")
                    .execute()
                )
                message = message_to_email(detail)
                if message.message_id:
                    messages.append(message)
            return messages
        except Exception:
            # Never let a mailbox hiccup take down the bot's alert loop; retry next pass.
            self._service = None
            logger.warning("gmail fetch failed for %s; retrying next pass", account, exc_info=True)
            return []
