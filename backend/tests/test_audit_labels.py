"""Every audit action the code records has a Portuguese label (E2E 22/10)."""

import re
from datetime import UTC, datetime
from pathlib import Path

from app.audit import events
from app.db.models import AuditEvent


def test_every_recorded_action_has_a_label() -> None:
    recorded = set()
    for path in Path(__file__).parents[1].joinpath("app").rglob("*.py"):
        recorded |= set(re.findall(r'action="([a-z_]+\.[a-z_]+)"', path.read_text()))
    assert recorded, "no audit actions found"
    assert recorded <= set(events.LABELS), sorted(recorded - set(events.LABELS))


def test_label_names_the_action_device_and_method() -> None:
    row = AuditEvent(
        occurred_at=datetime(2026, 10, 22, 9, 30, tzinfo=UTC),
        actor="telegram",
        action="action.approved",
        outcome="success",
        details={"action": "lock_screen", "by": "pin"},
    )
    assert events.label(row) == "22/10 09:30 · Ação aprovada (bloquear tela, com PIN)"
    row.details = {"name": "tropa", "action": "send_file", "file": "notas.pdf"}
    assert events.label(row).endswith("(enviar arquivo, notas.pdf, tropa)")
