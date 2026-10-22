import type { KeyboardEvent, ReactElement } from "react";
import type { Device, DeviceLifecycleStatus } from "../api/contracts";
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

export function DeviceList({ devices, selectedId, onSelect }: DeviceListProps): ReactElement {
  return <ul aria-label="Computadores" className="device-list">{devices.map((device) => {
    const selected = device.id === selectedId;
    const select = (): void => onSelect(device.id);
    return <li className={`device device--${device.lifecycleStatus}${selected ? " device--open" : ""}`} key={device.id}>
      <button aria-expanded={selected} className="device__row" onClick={select} onKeyDown={(event) => selectWithKeyboard(event, select)} type="button">
        <span className="device__name"><strong>{device.name}</strong><span>{friendlyPlatform(device.platform)}</span></span>
        <span className={`badge badge--${device.lifecycleStatus}`}>{lifecycleLabel(device.lifecycleStatus)}</span>
        <ConnectionStatus presence={device.status} />
        <span className="device__seen">{lastSeen(device.lastSeenAt)}</span>
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
  })}</ul>;
}
