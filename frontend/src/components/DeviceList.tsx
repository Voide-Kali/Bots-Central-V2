import type { KeyboardEvent, ReactElement } from "react";
import type { ProvisionalDevice } from "../api/contracts";
import { ConnectionStatus } from "./ConnectionStatus";

interface DeviceListProps {
  readonly devices: readonly ProvisionalDevice[];
  readonly selectedId: string | undefined;
  onSelect(id: string): void;
  onDetails(device: ProvisionalDevice): void;
}

function selectWithKeyboard(
  event: KeyboardEvent<HTMLButtonElement>,
  select: () => void
): void {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    select();
  }
}

export function DeviceList({ devices, selectedId, onSelect, onDetails }: DeviceListProps): ReactElement {
  return (
    <section aria-label="Lista de dispositivos" className="device-list">
      <div aria-hidden="true" className="device-list__head">
        <span>Dispositivo</span>
        <span>Status</span>
        <span>Agent</span>
        <span>Última atividade</span>
      </div>
      <ul>
        {devices.map((device) => {
          const selected = device.id === selectedId;
          const select = (): void => onSelect(device.id);
          return (
            <li className={selected ? "device-list__item device-list__item--selected" : "device-list__item"} key={device.id}>
              <button
                aria-expanded={selected}
                className="device-row"
                onClick={select}
                onKeyDown={(event) => selectWithKeyboard(event, select)}
                type="button"
              >
                <span className="device-row__device">
                  <strong>{device.name}</strong>
                  <span className="technical-label">{device.id} · {device.platform}</span>
                  {selected ? <span className="selected-label">selecionado</span> : null}
                </span>
                <ConnectionStatus connection={device.connection} />
                <span className="technical-value">{device.agentVersion}</span>
                <span>{device.lastSeen}</span>
              </button>
              {selected ? (
                <div aria-label={`Detalhes de ${device.name}`} className="device-details">
                  <dl>
                    <div><dt>ID do dispositivo</dt><dd>{device.id}</dd></div>
                    <div><dt>Plataforma</dt><dd>{device.platform}</dd></div>
                    <div><dt>Agent</dt><dd>{device.agentVersion}</dd></div>
                    <div><dt>Última atividade</dt><dd>{device.lastSeen}</dd></div>
                    <div><dt>Conexão</dt><dd><ConnectionStatus connection={device.connection} /></dd></div>
                  </dl>
                  <button className="details-button" onClick={() => onDetails(device)} type="button">Ver detalhes</button>
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
