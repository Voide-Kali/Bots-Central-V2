import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactElement } from "react";
import type { ApiClient } from "../api";
import type { AuditEvent, Device } from "../api/contracts";
import { UnauthenticatedError } from "../api/errors";
import { Brand } from "./Brand";
import { DeviceChart } from "./DeviceChart";
import { ACTION_LABELS, eventDetail } from "./HistoryPanel";

/*
 * "Modo feira": a read-only wall display for a TV at the science fair. The fleet, one big live
 * chart (cycling through computers, 1 sample/second) and a live feed of events. No controls,
 * no PIN, nothing that changes a computer: it only shows what is already happening.
 */

const DEVICES_EVERY = 8_000;
const EVENTS_EVERY = 5_000;
const FEATURE_EVERY = 12_000;
const ACTORS: Readonly<Record<string, string>> = { user: "voce", device: "computador", system: "sistema", telegram: "Telegram" };

function pct(used: number | null, total: number | null): number | null {
  return used !== null && total ? Math.round((used / total) * 100) : null;
}

function when(timestamp: string): string {
  return new Intl.DateTimeFormat("pt-BR", { timeStyle: "medium" }).format(new Date(timestamp));
}

function Tile({ device }: { readonly device: Device }): ReactElement {
  const online = device.status === "online" && device.lifecycleStatus === "active";
  const sample = device.telemetry;
  const cpu = sample?.cpuPercent ?? null;
  const memory = pct(sample?.memoryUsedBytes ?? null, sample?.memoryTotalBytes ?? null);
  return <div className={online ? "fair-tile fair-tile--on" : "fair-tile"}>
    <div className="fair-tile__head">
      <span className="fair-tile__dot" />
      <span className="fair-tile__name">{device.name}</span>
    </div>
    <div className="fair-tile__cpu num">{cpu !== null ? `${Math.round(cpu)}` : "--"}<small>% CPU</small></div>
    <div className="fair-tile__bars">
      <span className="fair-bar"><span className="fair-bar__fill" style={{ width: `${cpu ?? 0}%` }} /></span>
      <span className="fair-tile__sub num">{memory !== null ? `mem ${memory}%` : "sem medicao"}{sample?.temperatureC != null ? ` - ${Math.round(sample.temperatureC)} C` : ""}</span>
    </div>
  </div>;
}

function Feed({ events }: { readonly events: readonly AuditEvent[] }): ReactElement {
  if (events.length === 0) {
    return <p className="fair-feed__empty">Aguardando atividade...</p>;
  }
  return <ul className="fair-feed__list">
    {events.map((event) => <li className={event.outcome === "failure" || event.outcome === "denied" ? "fair-feed__row fair-feed__row--alert" : "fair-feed__row"} key={`${event.occurredAt}-${event.action}`}>
      <span className="fair-feed__time num">{when(event.occurredAt)}</span>
      <span className="fair-feed__what">{ACTION_LABELS[event.action] ?? event.action}</span>
      <span className="fair-feed__detail">{eventDetail(event)}{event.actor in ACTORS ? ` - ${ACTORS[event.actor]}` : ""}</span>
    </li>)}
  </ul>;
}

export function FairMode({ api, onUnauthenticated }: { readonly api: ApiClient; onUnauthenticated(): void }): ReactElement {
  const [devices, setDevices] = useState<readonly Device[]>([]);
  const [events, setEvents] = useState<readonly AuditEvent[]>([]);
  const [featured, setFeatured] = useState(0);
  const [now, setNow] = useState(() => new Date());
  const frame = useRef<HTMLDivElement>(null);

  const onError = useCallback((error: unknown) => { if (error instanceof UnauthenticatedError) onUnauthenticated(); }, [onUnauthenticated]);

  useEffect(() => {
    let active = true;
    const load = (): void => {
      if (document.visibilityState !== "visible") return;
      void api.devices.list().then((list) => { if (active) setDevices(list); }).catch(onError);
      void api.audit?.list(30).then((rows) => { if (active) setEvents(rows); }).catch(onError);
    };
    load();
    const devicesTimer = window.setInterval(() => { void api.devices.list().then((list) => { if (active) setDevices(list); }).catch(onError); }, DEVICES_EVERY);
    const eventsTimer = window.setInterval(() => { void api.audit?.list(30).then((rows) => { if (active) setEvents(rows); }).catch(onError); }, EVENTS_EVERY);
    const clock = window.setInterval(() => setNow(new Date()), 1_000);
    return () => { active = false; window.clearInterval(devicesTimer); window.clearInterval(eventsTimer); window.clearInterval(clock); };
  }, [api, onError]);

  const active = useMemo(() => devices.filter((device) => device.lifecycleStatus === "active"), [devices]);
  useEffect(() => {
    if (active.length < 2) return undefined;
    const timer = window.setInterval(() => setFeatured((index) => (index + 1) % active.length), FEATURE_EVERY);
    return () => { window.clearInterval(timer); };
  }, [active.length]);

  const featuredDevice = active.length > 0 ? active[featured % active.length] : undefined;
  const online = active.filter((device) => device.status === "online").length;
  const safe = active.length > 0 && online === active.length;

  function fullscreen(): void {
    const element = frame.current;
    if (!element) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void element.requestFullscreen?.();
  }

  return <section className="fair" ref={frame}>
    <header className="fair__top">
      <div className="fair__brand"><Brand /></div>
      <div className={safe ? "fair__status fair__status--safe" : "fair__status fair__status--warn"}>
        <span className="fair__status-label">{active.length === 0 ? "SEM COMPUTADORES" : safe ? "PROTEGIDO" : "ATENCAO"}</span>
        <span className="fair__status-sub num">{online} de {active.length} online</span>
      </div>
      <div className="fair__meta">
        <span className="fair__clock num">{new Intl.DateTimeFormat("pt-BR", { timeStyle: "medium" }).format(now)}</span>
        <button className="button" onClick={fullscreen} type="button">Tela cheia</button>
      </div>
    </header>

    <div className="fair__grid">
      <div className="fair__chart">
        {featuredDevice ? <>
          <div className="fair__chart-head"><span className="fair__chart-name">{featuredDevice.name}</span><span className="fair__chart-live">ao vivo</span></div>
          <DeviceChart api={api.devices} deviceId={featuredDevice.id} key={featuredDevice.id} onUnauthenticated={onUnauthenticated} />
        </> : <div className="fair__chart-empty"><p>Nenhum computador ativo para exibir.</p></div>}
      </div>
      <aside className="fair__feed" aria-label="Atividade recente">
        <h2 className="fair__feed-title">Atividade</h2>
        <Feed events={events} />
      </aside>
    </div>

    <footer className="fair__fleet">
      {active.length === 0 ? <span className="fair__fleet-empty">Adicione um computador para comecar.</span>
        : active.map((device) => <Tile device={device} key={device.id} />)}
    </footer>
    <p className="fair__tagline">Nada acontece nos computadores sem o aval do dono.</p>
  </section>;
}
