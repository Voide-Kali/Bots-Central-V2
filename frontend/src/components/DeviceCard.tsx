import type { ReactElement } from "react";
import type { ProvisionalDevice } from "../api/contracts";
export function DeviceCard({ device }: { readonly device: ProvisionalDevice }): ReactElement {
  const label = device.connection === "online" ? "Online" : "Offline";
  return <article className="device-card"><div className="device-card__heading"><div><p className="eyebrow">Dispositivo</p><h2>{device.name}</h2><p>{device.platform}</p></div><span className={`connection connection--${device.connection}`}><span aria-hidden="true" />{label}</span></div><dl className="device-card__details"><div><dt>Visto por último</dt><dd>{device.lastSeen}</dd></div><div><dt>Versão do agente</dt><dd>{device.agentVersion}</dd></div></dl></article>;
}
