import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactElement } from "react";
import type { ApiClient } from "../api";
import type { AuditEvent, Device } from "../api/contracts";
import { UnauthenticatedError } from "../api/errors";
import { Brand } from "./Brand";
import { DeviceChart } from "./DeviceChart";
import { Seal3D } from "./Seal3D";
import { ACTION_LABELS, eventDetail } from "./HistoryPanel";

/*
 * "Modo feira": a read-only wall display for a TV at the science fair. The fleet, one big live
 * chart (cycling through computers, 1 sample/second) and a live feed of events. No controls,
 * no PIN, nothing that changes a computer: it only shows what is already happening.
 */

const DEVICES_EVERY = 8_000;
const EVENTS_EVERY = 5_000;
const FEATURE_EVERY = 60_000;
const MAX_VISIBLE_EVENTS = 8;
const ACTORS: Readonly<Record<string, string>> = { user: "você", device: "computador", system: "sistema", telegram: "Telegram" };
const PUBLIC_KEY = "aval.fair.publicMode";

function readPublicMode(): boolean {
  try {
    return window.localStorage.getItem(PUBLIC_KEY) !== "off";
  } catch {
    return true;
  }
}

function pct(used: number | null, total: number | null): number | null {
  return used !== null && total ? Math.round((used / total) * 100) : null;
}

function when(timestamp: string): string {
  return new Intl.DateTimeFormat("pt-BR", { timeStyle: "medium" }).format(new Date(timestamp));
}

function Tile({ device, name }: { readonly device: Device; readonly name: string }): ReactElement {
  const online = device.status === "online" && device.lifecycleStatus === "active";
  const sample = device.telemetry;
  const cpu = sample?.cpuPercent ?? null;
  const memory = pct(sample?.memoryUsedBytes ?? null, sample?.memoryTotalBytes ?? null);
  return <div className={online ? "fair-tile fair-tile--on" : "fair-tile"}>
    <div className="fair-tile__head">
      <span className="fair-tile__dot" />
      <span className="fair-tile__name">{name}</span>
    </div>
    <div className="fair-tile__cpu num">{cpu !== null ? `${Math.round(cpu)}` : "--"}<small>% CPU</small></div>
    <div className="fair-tile__bars">
      <span className="fair-bar"><span className="fair-bar__fill" style={{ width: `${cpu ?? 0}%` }} /></span>
      <span className="fair-tile__sub num">{memory !== null ? `mem ${memory}%` : "sem medicao"}{sample?.temperatureC != null ? ` - ${Math.round(sample.temperatureC)} C` : ""}</span>
    </div>
  </div>;
}

function Feed({ events, anonymous }: { readonly events: readonly AuditEvent[]; readonly anonymous: boolean }): ReactElement {
  if (events.length === 0) {
    return <p className="fair-feed__empty">Aguardando atividade...</p>;
  }
  return <ul className="fair-feed__list">
    {events.slice(0, MAX_VISIBLE_EVENTS).map((event) => <li className={event.outcome === "failure" || event.outcome === "denied" ? "fair-feed__row fair-feed__row--alert" : "fair-feed__row"} key={`${event.occurredAt}-${event.action}`}>
      <time className="fair-feed__time num" dateTime={event.occurredAt}>{when(event.occurredAt)}</time>
      <span className="fair-feed__what">{ACTION_LABELS[event.action] ?? event.action}</span>
      <span className="fair-feed__detail">{anonymous ? (event.actor in ACTORS ? ACTORS[event.actor] : "") : `${eventDetail(event)}${event.actor in ACTORS ? ` - ${ACTORS[event.actor]}` : ""}`}</span>
    </li>)}
  </ul>;
}

export function FairMode({ api, onUnauthenticated }: { readonly api: ApiClient; onUnauthenticated(): void }): ReactElement {
  const [devices, setDevices] = useState<readonly Device[]>([]);
  const [events, setEvents] = useState<readonly AuditEvent[]>([]);
  const [featured, setFeatured] = useState(0);
  const [now, setNow] = useState(() => new Date());
  const [publicMode, setPublicMode] = useState(readPublicMode);
  const frame = useRef<HTMLDivElement>(null);

  const labels = useMemo(() => {
    const map = new Map<string, string>();
    [...devices].sort((a, b) => a.id.localeCompare(b.id)).forEach((device, index) => map.set(device.id, `Computador ${index + 1}`));
    return map;
  }, [devices]);
  const displayName = useCallback((device: Device): string => (publicMode ? labels.get(device.id) ?? "Computador" : device.name), [publicMode, labels]);

  const togglePublic = useCallback(() => {
    setPublicMode((on) => {
      const next = !on;
      try { window.localStorage.setItem(PUBLIC_KEY, next ? "on" : "off"); } catch { /* per-viewer only */ }
      return next;
    });
  }, []);

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
  const allOnline = active.length > 0 && online === active.length;
  const statusLabel = active.length === 0 ? "SEM COMPUTADORES" : online === 0 ? "NENHUM ONLINE" : allOnline ? "TODOS ONLINE" : "ATENÇÃO";

  function fullscreen(): void {
    const element = frame.current;
    if (!element) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void element.requestFullscreen?.();
  }

  return <section className="fair" ref={frame}>
    <header className="fair__top">
      <div className="fair__brand"><Seal3D /><Brand /></div>
      <div aria-live="polite" className={allOnline ? "fair__status fair__status--online" : "fair__status fair__status--warning"} role="status">
        <span className="fair__status-label">{statusLabel}</span>
        <span className="fair__status-sub num">{online} de {active.length} online</span>
      </div>
      <div className="fair__meta">
        <span className="fair__clock num">{new Intl.DateTimeFormat("pt-BR", { timeStyle: "medium" }).format(now)}</span>
        <button className="button" onClick={togglePublic} type="button" aria-pressed={publicMode}>{publicMode ? "Nomes ocultos" : "Nomes visíveis"}</button>
        <button className="button" onClick={fullscreen} type="button">Tela cheia</button>
      </div>
    </header>

    <div className="fair__grid">
      <div className="fair__chart">
        {featuredDevice ? <>
          <div className="fair__chart-head"><span className="fair__chart-name">{displayName(featuredDevice)}</span><span className="fair__chart-period">Atualização do gráfico</span></div>
          <DeviceChart api={api.devices} deviceId={featuredDevice.id} key={featuredDevice.id} exportable={false} onUnauthenticated={onUnauthenticated} />
        </> : <div className="fair__chart-empty"><p>Nenhum computador ativo para exibir.</p></div>}
      </div>
      <aside className="fair__feed" aria-label="Atividade recente">
        <h2 className="fair__feed-title">Atividade recente</h2>
        <Feed events={events} anonymous={publicMode} />
      </aside>
    </div>

    <footer className="fair__fleet">
      {active.length === 0 ? <span className="fair__fleet-empty">Adicione um computador para comecar.</span>
        : active.map((device) => <Tile device={device} name={displayName(device)} key={device.id} />)}
    </footer>
    <p className="fair__tagline">Nada acontece nos computadores sem o <b>aval</b> do dono.</p>
  </section>;
}
