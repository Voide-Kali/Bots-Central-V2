"""Minimal Telegram Bot API client on the standard library (no new dependencies).

The bot token is part of every API URL, so errors never include the URL or the
underlying exception text; callers only see ``TelegramUnavailable``.
"""

import json
import secrets
import ssl
import urllib.error
import urllib.request
from typing import Any

from pydantic import SecretStr

API_BASE = "https://api.telegram.org"
MAX_MESSAGE_CHARS = 4000


class TelegramUnavailable(Exception):
    pass


class TelegramClient:
    def __init__(self, token: SecretStr, *, timeout_seconds: float = 35.0) -> None:
        raw = token.get_secret_value()
        if not raw or any(ch.isspace() or ch == "/" for ch in raw):
            raise ValueError("invalid Telegram bot token")
        self._token = token
        self._timeout = timeout_seconds
        self._context = ssl.create_default_context()

    def _call(self, method: str, payload: dict[str, Any]) -> Any:
        url = f"{API_BASE}/bot{self._token.get_secret_value()}/{method}"
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 - fixed https host
                request, timeout=self._timeout, context=self._context
            ) as response:
                data = json.loads(response.read(1 << 20))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise TelegramUnavailable from None
        if not isinstance(data, dict) or data.get("ok") is not True:
            raise TelegramUnavailable
        return data.get("result")

    def get_updates(self, *, offset: int | None, timeout: int = 25) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        result = self._call("getUpdates", payload)
        if not isinstance(result, list):
            raise TelegramUnavailable
        return [item for item in result if isinstance(item, dict)]

    def send_document(self, chat_id: int, file_name: str, content: bytes, caption: str) -> None:
        """Upload a file as multipart/form-data (Bot API limit is 50 MB; we cap at 10 MB)."""
        boundary = "aval" + secrets.token_hex(16)
        safe_name = file_name.replace('"', "'").replace("\r", "").replace("\n", "")
        parts = [
            (f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}').encode(),
            (
                'Content-Disposition: form-data; name="caption"\r\n\r\n'
                + caption[: MAX_MESSAGE_CHARS // 4]
            ).encode(),
            (
                f'Content-Disposition: form-data; name="document"; filename="{safe_name}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode()
            + content,
        ]
        body = b"".join(f"--{boundary}\r\n".encode() + part + b"\r\n" for part in parts)
        body += f"--{boundary}--\r\n".encode()
        url = f"{API_BASE}/bot{self._token.get_secret_value()}/sendDocument"
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 - fixed https host
                request, timeout=self._timeout * 4, context=self._context
            ) as response:
                data = json.loads(response.read(1 << 20))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise TelegramUnavailable from None
        if not isinstance(data, dict) or data.get("ok") is not True:
            raise TelegramUnavailable

    def send_message(self, chat_id: int, text: str) -> None:
        # Plain text only (no parse_mode): device names come from agents.
        self._call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text[:MAX_MESSAGE_CHARS],
                "disable_web_page_preview": True,
            },
        )
