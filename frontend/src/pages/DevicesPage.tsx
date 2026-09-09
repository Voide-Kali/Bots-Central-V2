import { useEffect, useState } from "react";
import type { ReactElement } from "react";
import type { ApiClient } from "../api";
import { ApiUnavailableError, ContractPendingError, UnauthenticatedError } from "../api";
import type { ProvisionalDevice } from "../api/contracts";
import { navigate } from "../app/navigation";
import { useSession } from "../app/session";
import { DeviceCard } from "../components/DeviceCard";
import { PageStatus } from "../components/PageStatus";
type DeviceState =
  | { readonly kind: "idle" } | { readonly kind: "loading" } | { readonly kind: "ready"; readonly devices: readonly ProvisionalDevice[] }
  | { readonly kind: "empty" } | { readonly kind: "unauthenticated" } | { readonly kind: "unavailable" } | { readonly kind: "contract-pending" };
export function DevicesPage({ api }: { readonly api: ApiClient }): ReactElement {
  const { state: session, logout } = useSession(); const [deviceState, setDeviceState] = useState<DeviceState>({ kind: "idle" }); const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    if (session.kind === "unauthenticated") { setDeviceState({ kind: "unauthenticated" }); return () => { active = false; }; }
    setDeviceState({ kind: "loading" });
    void api.devices.list().then((result) => {
      if (!active) return;
      if (result.kind === "contract-pending") { setDeviceState({ kind: "contract-pending" }); return; }
      setDeviceState(result.devices.length === 0 ? { kind: "empty" } : { kind: "ready", devices: result.devices });
    }).catch((error: unknown) => {
      if (!active) return;
      if (error instanceof UnauthenticatedError) { setDeviceState({ kind: "unauthenticated" }); return; }
      if (error instanceof ApiUnavailableError) { setDeviceState({ kind: "unavailable" }); return; }
      if (error instanceof ContractPendingError) { setDeviceState({ kind: "contract-pending" }); return; }
      setDeviceState({ kind: "unavailable" });
    });
    return () => { active = false; };
  }, [api, reload, session.kind]);
  async function signOut(): Promise<void> { try { await logout(); } catch { setDeviceState({ kind: "unauthenticated" }); } }
  return <section className="devices-page" aria-labelledby="devices-title"><div className="devices-header"><div><p className="eyebrow">Device Center</p><h1 id="devices-title">Seus dispositivos</h1><p>Consulte disponibilidade e versão do agente. Comandos remotos ainda não fazem parte desta tela.</p></div>{session.kind === "mock" ? <div className="session-summary"><span>{session.identity.displayName}</span><button className="secondary-button" type="button" onClick={() => void signOut()}>Sair</button></div> : null}</div>
    {api.adapterName === "mock" ? <p className="adapter-notice" role="note">Dados de demonstração local. Estado visual não concede acesso a recursos no servidor.</p> : null}
    {deviceState.kind === "loading" || deviceState.kind === "idle" ? <PageStatus kind="loading">Carregando dispositivos…</PageStatus> : null}
    {deviceState.kind === "unauthenticated" ? <PageStatus kind="error"><p>Você precisa entrar para consultar dispositivos.</p><button className="text-button" type="button" onClick={() => navigate("/login")}>Ir para entrar</button></PageStatus> : null}
    {deviceState.kind === "unavailable" ? <PageStatus kind="error"><p>A API de dispositivos está indisponível no momento.</p><button className="text-button" type="button" onClick={() => setReload((value) => value + 1)}>Tentar novamente</button></PageStatus> : null}
    {deviceState.kind === "contract-pending" ? <PageStatus kind="notice">A API respondeu, mas o contrato de dispositivos ainda não foi integrado. Nenhum dado desconhecido foi exibido.</PageStatus> : null}
    {deviceState.kind === "empty" ? <PageStatus kind="empty">Ainda não há dispositivos disponíveis para esta conta.</PageStatus> : null}
    {deviceState.kind === "ready" ? <div className="device-grid" aria-label="Lista de dispositivos">{deviceState.devices.map((device) => <DeviceCard key={`${device.name}-${device.platform}`} device={device} />)}</div> : null}
  </section>;
}
