import type { KeyboardEvent, ReactElement } from "react";
import type { Device, DeviceLifecycleStatus, DeviceTelemetry } from "../api/contracts";
import { ConnectionStatus } from "./ConnectionStatus";
import { TelemetryPanel } from "./TelemetryPanel";

interface DeviceListProps {
  readonly devices: readonly Device[];
  readonly selectedId: string | undefined;
  onSelect(id: string): void;
}

function selectWithKeyboard(event: KeyboardEvent<HTMLButtonElement>, select: () => void): void {
  if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); }
}

export function lifecycleLabel(status: DeviceLifecycleStatus): string {
  if (status === "pending") return "Aguardando seu aval";
  if (status === "active") return "Aprovado";
  return "Desativado";
}

/** "darwin/arm64" → "macOS"; unknown values are shown as sent by the server. */
export function friendlyPlatform(platform: string): string {
  const os = platform.split("/")[0]?.toLowerCase() ?? "";
  if (os === "darwin" || os === "macos") return "macOS";
  if (os === "linux") return "Linux";
  if (os === "windows") return "Windows";
  return platform;
}

function lastSeen(value: string | null): string {
  if (value === null) return "Ainda não se conectou";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return value;
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(parsed);
}

/** Short recency for the row ("agora", "há 5 min", "há 26 h", "há 3 d"); the details keep the full date. */
export function recency(value: string | null, now = Date.now()): string {
  if (value === null) return "nunca";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return value;
  const minutes = Math.max(0, Math.round((now - parsed) / 60_000));
  if (minutes < 2) return "agora";
  if (minutes < 60) return `há ${minutes} min`;
  if (minutes < 48 * 60) return `há ${Math.round(minutes / 60)} h`;
  return `há ${Math.round(minutes / 1_440)} d`;
}

function ratio(used: number | null, total: number | null): number | null {
  return used === null || total === null || total <= 0 ? null : Math.min(100, Math.max(0, (used / total) * 100));
}

/** Only a measured CPU percentage; the load average is not a percentage and is shown as text in the details. */
export function cpuShare(telemetry: DeviceTelemetry): number | null {
  return telemetry.cpuPercent;
}

/** One figure and a 3px bar at its true ratio; the bar turns to the warning colour from 90%. */
function Metric({ label, percent }: { readonly label: string; readonly percent: number | null | undefined }): ReactElement {
  if (percent === null || percent === undefined) return <span className="metric metric--none" data-label={label}>—</span>;
  const value = Math.round(percent);
  return <span className={value >= 90 ? "metric metric--high" : "metric"} data-label={label}>
    <span className="metric__value num">{value}<small>%</small></span>
    <span aria-hidden="true" className="metric__track"><span className="metric__fill" style={{ width: `${value}%` }} /></span>
  </span>;
}

export function DeviceList({ devices, selectedId, onSelect }: DeviceListProps): ReactElement {
  return <div className="device-table">
    <div aria-hidden="true" className="device-table__head">
      <span>Computador</span><span>Situação</span><span>Conexão</span><span className="num">CPU</span><span className="num">Memória</span><span className="num">Disco</span><span className="num">Temp.</span><span className="num">Visto</span>
    </div>
    <ul aria-label="Computadores" className="device-list">{devices.map((device) => {
      const selected = device.id === selectedId;
      const select = (): void => onSelect(device.id);
      const telemetry = device.lifecycleStatus === "active" ? device.telemetry : null;
      return <li className={`device device--${device.lifecycleStatus}${selected ? " device--open" : ""}`} key={device.id}>
        <button aria-expanded={selected} className="device__row" onClick={select} onKeyDown={(event) => selectWithKeyboard(event, select)} type="button">
          <span className="device__name"><strong>{device.name}</strong><span>{friendlyPlatform(device.platform)}{device.agentVersion ? ` · agente ${device.agentVersion}` : ""}</span></span>
          <span className="device__state">{device.lifecycleStatus === "pending" ? <span className="badge badge--pending">{lifecycleLabel(device.lifecycleStatus)}</span> : <span className={`device__lifecycle device__lifecycle--${device.lifecycleStatus}`}>{lifecycleLabel(device.lifecycleStatus)}</span>}</span>
          <ConnectionStatus presence={device.status} />
          <Metric label="CPU" percent={telemetry ? cpuShare(telemetry) : null} />
          <Metric label="Memória" percent={telemetry ? ratio(telemetry.memoryUsedBytes, telemetry.memoryTotalBytes) : null} />
          <Metric label="Disco" percent={telemetry ? ratio(telemetry.diskUsedBytes, telemetry.diskTotalBytes) : null} />
          <span className={telemetry?.temperatureC != null ? "device__temp num" : "device__temp metric--none"}>{telemetry?.temperatureC != null ? <>{Math.round(telemetry.temperatureC)}<small> °C</small></> : "—"}</span>
          <span className="device__seen num">{recency(device.lastSeenAt)}</span>
        </button>
        {selected ? <div aria-label={`Detalhes de ${device.name}`} className="device__details">
          {device.lifecycleStatus === "active" ? <TelemetryPanel telemetry={device.telemetry} /> : null}
          <dl className="facts">
            <div><dt>Situação</dt><dd>{lifecycleLabel(device.lifecycleStatus)}</dd></div>
            <div><dt>Conexão</dt><dd><ConnectionStatus presence={device.status} /></dd></div>
            <div><dt>Visto por último</dt><dd>{lastSeen(device.lastSeenAt)}</dd></div>
            <div><dt>Sistema</dt><dd>{device.platform}</dd></div>
            <div><dt>Versão do agente</dt><dd>{device.agentVersion ?? "Não informada"}</dd></div>
            <div><dt>Identificador</dt><dd className="facts__mono">{device.id}</dd></div>
          </dl>
        </div> : null}
      </li>;
    })}</ul>
  </div>;
}
