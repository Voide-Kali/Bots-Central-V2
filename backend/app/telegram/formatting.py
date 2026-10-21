"""Plain-text rendering of device state for Telegram messages (pt-BR)."""

from app.db.models import Device, DeviceTelemetrySample


def _gb(value: int) -> str:
    return f"{value / 1024**3:.1f}".replace(".", ",")


def device_line(device: Device, presence: str, sample: DeviceTelemetrySample | None) -> str:
    icon = "🟢" if presence == "online" else "🔴"
    state = "online" if presence == "online" else "offline"
    if device.lifecycle_status.value == "pending":
        icon, state = "🟡", "aguardando aprovação"
    elif device.lifecycle_status.value == "revoked":
        icon, state = "⚫", "revogado"
    lines = [f"{icon} {device.name} — {state}"]
    if sample is not None and device.lifecycle_status.value == "active":
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
        if parts:
            lines.append("   " + " · ".join(parts))
    return "\n".join(lines)
