"""Pure in-memory delivery contract for post-commit email-verification work."""

import smtplib
import ssl
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol

from pydantic import SecretStr

from app.db.enums import EmailVerificationMaterialType


class EmailVerificationDeliveryConfigurationError(ValueError):
    """Raised when an SMTP delivery adapter cannot be configured safely."""


@dataclass(frozen=True)
class DeliveryIntent:
    """ORM-free plaintext material that is valid only in process memory after commit."""

    recipient: str = field(repr=False)
    challenge_id: uuid.UUID
    expires_at: datetime
    material_type: EmailVerificationMaterialType
    material: SecretStr = field(repr=False)


class EmailVerificationDeliveryAdapter(Protocol):
    """Future adapters must make one call with automatic retries disabled."""

    def deliver(self, intent: DeliveryIntent) -> None: ...


class SmtpEmailVerificationDeliveryAdapter:
    """Single-attempt STARTTLS SMTP adapter with no provider retry behavior."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        sender: str,
        public_origin: str,
        username: str | None,
        password: SecretStr | None,
        timeout_seconds: float,
        ca_file: Path | None = None,
    ) -> None:
        if not host or not sender or not public_origin:
            raise EmailVerificationDeliveryConfigurationError("SMTP delivery is not configured")
        if username is not None and password is None:
            raise EmailVerificationDeliveryConfigurationError("SMTP credentials are incomplete")
        self._host = host
        self._port = port
        self._sender = sender
        self._public_origin = public_origin
        self._username = username
        self._password = password
        self._timeout_seconds = timeout_seconds
        self._ca_file = ca_file

    @classmethod
    def from_settings(cls, settings: object) -> "SmtpEmailVerificationDeliveryAdapter":
        host = getattr(settings, "smtp_host", None)
        port = getattr(settings, "smtp_port", None)
        sender = getattr(settings, "smtp_sender", None)
        public_origin = getattr(settings, "public_origin", None)
        username = getattr(settings, "smtp_username", None)
        password = getattr(settings, "smtp_password", None)
        timeout_seconds = getattr(settings, "smtp_timeout_seconds", None)
        ca_file = getattr(settings, "smtp_ca_file", None)
        if (
            not isinstance(host, str)
            or not isinstance(port, int)
            or not isinstance(sender, str)
            or not isinstance(public_origin, str)
            or not isinstance(username, str | None)
            or not isinstance(password, SecretStr | None)
            or not isinstance(timeout_seconds, float)
            or not isinstance(ca_file, Path | None)
        ):
            raise EmailVerificationDeliveryConfigurationError("SMTP delivery is not configured")
        return cls(
            host=host,
            port=port,
            sender=sender,
            public_origin=public_origin,
            username=username,
            password=password,
            timeout_seconds=timeout_seconds,
            ca_file=ca_file,
        )

    def _message(self, intent: DeliveryIntent) -> EmailMessage:
        material = intent.material.get_secret_value()
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = intent.recipient
        message["Subject"] = "Email verification"
        if intent.material_type is EmailVerificationMaterialType.LINK:
            message.set_content(
                "Open this verification page and confirm explicitly:\n\n"
                f"{self._public_origin}/email-verification#token={material}\n"
            )
        else:
            message.set_content(
                "Enter this email verification code with its challenge in the verification "
                "page:\n\n"
                f"Challenge ID: {intent.challenge_id}\nCode: {material[:4]} {material[4:]}\n"
            )
        return message

    def deliver(self, intent: DeliveryIntent) -> None:
        self._send(self._message(intent))

    def send_plain(self, *, recipient: str, subject: str, body: str) -> None:
        """Single-attempt plain-text email through the same STARTTLS configuration."""
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        self._send(message)

    def _send(self, message: EmailMessage) -> None:
        context = ssl.create_default_context()
        if self._ca_file is not None:
            try:
                context.load_verify_locations(cafile=str(self._ca_file))
            except (OSError, ssl.SSLError) as error:
                raise EmailVerificationDeliveryConfigurationError(
                    "SMTP CA file could not be loaded"
                ) from error
        with smtplib.SMTP(self._host, self._port, timeout=self._timeout_seconds) as client:
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
            if self._username is not None and self._password is not None:
                client.login(self._username, self._password.get_secret_value())
            client.send_message(message)

    def __repr__(self) -> str:
        return "SmtpEmailVerificationDeliveryAdapter(configured=True)"


@dataclass(frozen=True)
class DeliveryDispatched:
    pass


@dataclass(frozen=True)
class DeliveryFailed:
    """Sanitized failure: no provider error, recipient, or material is retained."""


DeliveryDispatchOutcome = DeliveryDispatched | DeliveryFailed


def dispatch_delivery(
    adapter: EmailVerificationDeliveryAdapter, intent: DeliveryIntent
) -> DeliveryDispatchOutcome:
    """Attempt delivery once, without retrying or exposing adapter failures."""
    try:
        adapter.deliver(intent)
    except Exception:
        return DeliveryFailed()
    return DeliveryDispatched()
