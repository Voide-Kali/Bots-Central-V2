import type { ReactElement } from "react";
import type { DeviceTelemetry } from "../api/contracts";

const bytes = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });

export function formatBytes(value: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
  return `${bytes.format(size)} ${units[unit]}`;
}

export function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  if (days > 0) return `${days} d ${hours} h`;
  if (hours > 0) return `${hours} h ${minutes} min`;
  return `${minutes} min`;
}

function usage(used: number | null, total: number | null): string | null {
  if (used === null || total === null || total <= 0) return null;
  return `${formatBytes(used)} de ${formatBytes(total)} (${Math.round((used / total) * 100)}%)`;
}

function Meter({ label, percent, text }: { readonly label: string; readonly percent: number | null; readonly text: string }): ReactElement {
  return <div className="telemetry-item">
    <dt>{label}</dt>
    <dd>
      <span>{text}</span>
      {percent === null ? null : <meter aria-label={label} max={100} min={0} value={Math.min(100, Math.max(0, percent))} />}
    </dd>
  </div>;
}

export function TelemetryPanel({ telemetry }: { readonly telemetry: DeviceTelemetry | null }): ReactElement {
  if (telemetry === null) {
    return <p className="telemetry-empty">Sem telemetria ainda. Ela aparece depois que o agente aprovado enviar o próximo heartbeat.</p>;
  }
  const memory = usage(telemetry.memoryUsedBytes, telemetry.memoryTotalBytes);
  const disk = usage(telemetry.diskUsedBytes, telemetry.diskTotalBytes);
  const cpuText = telemetry.cpuPercent !== null
    ? `${bytes.format(telemetry.cpuPercent)}%`
    : telemetry.load1 !== null ? `carga ${bytes.format(telemetry.load1)}${telemetry.cpuCount ? ` / ${telemetry.cpuCount} núcleos` : ""}` : "Não informado";
  const cpuPercent = telemetry.cpuPercent ?? (telemetry.load1 !== null && telemetry.cpuCount ? (telemetry.load1 / telemetry.cpuCount) * 100 : null);
  const recorded = new Date(telemetry.recordedAt);
  return <section aria-label="Telemetria" className="telemetry-panel">
    <dl>
      <Meter label="CPU" percent={cpuPercent} text={cpuText} />
      <Meter label="Memória" percent={memory && telemetry.memoryTotalBytes ? ((telemetry.memoryUsedBytes ?? 0) / telemetry.memoryTotalBytes) * 100 : null} text={memory ?? "Não informado"} />
      <Meter label="Disco" percent={disk && telemetry.diskTotalBytes ? ((telemetry.diskUsedBytes ?? 0) / telemetry.diskTotalBytes) * 100 : null} text={disk ?? "Não informado"} />
      <div className="telemetry-item"><dt>Temperatura</dt><dd>{telemetry.temperatureC === null ? "Não disponível neste hardware" : `${bytes.format(telemetry.temperatureC)} °C`}</dd></div>
      <div className="telemetry-item"><dt>Ligado há</dt><dd>{telemetry.uptimeSeconds === null ? "Não informado" : formatUptime(telemetry.uptimeSeconds)}</dd></div>
    </dl>
    <p className="technical-label">Medido em {Number.isNaN(recorded.valueOf()) ? telemetry.recordedAt : new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "medium" }).format(recorded)}</p>
  </section>;
}
