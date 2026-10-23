import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ReactElement } from "react";
import type { ApiClient } from "../api";
import { UnauthenticatedError } from "../api";
import type { Device } from "../api/contracts";
import { navigate } from "../app/navigation";
import { useSession } from "../app/session";
import { Brand } from "../components/Brand";
import { DeviceActions } from "../components/DeviceActions";
import { DeviceChart } from "../components/DeviceChart";
import { DeviceList } from "../components/DeviceList";
import { FairMode } from "../components/FairMode";
import { AdminPanel } from "../components/AdminPanel";
import { HistoryPanel } from "../components/HistoryPanel";
import { PinCard } from "../components/PinCard";
import { TelegramCard } from "../components/TelegramCard";

type DeviceState =
  | { readonly kind: "idle" }
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly devices: readonly Device[]; readonly lastChecked: string }
  | { readonly kind: "unavailable" };

type Filter = "all" | Device["status"];
const noDevices: readonly Device[] = [];

function Skeletons(): ReactElement {
  return <section aria-label="Carregando" className="panel panel--loading">
    <div className="panel__head"><span className="skeleton skeleton--title" /><button className="button" disabled type="button">Atualizar</button></div>
    <div className="list-controls"><input aria-label="Buscar computadores" disabled placeholder="Buscar por nome ou sistema" /></div>
    <div className="skeleton-rows">{[0, 1, 2].map((item) => <span className="skeleton skeleton--row" key={item} />)}</div>
  </section>;
}

function localTimestamp(timestamp: string): string {
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(new Date(timestamp));
}

export function DevicesPage({ api }: { readonly api: ApiClient }): ReactElement {
  const { state: session, invalidate, logout, retryBootstrap } = useSession();
  const [deviceState, setDeviceState] = useState<DeviceState>({ kind: "idle" });
  const [reload, setReload] = useState(0);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [selectedId, setSelectedId] = useState<string>();
  const [feedback, setFeedback] = useState<string>();
  const [profileOpen, setProfileOpen] = useState(false);
  const [pairing, setPairing] = useState<{ readonly id: string; readonly token: string; readonly expiresAt: string }>();
  const [fingerprintInput, setFingerprintInput] = useState("");
  const [actionBusy, setActionBusy] = useState(false);
  const [view, setView] = useState<"devices" | "history" | "admin" | "fair">("devices");

  const listRequest = useRef<Promise<void> | undefined>(undefined);
  /** True only for a refresh the person asked for; automatic polling stays silent. */
  const manualRefresh = useRef(false);
  /** Pending devices that already existed when the pairing code was created. */
  const pendingAtPairing = useRef<ReadonlySet<string>>(new Set());
  const actionLock = useRef(false);
  const mounted = useRef(false);
  const sessionGeneration = useRef(0);
  // Layout effect: the generation must change in the same commit that shows the new session
  // state, otherwise a click right after login can capture the stale generation and the
  // pairing response is silently discarded (previously a flaky test).
  useLayoutEffect(() => { sessionGeneration.current += 1; }, [session.kind]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  useEffect(() => {
    let active = true;
    if (session.kind !== "authenticated") {
      setDeviceState({ kind: "idle" });
      setPairing(undefined);
      setFingerprintInput("");
      return () => { active = false; };
    }
    setDeviceState((current) => current.kind === "ready" ? current : { kind: "loading" });
    const previous = listRequest.current;
    const request = (async () => {
      await previous;
      if (!active) return;
      const devices = await api.devices.list();
      if (!active) return;
      setDeviceState({ kind: "ready", devices, lastChecked: new Date().toISOString() });
      if (manualRefresh.current) { manualRefresh.current = false; setFeedback("Lista atualizada."); }
    })().catch((requestError: unknown) => {
      if (!active) return;
      if (requestError instanceof UnauthenticatedError) invalidate();
      else setDeviceState({ kind: "unavailable" });
    });
    listRequest.current = request;
    void request.finally(() => { if (listRequest.current === request) listRequest.current = undefined; });
    return () => { active = false; };
  }, [api, invalidate, reload, session.kind]);

  useEffect(() => {
    if (pairing === undefined) return undefined;
    const expiry = window.setTimeout(() => { setPairing(undefined); setFeedback("O código expirou. Gere outro quando for instalar."); }, Math.max(0, new Date(pairing.expiresAt).valueOf() - Date.now()));
    return () => { window.clearTimeout(expiry); };
  }, [pairing]);

  // Live view: the agents report every 30 s; the panel asks every 10 s (5 s while a
  // computer is being added) and only while the tab is visible.
  useEffect(() => {
    if (session.kind !== "authenticated") return undefined;
    const every = pairing === undefined ? 10_000 : 5_000;
    const poll = window.setInterval(() => {
      if (document.visibilityState === "visible" && listRequest.current === undefined) setReload((current) => current + 1);
    }, every);
    return () => { window.clearInterval(poll); };
  }, [pairing, session.kind]);

  // When the computer being added shows up, close the code and open its approval.
  useEffect(() => {
    if (pairing === undefined || deviceState.kind !== "ready") return;
    const arrived = deviceState.devices.find((device) => device.lifecycleStatus === "pending" && !pendingAtPairing.current.has(device.id));
    if (arrived) { setPairing(undefined); setFingerprintInput(""); setSelectedId(arrived.id); }
  }, [deviceState, pairing]);

  const devices = deviceState.kind === "ready" ? deviceState.devices : noDevices;
  const online = devices.filter((device) => device.status === "online").length;
  const pending = devices.filter((device) => device.lifecycleStatus === "pending").length;
  const filteredDevices = useMemo(() => {
    const term = search.trim().toLocaleLowerCase();
    return devices.filter((device) => (filter === "all" || device.status === filter) && (term === "" || [device.id, device.name, device.platform].some((value) => value.toLocaleLowerCase().includes(term))));
  }, [devices, filter, search]);

  function refresh(): void { manualRefresh.current = true; setFeedback(undefined); setReload((current) => current + 1); }
  function clearFilters(): void { setSearch(""); setFilter("all"); }
  function selectDevice(id: string): void { setFingerprintInput(""); setSelectedId((current) => current === id ? undefined : id); }
  async function signOut(): Promise<void> { await logout(); }
  async function startPairing(): Promise<void> {
    if (actionLock.current) return;
    actionLock.current = true;
    setActionBusy(true);
    const generation = sessionGeneration.current;
    try {
      pendingAtPairing.current = new Set(devices.filter((device) => device.lifecycleStatus === "pending").map((device) => device.id));
      const created = await api.devices.createPairing();
      if (mounted.current && generation === sessionGeneration.current) setPairing({ id: created.pairingId, token: created.pairingToken, expiresAt: created.expiresAt });
    } catch (error) { if (error instanceof UnauthenticatedError) invalidate(); else setFeedback("Não foi possível gerar o código. Tente de novo."); }
    finally { actionLock.current = false; if (mounted.current) setActionBusy(false); }
  }
  async function copyPairing(): Promise<void> {
    if (!pairing || Date.parse(pairing.expiresAt) <= Date.now()) return;
    try { await navigator.clipboard.writeText(pairing.token); setFeedback("Código copiado."); }
    catch { setFeedback("Não foi possível copiar. Selecione o código para copiá-lo."); }
  }
  async function cancelPairing(): Promise<void> {
    if (!pairing || actionLock.current) return;
    actionLock.current = true;
    setActionBusy(true);
    try {
      await api.devices.revokePairing(pairing.id);
      if (mounted.current) { setPairing(undefined); setFeedback("Código cancelado."); }
    } catch (error) {
      if (error instanceof UnauthenticatedError) invalidate();
      else setFeedback("Não foi possível cancelar o código no servidor.");
    } finally { actionLock.current = false; if (mounted.current) setActionBusy(false); }
  }
  async function decide(device: Device, decision: "approve" | "reject"): Promise<void> {
    if (actionLock.current || device.lifecycleStatus !== "pending" || device.fingerprint === null || fingerprintInput !== device.fingerprint) return;
    if (decision === "reject" && !window.confirm(`Recusar o computador ${device.name}? Ele não poderá se conectar.`)) return;
    actionLock.current = true;
    setActionBusy(true);
    try {
      if (decision === "approve") await api.devices.approve(device.id, device.fingerprint);
      else await api.devices.reject(device.id, device.fingerprint);
      if (!mounted.current) return;
      setPairing(undefined);
      setFingerprintInput("");
      refresh();
    } catch (error) { if (error instanceof UnauthenticatedError) invalidate(); else setFeedback("O servidor não aceitou a decisão. Atualize a lista e tente de novo."); }
    finally { actionLock.current = false; if (mounted.current) setActionBusy(false); }
  }
  const selectedDevice = devices.find((device) => device.id === selectedId);
  const pendingDevices = devices.filter((device) => device.lifecycleStatus === "pending");

  const waitingForSession = session.kind === "bootstrapping";
  const loadingDevices = session.kind === "authenticated" && (deviceState.kind === "idle" || deviceState.kind === "loading");
  const requiresLogin = session.kind === "unauthenticated";
  const unavailable = session.kind === "unavailable" || deviceState.kind === "unavailable";
  const authenticated = session.kind === "authenticated";
  const profileName = authenticated ? session.identity.email : "Perfil";
  const isAdmin = authenticated && session.identity.role === "admin" && api.admin !== undefined;
  const tabs: ReadonlyArray<{ readonly id: "devices" | "history" | "admin" | "fair"; readonly label: string }> = [
    { id: "devices", label: "Computadores" },
    ...(api.audit ? [{ id: "history" as const, label: "Histórico" }] : []),
    ...(api.audit ? [{ id: "fair" as const, label: "Modo feira" }] : []),
    ...(isAdmin ? [{ id: "admin" as const, label: "Admin" }] : [])
  ];

  const devicesView = <>
    <section aria-labelledby="devices-title" className="title-row">
      <div>
        <h1 id="devices-title">Seus computadores</h1>
        {deviceState.kind === "ready" ? <p className="title-row__sub" aria-label="Resumo"><span><strong>{online}</strong> de {devices.length} online</span>{pending > 0 ? <span className="title-row__pending"><strong>{pending}</strong> aguardando seu aval</span> : null}<span>atualizado {localTimestamp(deviceState.lastChecked)}</span></p> : null}
      </div>
      <div className="title-row__actions">
        {deviceState.kind === "ready" ? <button className="button" onClick={refresh} type="button">Atualizar</button> : null}
        {authenticated && !pairing ? <button className="button button--primary" disabled={actionBusy} onClick={() => void startPairing()} type="button">Adicionar computador</button> : null}
      </div>
    </section>

    {authenticated && pairing ? <section aria-label="Adicionar computador" className="callout">
      <div className="callout__text">
        <h2>Código para o computador novo</h2>
        <p>No computador que você quer adicionar, rode o instalador do agente e cole este código quando ele pedir.</p>
        <p className="callout__fine">Expira em <time dateTime={pairing.expiresAt}>{localTimestamp(pairing.expiresAt)}</time>. Depois ele aparece aqui como "aguardando seu aval".</p>
      </div>
      <div className="callout__side">
        <code className="callout__code">{pairing.token}</code>
        <div className="callout__actions"><button className="button button--primary" onClick={() => void copyPairing()} type="button">Copiar código</button><button className="button" disabled={actionBusy} onClick={() => void cancelPairing()} type="button">Cancelar código</button></div>
      </div>
    </section> : null}

    {authenticated && selectedDevice?.lifecycleStatus === "pending" ? <section aria-label="Aprovar computador" className="callout callout--approval">
      <div className="callout__text">
        <h2>{selectedDevice.name} quer entrar</h2>
        {selectedDevice.fingerprint === null ? <p role="alert">O servidor não mandou o código de identificação deste computador. Não dá para aprovar com segurança; atualize a lista.</p> : <p>Para ter certeza de que é o seu computador, compare: o agente mostrou um código na tela dele. Ele tem que ser exatamente este:</p>}
      </div>
      <div className="callout__side">
        {selectedDevice.fingerprint === null ? null : <>
          <code className="callout__code">{selectedDevice.fingerprint}</code>
          <div className="form-field"><label htmlFor="fingerprint-check">Código mostrado no computador</label><input autoComplete="off" id="fingerprint-check" spellCheck={false} value={fingerprintInput} onChange={(event) => setFingerprintInput(event.target.value)} /><p className={fingerprintInput !== "" && fingerprintInput === selectedDevice.fingerprint ? "form-field__hint form-field__hint--ok" : "form-field__hint"}>{fingerprintInput === "" ? "Cole aqui o código que aparece no computador." : fingerprintInput === selectedDevice.fingerprint ? "Confere. Pode aprovar." : "Ainda não confere."}</p></div>
        </>}
        <div className="callout__actions">
          <button className="button button--primary" disabled={actionBusy || selectedDevice.fingerprint === null || fingerprintInput !== selectedDevice.fingerprint} onClick={() => void decide(selectedDevice, "approve")} type="button">Aprovar computador</button>
          <button className="button button--danger" disabled={actionBusy || selectedDevice.fingerprint === null || fingerprintInput !== selectedDevice.fingerprint} onClick={() => void decide(selectedDevice, "reject")} type="button">Recusar</button>
        </div>
      </div>
    </section> : null}

    {authenticated && pendingDevices.length > 0 && selectedDevice?.lifecycleStatus !== "pending" ? <p className="notice notice--pending" role="status"><span>{pendingDevices.length === 1 ? `${pendingDevices[0]!.name} está aguardando seu aval.` : `${pendingDevices.length} computadores aguardando seu aval.`}</span> Clique nele na lista para conferir o código e aprovar.</p> : null}

    <div className="workspace__grid">
      <div className="workspace__main">
        {waitingForSession || loadingDevices ? <Skeletons /> : null}
        {requiresLogin ? <section className="panel panel--state"><h2>Acesso necessário</h2><p>Entre para ver seus computadores.</p><button className="button button--primary" onClick={() => navigate("/login")} type="button">Ir para o login</button></section> : null}
        {unavailable ? <section className="panel panel--state panel--warning"><h2>Não foi possível atualizar seus computadores.</h2><p>O servidor não respondeu. Confira se o Tailscale está ligado e tente de novo.</p><button className="button" onClick={session.kind === "unavailable" ? () => void retryBootstrap() : refresh} type="button">Tentar novamente</button></section> : null}
        {deviceState.kind === "ready" ? <section aria-labelledby="devices-heading" className="panel">
          <div className="panel__head"><h2 id="devices-heading">Saúde agora</h2><p className="panel__meta">{devices.length === 1 ? "1 computador" : `${devices.length} computadores`} · medições a cada 30 s, ao vivo ao abrir</p></div>
          {devices.length > 0 ? <div className="list-controls">
            <label className="list-controls__search"><span className="sr-only">Buscar computadores</span><input onChange={(event) => setSearch(event.target.value)} placeholder="Buscar por nome ou sistema" type="search" value={search} /></label>
            <div aria-label="Filtrar" className="segmented" role="group">{(["all", "online", "offline"] as const).map((nextFilter) => <button aria-pressed={filter === nextFilter} key={nextFilter} onClick={() => setFilter(nextFilter)} type="button">{nextFilter === "all" ? "Todos" : nextFilter === "online" ? "Online" : "Offline"}</button>)}</div>
          </div> : null}
          {filteredDevices.length === 0 ? <div className="empty">
            {devices.length === 0 ? <><h3>Nenhum computador ainda.</h3><p>Clique em <strong>Adicionar computador</strong>, instale o agente na máquina e cole o código.</p></> : <><h3>Nada encontrado.</h3><p>Tente outro termo ou limpe os filtros.</p><button className="button" onClick={clearFilters} type="button">Limpar filtros</button></>}
          </div> : <DeviceList devices={filteredDevices} onSelect={selectDevice} renderChart={(device) => device.lifecycleStatus === "active" ? <DeviceChart api={api.devices} deviceId={device.id} onUnauthenticated={invalidate} /> : null} renderActions={(device) => <DeviceActions api={api.devices} pinApi={api.actionPin} deviceId={device.id} onUnauthenticated={invalidate} />} selectedId={selectedId} />}
        </section> : null}
      </div>
      {authenticated && (api.telegram || api.actionPin) ? <aside aria-labelledby="aval-heading" className="workspace__aside">
        <div className="aside__head"><h2 id="aval-heading">Seu aval</h2><p>Nada roda nos computadores sem passar por aqui.</p></div>
        <div className="seal-row"><span aria-hidden="true" className="seal seal--on" /><div><h3>E-mail confirmado</h3><p>Códigos por e-mail só para criar a conta e trocar a senha.</p></div></div>
        {api.actionPin ? <PinCard api={api.actionPin} onUnauthenticated={invalidate} /> : null}
        {api.telegram ? <TelegramCard api={api.telegram} onUnauthenticated={invalidate} /> : null}
      </aside> : null}
    </div>
  </>;

  return <div className="app">
    <a className="skip-link" href="#main-content">Pular para o conteúdo</a>
    <header className="topbar"><div className="topbar__inner">
      <a aria-label="Aval" className="brand-link" href="/devices" onClick={(event) => { event.preventDefault(); setView("devices"); }}><Brand /></a>
      <nav aria-label="Seções" className="tabs">{tabs.map((tab) => <button aria-current={view === tab.id ? "page" : undefined} className="tabs__tab" key={tab.id} onClick={() => { setView(tab.id); setFeedback(undefined); }} type="button">{tab.label}</button>)}</nav>
      <div className="profile-menu"><button aria-expanded={profileOpen} aria-haspopup="menu" className="profile-menu__button" onClick={() => setProfileOpen((open) => !open)} type="button"><span aria-hidden="true" className="profile-menu__initial">{profileName.slice(0, 1)}</span><span className="profile-menu__name">{profileName}</span><span aria-hidden="true" className="profile-menu__caret" /></button>{profileOpen ? <div role="menu"><button onClick={() => void signOut()} role="menuitem" type="button">Sair</button></div> : null}</div>
    </div></header>
    <main className="workspace" id="main-content">
      {feedback ? <p className="notice" role="status">{feedback}</p> : null}
      {view === "admin" && isAdmin && api.admin ? <AdminPanel api={api.admin} onUnauthenticated={invalidate} /> : view === "history" && authenticated && api.audit ? <HistoryPanel api={api.audit} onUnauthenticated={invalidate} /> : view === "fair" && authenticated && api.audit ? <FairMode api={api} onUnauthenticated={invalidate} /> : devicesView}
    </main>
    <footer className="app__footer">Nada acontece nos seus computadores sem o seu aval.</footer>
  </div>;
}
