"""Opt-in network location carried in a separate `net` heartbeat claim (ADR-036).

Deliberately NOT part of telemetry, which is kept free of network addresses by design. Only the
current state is kept, on the device row. The public IP is best-effort (the agent resolves it);
the local IPs are the device's non-loopback interface addresses. Geolocation (city/country) is a
later step done server-side (ADR-036, parte 2).
"""

from __future__ import annotations

import datetime as dt
import ipaddress
from dataclasses import dataclass, field

from app.db.models import Device

NETWORK_VERSION = 1
_ALLOWED_KEYS = {"v", "public_ip", "local_ips"}
_MAX_LOCAL_IPS = 16


class InvalidNetwork(Exception):
    """The `net` claim is malformed; the heartbeat is rejected (like bad telemetry)."""


def _valid_ip(value: object) -> str | None:
    if not isinstance(value, str):
        raise InvalidNetwork
    text = value.strip()
    if not text:
        return None
    try:
        return str(ipaddress.ip_address(text))
    except ValueError as error:
        raise InvalidNetwork from error


@dataclass(frozen=True)
class NetworkInfo:
    public_ip: str | None = None
    local_ips: tuple[str, ...] = field(default_factory=tuple)


def parse_claim(value: object) -> NetworkInfo:
    if not isinstance(value, dict) or not set(value) <= _ALLOWED_KEYS:
        raise InvalidNetwork
    version = value.get("v")
    if isinstance(version, bool) or version != NETWORK_VERSION:
        raise InvalidNetwork
    public_ip = _valid_ip(value["public_ip"]) if value.get("public_ip") is not None else None
    local_raw = value.get("local_ips", [])
    if not isinstance(local_raw, list) or len(local_raw) > _MAX_LOCAL_IPS:
        raise InvalidNetwork
    seen: list[str] = []
    for item in local_raw:
        ip = _valid_ip(item)
        if ip is not None and ip not in seen:
            seen.append(ip)
    return NetworkInfo(public_ip=public_ip, local_ips=tuple(seen))


def store(device: Device, info: NetworkInfo, *, now: dt.datetime) -> None:
    """Write the latest network state onto the device, inside the heartbeat transaction."""
    device.last_public_ip = info.public_ip
    device.last_local_ips = list(info.local_ips)
    device.network_reported_at = now


def device_to_json(device: Device) -> dict[str, object] | None:
    if device.last_public_ip is None and not device.last_local_ips:
        return None
    return {
        "public_ip": device.last_public_ip,
        "local_ips": list(device.last_local_ips or []),
        "reported_at": (
            device.network_reported_at.isoformat() if device.network_reported_at else None
        ),
    }
