"""Network Intelligence: persist scan results, compare, detect new hosts.

When a network_scan action completes, ``persist_scan`` parses the raw nmap
output, stores the hosts, and returns a diff against the previous scan so the
caller can alert the user about new or disappeared hosts.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import NetworkScan, NetworkScanHost


@dataclass(frozen=True)
class HostEntry:
    ip: str
    hostname: str | None


@dataclass(frozen=True)
class ScanDiff:
    """Difference between two consecutive scans from the same device."""

    new_hosts: list[HostEntry]
    gone_hosts: list[HostEntry]
    total: int


# Regex that matches the agent's formatted output: "192.168.1.1 - hostname" or just "192.168.1.1"
_HOST_LINE = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){3})(?:\s+-\s+(.+))?$", re.MULTILINE)


def parse_scan_text(raw: str) -> list[HostEntry]:
    """Parse the agent's friendly scan output into host entries."""
    hosts: list[HostEntry] = []
    for match in _HOST_LINE.finditer(raw):
        ip = match.group(1)
        hostname = match.group(2)
        if hostname:
            hostname = hostname.strip()
        hosts.append(HostEntry(ip=ip, hostname=hostname or None))
    return hosts


def persist_scan(
    session: Session,
    *,
    device_id: uuid.UUID,
    command_id: uuid.UUID | None,
    raw_text: str,
) -> ScanDiff | None:
    """Parse and persist a scan result; return the diff against the previous scan.

    Returns ``None`` if parsing yields zero hosts (the scan text was empty or
    malformed).
    """
    hosts = parse_scan_text(raw_text)
    if not hosts:
        return None

    now = cast(datetime, session.scalar(text("SELECT clock_timestamp()")))

    # Fetch the previous scan for this device, if any.
    prev_scan = session.scalars(
        select(NetworkScan)
        .where(NetworkScan.device_id == device_id)
        .order_by(NetworkScan.scanned_at.desc())
        .limit(1)
    ).first()

    prev_hosts: dict[str, HostEntry] = {}
    if prev_scan is not None:
        prev_rows = session.scalars(
            select(NetworkScanHost).where(NetworkScanHost.scan_id == prev_scan.id)
        ).all()
        prev_hosts = {h.ip: HostEntry(ip=h.ip, hostname=h.hostname) for h in prev_rows}

    # Create the new scan record.
    scan = NetworkScan(
        device_id=device_id,
        command_id=command_id,
        scanned_at=now,
        host_count=len(hosts),
        raw_text=raw_text,
    )
    session.add(scan)
    session.flush()  # get scan.id

    # Determine new vs seen hosts.
    current_ips = set()
    for host in hosts:
        current_ips.add(host.ip)
        is_new = host.ip not in prev_hosts
        session.add(
            NetworkScanHost(
                scan_id=scan.id,
                ip=host.ip,
                hostname=host.hostname,
                first_seen_scan_id=scan.id if is_new else None,
            )
        )

    new_hosts = [h for h in hosts if h.ip not in prev_hosts]
    gone_hosts = [h for ip, h in sorted(prev_hosts.items()) if ip not in current_ips]

    return ScanDiff(new_hosts=new_hosts, gone_hosts=gone_hosts, total=len(hosts))


def format_diff(diff: ScanDiff, device_name: str) -> str | None:
    """Format the diff as a plain-text Telegram alert, or None if nothing changed."""
    parts: list[str] = []

    if diff.new_hosts:
        lines = [f"  {h.ip}" + (f" - {h.hostname}" if h.hostname else "") for h in diff.new_hosts]
        parts.append(
            f"Novos aparelhos na rede de {device_name} ({len(diff.new_hosts)}):\n"
            + "\n".join(lines)
        )

    if diff.gone_hosts:
        lines = [f"  {h.ip}" + (f" - {h.hostname}" if h.hostname else "") for h in diff.gone_hosts]
        parts.append(
            f"Aparelhos que sairam da rede de {device_name} ({len(diff.gone_hosts)}):\n"
            + "\n".join(lines)
        )

    if not parts:
        return None

    parts.append(f"Total agora: {diff.total} aparelhos.")
    return "\n\n".join(parts)


def latest_scan_summary(session: Session, device_id: uuid.UUID) -> str | None:
    """Return a readable summary of the most recent scan for a device, or None."""
    scan = session.scalars(
        select(NetworkScan)
        .where(NetworkScan.device_id == device_id)
        .order_by(NetworkScan.scanned_at.desc())
        .limit(1)
    ).first()
    if scan is None:
        return None

    hosts = session.scalars(
        select(NetworkScanHost).where(NetworkScanHost.scan_id == scan.id)
    ).all()

    lines = [f"Ultimo scan: {scan.host_count} aparelhos ({_fmt_time(scan.scanned_at)})"]
    for h in sorted(hosts, key=lambda x: _ip_sort_key(x.ip)):
        line = f"  {h.ip}"
        if h.hostname:
            line += f" - {h.hostname}"
        if h.first_seen_scan_id == scan.id:
            line += " [NOVO]"
        lines.append(line)
    return "\n".join(lines)


def scan_history(
    session: Session,
    device_id: uuid.UUID,
    *,
    limit: int = 10,
) -> list[NetworkScan]:
    """Return the N most recent scans for a device, newest first."""
    return list(
        session.scalars(
            select(NetworkScan)
            .where(NetworkScan.device_id == device_id)
            .order_by(NetworkScan.scanned_at.desc())
            .limit(limit)
        ).all()
    )


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%d/%m %H:%M")


def _ip_sort_key(ip: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in ip.split("."))
    except ValueError:
        return (999, 999, 999, 999)
