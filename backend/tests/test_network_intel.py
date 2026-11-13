"""Tests for the network intelligence module."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.enums import DeviceLifecycleStatus
from app.db.models import Device, User
from app.devices.network_intel import (
    HostEntry,
    ScanDiff,
    format_diff,
    latest_scan_summary,
    parse_scan_text,
    persist_scan,
    scan_history,
)

pytestmark = pytest.mark.postgresql


SAMPLE_SCAN = """\
5 aparelhos ligados na sua rede local:

192.168.1.1 - router.local
192.168.1.10 - tropa
192.168.1.20 - mac-mini.local
192.168.1.30
192.168.1.40 - impressora"""


def _seed(session: Session, *, device_name: str = "tropa") -> tuple[uuid.UUID, uuid.UUID]:
    user_id = uuid.uuid4()
    device_id = uuid.uuid4()
    session.add(User(id=user_id))
    session.flush()
    session.add(
        Device(
            id=device_id,
            user_id=user_id,
            name=device_name,
            platform="linux",
            agent_version="0.1.0",
            lifecycle_status=DeviceLifecycleStatus.ACTIVE,
            public_key=b"k" * 32,
            last_seen_at=datetime.now(UTC),
        )
    )
    session.flush()
    return user_id, device_id


# --- parse_scan_text ---


def test_parse_scan_text_extracts_hosts() -> None:
    hosts = parse_scan_text(SAMPLE_SCAN)
    assert len(hosts) == 5
    assert hosts[0] == HostEntry(ip="192.168.1.1", hostname="router.local")
    assert hosts[3] == HostEntry(ip="192.168.1.30", hostname=None)


def test_parse_scan_text_empty() -> None:
    assert parse_scan_text("Nenhum aparelho respondeu na sua rede local.") == []


def test_parse_scan_text_single_host() -> None:
    hosts = parse_scan_text("1 aparelhos ligados:\n\n10.0.0.1 - gateway")
    assert len(hosts) == 1
    assert hosts[0].ip == "10.0.0.1"
    assert hosts[0].hostname == "gateway"


# --- persist_scan ---


def test_persist_scan_creates_records(migrated_postgresql_engine: Engine) -> None:
    factory = sessionmaker(bind=migrated_postgresql_engine)
    with factory() as session, session.begin():
        _, device_id = _seed(session)

    with factory() as session, session.begin():
        diff = persist_scan(session, device_id=device_id, command_id=None, raw_text=SAMPLE_SCAN)

    assert diff is not None
    assert diff.total == 5
    assert len(diff.new_hosts) == 5  # first scan: all are new
    assert diff.gone_hosts == []

    with factory() as session:
        scans = scan_history(session, device_id)
        assert len(scans) == 1
        assert scans[0].host_count == 5


def test_persist_scan_detects_new_and_gone(migrated_postgresql_engine: Engine) -> None:
    factory = sessionmaker(bind=migrated_postgresql_engine)
    with factory() as session, session.begin():
        _, device_id = _seed(session)

    # First scan.
    with factory() as session, session.begin():
        persist_scan(session, device_id=device_id, command_id=None, raw_text=SAMPLE_SCAN)

    # Second scan: one host gone (192.168.1.40), one new (192.168.1.50).
    scan2 = (
        "4 aparelhos ligados:\n\n"
        "192.168.1.1 - router.local\n"
        "192.168.1.10 - tropa\n"
        "192.168.1.20 - mac-mini.local\n"
        "192.168.1.50 - novo-dispositivo"
    )
    with factory() as session, session.begin():
        diff = persist_scan(session, device_id=device_id, command_id=None, raw_text=scan2)

    assert diff is not None
    assert diff.total == 4
    assert len(diff.new_hosts) == 1
    assert diff.new_hosts[0].ip == "192.168.1.50"
    assert diff.new_hosts[0].hostname == "novo-dispositivo"
    assert len(diff.gone_hosts) == 2  # 192.168.1.30 and 192.168.1.40
    gone_ips = {h.ip for h in diff.gone_hosts}
    assert "192.168.1.30" in gone_ips
    assert "192.168.1.40" in gone_ips


def test_persist_scan_empty_returns_none(migrated_postgresql_engine: Engine) -> None:
    factory = sessionmaker(bind=migrated_postgresql_engine)
    with factory() as session, session.begin():
        _, device_id = _seed(session)

    with factory() as session, session.begin():
        diff = persist_scan(
            session,
            device_id=device_id,
            command_id=None,
            raw_text="Nenhum aparelho respondeu na sua rede local.",
        )
    assert diff is None


# --- format_diff ---


def test_format_diff_new_hosts() -> None:
    diff = ScanDiff(
        new_hosts=[HostEntry("192.168.1.50", "novo")],
        gone_hosts=[],
        total=5,
    )
    result = format_diff(diff, "tropa")
    assert result is not None
    assert "Novos aparelhos" in result
    assert "192.168.1.50" in result
    assert "novo" in result
    assert "Total agora: 5" in result


def test_format_diff_gone_hosts() -> None:
    diff = ScanDiff(
        new_hosts=[],
        gone_hosts=[HostEntry("192.168.1.40", "impressora")],
        total=4,
    )
    result = format_diff(diff, "tropa")
    assert result is not None
    assert "sairam" in result
    assert "192.168.1.40" in result


def test_format_diff_no_changes() -> None:
    diff = ScanDiff(new_hosts=[], gone_hosts=[], total=5)
    assert format_diff(diff, "tropa") is None


# --- latest_scan_summary ---


def test_latest_scan_summary_with_data(migrated_postgresql_engine: Engine) -> None:
    factory = sessionmaker(bind=migrated_postgresql_engine)
    with factory() as session, session.begin():
        _, device_id = _seed(session)

    with factory() as session, session.begin():
        persist_scan(session, device_id=device_id, command_id=None, raw_text=SAMPLE_SCAN)

    with factory() as session:
        summary = latest_scan_summary(session, device_id)

    assert summary is not None
    assert "5 aparelhos" in summary
    assert "192.168.1.1" in summary
    assert "router.local" in summary
    assert "[NOVO]" in summary  # first scan, all are new


def test_latest_scan_summary_no_scans(migrated_postgresql_engine: Engine) -> None:
    factory = sessionmaker(bind=migrated_postgresql_engine)
    with factory() as session, session.begin():
        _, device_id = _seed(session)

    with factory() as session:
        assert latest_scan_summary(session, device_id) is None
