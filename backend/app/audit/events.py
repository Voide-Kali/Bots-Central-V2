"""Record audit events inside the caller's transaction (never on its own).

Writing in the same transaction as the action means an action and its audit row
commit or roll back together. Events never contain secrets: no tokens, codes,
passwords, keys or full IP addresses.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import AuditEvent

Actor = Literal["user", "device", "telegram", "system"]
Outcome = Literal["success", "denied", "failure"]

MAX_LIST = 100
_FORBIDDEN_DETAIL_KEYS = ("token", "code", "password", "secret", "key", "jws", "proof")


def record(
    session: Session,
    *,
    user_id: uuid.UUID | None,
    action: str,
    actor: Actor,
    target_type: str | None = None,
    target_id: str | None = None,
    outcome: Outcome = "success",
    details: dict[str, Any] | None = None,
) -> None:
    safe = dict(details or {})
    for key in safe:
        if any(word in key.lower() for word in _FORBIDDEN_DETAIL_KEYS):
            raise ValueError(f"audit details must not carry secrets: {key}")
    session.add(
        AuditEvent(
            occurred_at=session.scalar(text("SELECT clock_timestamp()")),
            user_id=user_id,
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            outcome=outcome,
            details=safe,
        )
    )


def to_json(event: AuditEvent) -> dict[str, Any]:
    return {
        "occurred_at": event.occurred_at.isoformat(),
        "actor": event.actor,
        "action": event.action,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "outcome": event.outcome,
        "details": event.details,
    }


def list_for_user(session: Session, *, user_id: uuid.UUID, limit: int = 50) -> list[AuditEvent]:
    if not 1 <= limit <= MAX_LIST:
        raise ValueError("limit out of range")
    return list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.user_id == user_id)
            .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
            .limit(limit)
        ).all()
    )


LABELS = {
    "auth.login": "Login no painel",
    "device.pairing_created": "Código de pareamento gerado",
    "device.pairing_revoked": "Pareamento cancelado",
    "device.enrolled": "Dispositivo pediu pareamento",
    "device.approved": "Dispositivo aprovado",
    "device.rejected": "Dispositivo rejeitado",
    "telegram.linked": "Telegram vinculado",
    "telegram.unlinked": "Telegram desvinculado",
    "auth.password_reset_requested": "Código de recuperação de senha pedido",
    "auth.password_reset_completed": "Senha redefinida",
    "auth.password_reset_failed": "Tentativa de redefinir senha falhou",
    "action.requested": "Ação pedida (aguardando aval)",
    "action.approved": "Ação aprovada com código",
    "action.approval_failed": "Código de aprovação incorreto",
    "action.cancelled": "Ação cancelada",
    "action.dispatched": "Ação entregue ao agente",
    "action.failed": "Ação falhou no agente",
    "action.completed": "Ação concluída pelo agente",
    "action.delivered": "Arquivo entregue no Telegram",
}


def label(event: AuditEvent) -> str:
    when: datetime = event.occurred_at
    name = LABELS.get(event.action, event.action)
    extra = event.details.get("name") if isinstance(event.details, dict) else None
    return f"{when:%d/%m %H:%M} · {name}" + (f" ({extra})" if isinstance(extra, str) else "")
