import uuid
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

import pytest
from pydantic import SecretStr

from app.auth.email_verification_delivery import (
    DeliveryIntent,
    SmtpEmailVerificationDeliveryAdapter,
)
from app.db.enums import EmailVerificationMaterialType as Material


def test_smtp_adapter_uses_starttls_and_builds_link_from_configured_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    class FakeSmtp:
        def __init__(self, host: str, port: int, *, timeout: float) -> None:
            calls.append(("connect", (host, port, timeout)))

        def __enter__(self) -> "FakeSmtp":
            return self

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            calls.append(("close", None))

        def ehlo(self) -> None:
            calls.append(("ehlo", None))

        def starttls(self, *, context: object) -> None:
            calls.append(("starttls", context))

        def login(self, username: str, password: str) -> None:
            calls.append(("login", username))

        def send_message(self, message: Any) -> None:
            calls.append(("message", message))

    monkeypatch.setattr("app.auth.email_verification_delivery.smtplib.SMTP", FakeSmtp)
    adapter = SmtpEmailVerificationDeliveryAdapter(
        host="smtp.example.test",
        port=587,
        sender="sender@example.test",
        public_origin="https://verify.example.test",
        username="user",
        password=SecretStr("smtp-password"),
        timeout_seconds=5.0,
    )
    token = "x" * 43
    recipient = "recipient@example.test"
    adapter.deliver(
        DeliveryIntent(
            recipient=recipient,
            challenge_id=uuid.uuid4(),
            expires_at=datetime(2030, 1, 1, tzinfo=UTC),
            material_type=Material.LINK,
            material=SecretStr(token),
        )
    )

    message = next(value for name, value in calls if name == "message")
    assert isinstance(message, EmailMessage)
    assert "starttls" in [name for name, _ in calls]
    assert "login" in [name for name, _ in calls]
    assert token in message.get_content()
    assert "https://verify.example.test/email-verification#token=" in message.get_content()
    assert token not in repr(adapter)
    assert recipient not in repr(adapter)
