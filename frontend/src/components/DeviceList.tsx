import type { KeyboardEvent, ReactElement } from "react";
import type { Device, DeviceLifecycleStatus } from "../api/contracts";
import { ConnectionStatus } from "./ConnectionStatus";

interface DeviceListProps {
  readonly devices: readonly Device[];
  readonly selectedId: string | undefined;
  onSelect(id: string): void;
}

function selectWithKeyboard(event: KeyboardEvent<HTMLButtonElement>, select: () => void): void {
  if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); }
}

function lifecycleLabel(status: DeviceLifecycleStatus): string {
  if (status === "pending") return "Pendente de aprovação";
  if (status === "active") return "Ativo";
  return "Revogado";
}

function serverTimestamp(value: string | null): string {
  if (value === null) return "Ainda não recebido pelo servidor";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return value;
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "medium" }).format(parsed);
}

export function DeviceList({ devices, selectedId, onSelect }: DeviceListProps): ReactElement {
  return <section aria-label="Lista de dispositivos" className="device-list">
    <div aria-hidden="true" className="device-list__head"><span>Dispositivo</span><span>Status</span><span>Agent</span><span>Última atividade</span></div>
    <ul>{devices.map((device) => {
      const selected = device.id === selectedId;
      const select = (): void => onSelect(device.id);
      return <li className={selected ? "device-list__item device-list__item--selected" : "device-list__item"} key={device.id}>
        <button aria-expanded={selected} className="device-row" onClick={select} onKeyDown={(event) => selectWithKeyboard(event, select)} type="button">
          <span className="device-row__device"><strong>{device.name}</strong><span className="technical-label">{device.id} · {device.platform}</span><span className={`lifecycle-badge lifecycle-badge--${device.lifecycleStatus}`}>{lifecycleLabel(device.lifecycleStatus)}</span>{selected ? <span className="selected-label">selecionado</span> : null}</span>
          <ConnectionStatus presence={device.status} />
          <span className="technical-value">{device.agentVersion ?? "Não informado"}</span>
          <span>{serverTimestamp(device.lastSeenAt)}</span>
        </button>
        {selected ? <div aria-label={`Detalhes de ${device.name}`} className="device-details"><dl>
          <div><dt>ID do dispositivo</dt><dd>{device.id}</dd></div>
          <div><dt>Nome informado</dt><dd>{device.name}</dd></div>
          <div><dt>Plataforma</dt><dd>{device.platform}</dd></div>
          <div><dt>Ciclo de vida</dt><dd>{lifecycleLabel(device.lifecycleStatus)}</dd></div>
          <div><dt>Presença do servidor</dt><dd><ConnectionStatus presence={device.status} /></dd></div>
          <div><dt>Agent</dt><dd>{device.agentVersion ?? "Não informado pelo servidor"}</dd></div>
          <div><dt>Última atividade</dt><dd>{serverTimestamp(device.lastSeenAt)}</dd></div>
        </dl></div> : null}
      </li>;
    })}</ul>
  </section>;
}
