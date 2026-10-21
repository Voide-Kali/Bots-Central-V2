import { useEffect, useRef, useState, type ReactElement } from "react";
import type { AuditApi } from "../api/client";
import type { AuditEvent } from "../api/contracts";
import { UnauthenticatedError } from "../api/errors";

/** Same wording as the Telegram /historico command (backend app/audit/events.py LABELS). */
export const ACTION_LABELS: Readonly<Record<string, string>> = {
  "auth.login": "Login no painel",
  "auth.password_reset_requested": "Código de recuperação de senha pedido",
  "auth.password_reset_completed": "Senha redefinida",
  "auth.password_reset_failed": "Tentativa de redefinir senha falhou",
  "device.pairing_created": "Código de pareamento gerado",
  "device.pairing_revoked": "Pareamento cancelado",
  "device.enrolled": "Dispositivo pediu pareamento",
  "device.approved": "Dispositivo aprovado",
  "device.rejected": "Dispositivo rejeitado",
  "telegram.linked": "Telegram vinculado",
  "telegram.unlinked": "Telegram desvinculado",
  "action.requested": "Ação pedida (aguardando aval)",
  "action.approved": "Ação aprovada com código",
  "action.approval_failed": "Código de aprovação incorreto",
  "action.cancelled": "Ação cancelada",
  "action.dispatched": "Ação entregue ao agente",
  "action.failed": "Ação falhou no agente",
  "action.completed": "Ação concluída pelo agente",
  "action.delivered": "Arquivo entregue no Telegram"
};

const ACTORS: Readonly<Record<string, string>> = { user: "você", device: "dispositivo", system: "sistema", telegram: "Telegram" };

type PanelState =
  | { readonly kind: "loading" }
  | { readonly kind: "unavailable" }
  | { readonly kind: "ready"; readonly events: readonly AuditEvent[] };

function when(timestamp: string): string {
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(new Date(timestamp));
}

export function HistoryPanel({ api, onUnauthenticated }: { readonly api: AuditApi; onUnauthenticated(): void }): ReactElement {
  const [state, setState] = useState<PanelState>({ kind: "loading" });
  const mounted = useRef(true);

  async function load(): Promise<void> {
    setState({ kind: "loading" });
    try {
      const events = await api.list(50);
      if (mounted.current) setState({ kind: "ready", events });
    } catch (error) {
      if (error instanceof UnauthenticatedError) onUnauthenticated();
      else if (mounted.current) setState({ kind: "unavailable" });
    }
  }

  useEffect(() => {
    mounted.current = true;
    void load();
    return () => { mounted.current = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  return <section aria-labelledby="history-heading" className="device-panel history-panel">
    <div className="device-toolbar"><div><h2 id="history-heading">Histórico</h2><p>Tudo o que aconteceu na sua conta. O registro não pode ser apagado nem alterado.</p></div><button disabled={state.kind === "loading"} onClick={() => void load()} type="button">Atualizar</button></div>
    {state.kind === "loading" ? <p>Carregando…</p> : null}
    {state.kind === "unavailable" ? <p role="alert">Não foi possível carregar o histórico agora.</p> : null}
    {state.kind === "ready" && state.events.length === 0 ? <p>Nenhuma ação registrada ainda.</p> : null}
    {state.kind === "ready" && state.events.length > 0 ? <ol className="history-list">{state.events.map((event, index) => <li className={event.outcome === "success" ? "history-item" : "history-item history-item--failed"} key={`${event.occurredAt}-${index}`}>
      <time dateTime={event.occurredAt}>{when(event.occurredAt)}</time>
      <strong>{ACTION_LABELS[event.action] ?? event.action}</strong>
      {event.name !== null ? <span>{event.name}</span> : null}
      <small>por {ACTORS[event.actor] ?? event.actor}{event.outcome === "success" ? "" : " · falhou"}</small>
    </li>)}</ol> : null}
  </section>;
}
