"""Pure in-memory delivery contract for post-commit email-verification work."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from pydantic import SecretStr

from app.db.enums import EmailVerificationMaterialType


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
