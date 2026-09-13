import uuid
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from app.auth.email_verification_delivery import (
    DeliveryIntent,
    EmailVerificationDeliveryConfigurationError,
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


def test_smtp_adapter_preserves_default_verified_context_without_custom_ca(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeContext:
        check_hostname = True
        verify_mode = 2

        def load_verify_locations(self, *, cafile: str) -> None:
            calls.append(f"load:{cafile}")

    class FakeSmtp:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "FakeSmtp":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def ehlo(self) -> None:
            return None

        def starttls(self, *, context: FakeContext) -> None:
            assert context.check_hostname is True
            assert context.verify_mode == 2
            calls.append("starttls")

        def send_message(self, message: Any) -> None:
            return None

    monkeypatch.setattr(
        "app.auth.email_verification_delivery.ssl.create_default_context", FakeContext
    )
    monkeypatch.setattr("app.auth.email_verification_delivery.smtplib.SMTP", FakeSmtp)
    _adapter().deliver(_intent())

    assert calls == ["starttls"]


def test_smtp_adapter_adds_custom_ca_without_relaxing_tls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, object]] = []
    ca_file = tmp_path / "local-ca.pem"
    ca_file.write_text("placeholder", encoding="ascii")

    class FakeContext:
        check_hostname = True
        verify_mode = 2

        def load_verify_locations(self, *, cafile: str) -> None:
            calls.append(("load", cafile))

    class FakeSmtp:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "FakeSmtp":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def ehlo(self) -> None:
            return None

        def starttls(self, *, context: FakeContext) -> None:
            assert context.check_hostname is True
            assert context.verify_mode == 2
            calls.append(("starttls", context))

        def send_message(self, message: Any) -> None:
            return None

    monkeypatch.setattr(
        "app.auth.email_verification_delivery.ssl.create_default_context", FakeContext
    )
    monkeypatch.setattr("app.auth.email_verification_delivery.smtplib.SMTP", FakeSmtp)
    _adapter(ca_file=ca_file).deliver(_intent())

    assert calls[0] == ("load", str(ca_file))
    assert calls[1][0] == "starttls"


def test_smtp_adapter_rejects_unloadable_custom_ca_without_leaking_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sentinel = "CA-MATERIAL-MUST-NOT-LEAK"
    ca_file = tmp_path / sentinel

    class FakeContext:
        def load_verify_locations(self, *, cafile: str) -> None:
            raise OSError("unloadable")

    monkeypatch.setattr(
        "app.auth.email_verification_delivery.ssl.create_default_context", FakeContext
    )
    with pytest.raises(
        EmailVerificationDeliveryConfigurationError, match="SMTP CA file could not be loaded"
    ) as raised:
        _adapter(ca_file=ca_file).deliver(_intent())

    assert sentinel not in str(raised.value)
    assert sentinel not in repr(raised.value)


def _adapter(*, ca_file: Path | None = None) -> SmtpEmailVerificationDeliveryAdapter:
    return SmtpEmailVerificationDeliveryAdapter(
        host="smtp.example.test",
        port=587,
        sender="sender@example.test",
        public_origin="https://verify.example.test",
        username=None,
        password=None,
        timeout_seconds=5.0,
        ca_file=ca_file,
    )


def _intent() -> DeliveryIntent:
    return DeliveryIntent(
        recipient="recipient@example.test",
        challenge_id=uuid.uuid4(),
        expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        material_type=Material.LINK,
        material=SecretStr("x" * 43),
    )
