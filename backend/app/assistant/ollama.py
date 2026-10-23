"""Tiny Ollama chat client on the standard library."""

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit


class AssistantUnavailable(Exception):
    pass


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout_seconds: float = 45.0,
        keep_alive: str = "30m",
        num_predict: int = 256,
    ) -> None:
        parts = urlsplit(base_url)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.path not in {"", "/"}
        ):
            raise ValueError("invalid Ollama base URL")
        self._url = f"{parts.scheme}://{parts.netloc}/api/chat"
        self._model = model
        self._timeout = timeout_seconds
        # keep_alive keeps the model loaded between questions, so an occasional question does
        # not pay the cold reload. num_predict caps the answer length (shorter = faster on CPU).
        self._keep_alive = keep_alive
        self._num_predict = num_predict

    def chat(self, messages: list[dict[str, str]]) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "keep_alive": self._keep_alive,
            "options": {"temperature": 0.2, "num_predict": self._num_predict},
        }
        request = urllib.request.Request(
            self._url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                data = json.loads(response.read(1 << 20))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise AssistantUnavailable from None
        message = data.get("message") if isinstance(data, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise AssistantUnavailable
        return content.strip()
