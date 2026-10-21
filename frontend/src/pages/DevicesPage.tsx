import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ReactElement } from "react";
import type { ApiClient } from "../api";
import { UnauthenticatedError } from "../api";
import type { Device } from "../api/contracts";
import { navigate } from "../app/navigation";
import { useSession } from "../app/session";
import { DeviceList } from "../components/DeviceList";
import { TelegramCard } from "../components/TelegramCard";

type DeviceState =
  | { readonly kind: "idle" }
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly devices: readonly Device[]; readonly lastChecked: string }
  | { readonly kind: "unavailable" };

type Filter = "all" | Device["status"];
const sidebarItems = ["Devices", "Automations", "Notifications", "History", "Security", "Settings"] as const;
const noDevices: readonly Device[] = [];

function SummaryCard({ label, value, detail }: { readonly label: string; readonly value: string; readonly detail: string }): ReactElement {
  return <article className="summary-card"><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>;
}

function Skeletons(): ReactElement {
  return <><section aria-label="Carregando resumo" className="summary-grid summary-grid--loading">{[0, 1, 2, 3].map((item) => <div className="skeleton-card" key={item} />)}</section><section className="device-panel" aria-label="Carregando dispositivos"><div className="device-toolbar"><div><span className="skeleton-line skeleton-line--title" /><span className="skeleton-line" /></div><button disabled type="button">Atualizar</button></div><div className="device-controls"><input aria-label="Buscar dispositivos" disabled placeholder="Buscar por nome, plataforma ou ID" /><div className="filter-group">{[0, 1, 2].map((item) => <button disabled key={item} type="button">Filtro</button>)}</div></div><div className="skeleton-rows">{[0, 1, 2].map((item) => <div className="skeleton-row" key={item} />)}</div></section></>;
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
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [pairing, setPairing] = useState<{ readonly id: string; readonly token: string; readonly expiresAt: string }>();
  const [fingerprintInput, setFingerprintInput] = useState("");
  const [actionBusy, setActionBusy] = useState(false);

  const listRequest = useRef<Promise<void> | undefined>(undefined);
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
      if (reload > 0) setFeedback("Lista de dispositivos atualizada com dados do servidor.");
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
    const expiry = window.setTimeout(() => { setPairing(undefined); setFeedback("O código de pairing expirou."); }, Math.max(0, new Date(pairing.expiresAt).valueOf() - Date.now()));
    const poll = window.setInterval(() => { if (listRequest.current === undefined) setReload((current) => current + 1); }, 5_000);
    return () => { window.clearTimeout(expiry); window.clearInterval(poll); };
  }, [pairing]);

  const devices = deviceState.kind === "ready" ? deviceState.devices : noDevices;
  const online = devices.filter((device) => device.status === "online").length;
  const pending = devices.filter((device) => device.lifecycleStatus === "pending").length;
  const filteredDevices = useMemo(() => {
    const term = search.trim().toLocaleLowerCase();
    return devices.filter((device) => (filter === "all" || device.status === filter) && (term === "" || [device.id, device.name, device.platform].some((value) => value.toLocaleLowerCase().includes(term))));
  }, [devices, filter, search]);

  function refresh(): void { setFeedback(undefined); setReload((current) => current + 1); }
  function clearFilters(): void { setSearch(""); setFilter("all"); }
  function selectDevice(id: string): void { setFingerprintInput(""); setSelectedId((current) => current === id ? undefined : id); }
  async function signOut(): Promise<void> { await logout(); }
  async function startPairing(): Promise<void> {
    if (actionLock.current) return;
    actionLock.current = true;
    setActionBusy(true);
    const generation = sessionGeneration.current;
    try {
      const created = await api.devices.createPairing();
      if (mounted.current && generation === sessionGeneration.current) setPairing({ id: created.pairingId, token: created.pairingToken, expiresAt: created.expiresAt });
    } catch (error) { if (error instanceof UnauthenticatedError) invalidate(); else setFeedback("Não foi possível iniciar o pairing."); }
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
      if (mounted.current) { setPairing(undefined); setFeedback("Pairing cancelado."); }
    } catch (error) {
      if (error instanceof UnauthenticatedError) invalidate();
      else setFeedback("Não foi possível cancelar o pairing no servidor.");
    } finally { actionLock.current = false; if (mounted.current) setActionBusy(false); }
  }
  async function decide(device: Device, decision: "approve" | "reject"): Promise<void> {
    if (actionLock.current || device.lifecycleStatus !== "pending" || device.fingerprint === null || fingerprintInput !== device.fingerprint) return;
    if (decision === "reject" && !window.confirm(`Rejeitar o dispositivo ${device.name}?`)) return;
    actionLock.current = true;
    setActionBusy(true);
    try {
      if (decision === "approve") await api.devices.approve(device.id, device.fingerprint);
      else await api.devices.reject(device.id, device.fingerprint);
      if (!mounted.current) return;
      setPairing(undefined);
      setFingerprintInput("");
      refresh();
    } catch (error) { if (error instanceof UnauthenticatedError) invalidate(); else setFeedback("O servidor não aceitou a decisão."); }
    finally { actionLock.current = false; if (mounted.current) setActionBusy(false); }
  }
  const selectedDevice = devices.find((device) => device.id === selectedId);

  const waitingForSession = session.kind === "bootstrapping";
  const loadingDevices = session.kind === "authenticated" && (deviceState.kind === "idle" || deviceState.kind === "loading");
  const requiresLogin = session.kind === "unauthenticated";
  const unavailable = session.kind === "unavailable" || deviceState.kind === "unavailable";
  const profileName = session.kind === "authenticated" ? session.identity.email : "Perfil";

  return <main className={`device-center ${sidebarOpen ? "device-center--sidebar-open" : ""}`}>
    <header className="device-header"><button aria-controls="device-sidebar" aria-expanded={sidebarOpen} aria-label="Abrir menu" className="sidebar-toggle" onClick={() => setSidebarOpen((open) => !open)} type="button"><span /><span /><span /></button><div className="device-header__context"><span>Espaço / pessoal</span><strong>Dados do servidor</strong><h1>Device Center</h1></div><div className="profile-menu"><button aria-expanded={profileOpen} aria-haspopup="menu" onClick={() => setProfileOpen((open) => !open)} type="button">{profileName}<span aria-hidden="true">⌄</span></button>{profileOpen ? <div role="menu"><button onClick={() => { setFeedback("As preferências do perfil ficam fora deste MVP."); setProfileOpen(false); }} role="menuitem" type="button">Perfil</button><button onClick={() => void signOut()} role="menuitem" type="button">Sair</button></div> : null}</div></header>
    <div className="device-shell"><>{sidebarOpen ? <button aria-label="Fechar menu" className="sidebar-scrim" onClick={() => setSidebarOpen(false)} type="button" /> : null}</><aside className="device-sidebar" id="device-sidebar"><div className="sidebar-brand"><span>bc</span><strong>Bots Central</strong></div><nav aria-label="Navegação do Device Center"><ul>{sidebarItems.map((item) => { const selected = item === "Devices"; return <li key={item}><button aria-current={selected ? "page" : undefined} className={selected ? "sidebar-item sidebar-item--active" : "sidebar-item"} onClick={() => { if (!selected) setFeedback(`${item} estará disponível em uma próxima versão.`); setSidebarOpen(false); }} type="button"><span>{item}</span>{selected ? null : <small>Soon</small>}</button></li>; })}</ul></nav><section aria-label="Cobertura de dispositivos" className="coverage-card"><span>Dispositivos online</span><strong>{deviceState.kind === "ready" ? `${online}/${devices.length}` : "—"}</strong><small>presença informada pelo servidor</small></section></aside>
      <section aria-labelledby="devices-heading" className="device-content">{feedback ? <p className="context-feedback" role="status">{feedback}</p> : null}
        {deviceState.kind === "ready" ? <section aria-label="Resumo de dispositivos" className="summary-grid"><SummaryCard detail="dispositivos" label="Total" value={String(devices.length)} /><SummaryCard detail="presença atual informada" label="Online" value={String(online)} /><SummaryCard detail="aguardando fluxo do servidor" label="Pendentes" value={String(pending)} /><SummaryCard detail="momento da consulta" label="Atualizado" value={localTimestamp(deviceState.lastChecked)} /></section> : null}
        {session.kind === "authenticated" ? <section className="pairing-notice" aria-label="Adicionar dispositivo">
          <h2>Adicionar dispositivo</h2>
          {pairing ? <>
            <p>Use este código no Agent antes da expiração.</p>
            <code style={{ overflowWrap: "anywhere" }}>{pairing.token}</code>
            <p>Expira em <time dateTime={pairing.expiresAt}>{localTimestamp(pairing.expiresAt)}</time></p>
            <button onClick={() => void copyPairing()} type="button">Copiar código</button>
            <button disabled={actionBusy} onClick={() => void cancelPairing()} type="button">Cancelar pairing</button>
          </> : <button disabled={actionBusy} onClick={() => void startPairing()} type="button">Adicionar dispositivo</button>}
        </section> : null}
        {session.kind === "authenticated" && api.telegram ? <TelegramCard api={api.telegram} onUnauthenticated={invalidate} /> : null}
        {waitingForSession || loadingDevices ? <Skeletons /> : null}
        {requiresLogin ? <section className="state-panel"><h2>Acesso necessário</h2><p>Entre para consultar os dispositivos do seu espaço.</p><button onClick={() => navigate("/login")} type="button">Ir para entrar</button></section> : null}
        {unavailable ? <section className="state-panel state-panel--unavailable"><h2>Não foi possível atualizar seus dispositivos.</h2><p>Não foi possível carregar uma atualização do servidor. Tente novamente em alguns instantes.</p><button onClick={session.kind === "unavailable" ? () => void retryBootstrap() : refresh} type="button">Tentar novamente</button></section> : null}
        {deviceState.kind === "ready" ? <><section className="device-panel"><div className="device-toolbar"><div><h2 id="devices-heading">Seus dispositivos</h2><p>Metadados e presença retornados pelo servidor para o seu espaço.</p></div><button onClick={refresh} type="button">Atualizar</button></div><div className="device-controls"><label className="device-search"><span className="sr-only">Buscar dispositivos</span><input onChange={(event) => setSearch(event.target.value)} placeholder="Buscar por nome, plataforma ou ID" type="search" value={search} /></label><div aria-label="Filtros de dispositivos" className="filter-group">{(["all", "online", "offline"] as const).map((nextFilter) => <button aria-pressed={filter === nextFilter} className={filter === nextFilter ? "filter-button filter-button--active" : "filter-button"} key={nextFilter} onClick={() => setFilter(nextFilter)} type="button">{nextFilter === "all" ? "Todos" : nextFilter === "online" ? "Online" : "Offline"}</button>)}</div></div>{filteredDevices.length === 0 ? <section className="empty-state"><h3>Nenhum dispositivo encontrado.</h3><p>{devices.length === 0 ? "O servidor ainda não retornou dispositivos para este espaço." : "Tente outro termo ou limpe os filtros."}</p>{devices.length > 0 ? <button onClick={clearFilters} type="button">Limpar filtros</button> : null}</section> : <DeviceList devices={filteredDevices} onSelect={selectDevice} selectedId={selectedId} />}</section></> : null}
        {session.kind === "authenticated" && selectedDevice?.lifecycleStatus === "pending" ? <section className="pairing-notice" aria-label="Aprovação do dispositivo">
          <h2>Aguardando aprovação</h2>
          {selectedDevice.fingerprint === null ? <p role="alert">O servidor não retornou o fingerprint deste dispositivo. Aprovação e rejeição indisponíveis; atualize a lista.</p> : <>
            <p>O fingerprint deve corresponder exatamente ao exibido pelo Agent.</p>
            <code style={{ overflowWrap: "anywhere", whiteSpace: "pre-wrap" }}>{selectedDevice.fingerprint}</code>
            <label className="form-field">Fingerprint exibido pelo Agent<input autoComplete="off" spellCheck={false} value={fingerprintInput} onChange={(event) => setFingerprintInput(event.target.value)} /></label>
          </>}
          <button disabled={actionBusy || selectedDevice.fingerprint === null || fingerprintInput !== selectedDevice.fingerprint} onClick={() => void decide(selectedDevice, "approve")} type="button">Aprovar dispositivo</button>
          <button disabled={actionBusy || selectedDevice.fingerprint === null || fingerprintInput !== selectedDevice.fingerprint} onClick={() => void decide(selectedDevice, "reject")} type="button">Rejeitar dispositivo</button>
        </section> : null}
      </section></div>
  </main>;
}
