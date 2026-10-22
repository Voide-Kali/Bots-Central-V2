"""Plain-text rendering of device state for Telegram messages (pt-BR).

No parse_mode is used anywhere: device names come from agents and must never
be interpreted as markup.
"""

from datetime import datetime

from app.db.models import Device, DeviceTelemetrySample

PLATFORMS = {"darwin": "macOS", "macos": "macOS", "linux": "Linux", "windows": "Windows"}


def _gb(value: int) -> str:
    return f"{value / 1024**3:.1f}".replace(".", ",")


def _ago(now: datetime, then: datetime | None) -> str:
    if then is None:
        return "nunca se conectou"
    seconds = max(0, int((now - then).total_seconds()))
    if seconds < 90:
        return f"visto há {seconds} s"
    if seconds < 3600:
        return f"visto há {seconds // 60} min"
    if seconds < 86400:
        return f"visto há {seconds // 3600} h {seconds % 3600 // 60} min"
    return f"visto há {seconds // 86400} d"


def _uptime(seconds: int) -> str:
    days, hours = seconds // 86400, seconds % 86400 // 3600
    return f"{days} d {hours} h" if days else f"{hours} h {seconds % 3600 // 60} min"


def friendly_platform(platform: str) -> str:
    return PLATFORMS.get(platform.split("/", 1)[0].lower(), platform)


def _state(device: Device, presence: str) -> str:
    if device.lifecycle_status.value == "pending":
        return "aguardando aprovação"
    if device.lifecycle_status.value == "revoked":
        return "desativado"
    return presence


def _metrics(sample: DeviceTelemetrySample) -> list[str]:
    parts: list[str] = []
    if sample.cpu_percent is not None:
        parts.append(f"CPU {sample.cpu_percent:.0f}%")
    elif sample.load1 is not None:
        parts.append(f"carga {sample.load1:.2f}".replace(".", ","))
    if sample.memory_used_bytes is not None and sample.memory_total_bytes:
        parts.append(f"RAM {_gb(sample.memory_used_bytes)}/{_gb(sample.memory_total_bytes)} GB")
    if sample.disk_used_bytes is not None and sample.disk_total_bytes:
        parts.append(f"disco {sample.disk_used_bytes * 100 / sample.disk_total_bytes:.0f}%")
    if sample.temperature_c is not None:
        parts.append(f"{sample.temperature_c:.0f} °C")
    return parts


def device_line(device: Device, presence: str, sample: DeviceTelemetrySample | None) -> str:
    state = _state(device, presence)
    lines = [f"{device.name} — {state}"]
    if sample is not None and device.lifecycle_status.value == "active":
        parts = _metrics(sample)
        if parts:
            lines.append("   " + " · ".join(parts))
    return "\n".join(lines)


def device_card(
    device: Device, presence: str, sample: DeviceTelemetrySample | None, now: datetime
) -> str:
    """Detailed card for one computer (the "Detalhes" button)."""
    state = _state(device, presence)
    lines = [
        device.name,
        "",
        f"{state.upper()} · {_ago(now, device.last_seen_at)}",
        f"Sistema: {friendly_platform(device.platform)} ({device.platform})",
        f"Agente: {device.agent_version or 'não informado'}",
    ]
    if device.lifecycle_status.value == "pending":
        lines += ["", "Aprove no painel comparando o código mostrado no computador."]
    elif sample is not None:
        lines.append("")
        if sample.cpu_percent is not None:
            lines.append(f"CPU: {sample.cpu_percent:.0f}%")
        elif sample.load1 is not None:
            cores = f" de {sample.cpu_count} núcleos" if sample.cpu_count else ""
            lines.append(f"CPU: carga {sample.load1:.2f}{cores}".replace(".", ","))
        if sample.memory_used_bytes is not None and sample.memory_total_bytes:
            percent = sample.memory_used_bytes * 100 / sample.memory_total_bytes
            lines.append(
                f"RAM: {_gb(sample.memory_used_bytes)} de {_gb(sample.memory_total_bytes)} GB"
                f" ({percent:.0f}%)"
            )
        if sample.disk_used_bytes is not None and sample.disk_total_bytes:
            percent = sample.disk_used_bytes * 100 / sample.disk_total_bytes
            lines.append(
                f"Disco: {_gb(sample.disk_used_bytes)} de {_gb(sample.disk_total_bytes)} GB"
                f" ({percent:.0f}%)"
            )
        if sample.temperature_c is not None:
            lines.append(f"Temperatura: {sample.temperature_c:.0f} °C")
        if sample.uptime_seconds is not None:
            lines.append(f"Ligado há: {_uptime(sample.uptime_seconds)}")
    else:
        lines += ["", "Sem medições ainda."]
    return "\n".join(lines)
