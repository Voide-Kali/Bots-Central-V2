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
  "action.approved": "Ação aprovada",
  "action.approval_failed": "Código de aprovação incorreto",
  "action.cancelled": "Ação cancelada",
  "action.dispatched": "Ação entregue ao agente",
  "action.failed": "Ação falhou no agente",
  "action.completed": "Ação concluída pelo agente",
  "action.delivered": "Resultado entregue no Telegram",
  "pin.changed": "PIN criado ou trocado",
  "pin.change_failed": "Senha errada ao trocar o PIN",
  "pin.failed": "PIN incorreto",
  "pin.locked": "PIN travado por 15 minutos",
  "admin.role_changed": "Papel da conta alterado",
  "admin.user_activated": "Conta ativada pelo administrador",
  "sensor.failed_login": "Senha errada no computador"
};

const SOURCES: Readonly<Record<string, string>> = {
  "gdm-password": "tela de login", "gdm-autologin": "tela de login", lightdm: "tela de login", sddm: "tela de login",
  "gnome-screensaver": "tela de bloqueio", "xfce4-screensaver": "tela de bloqueio", kscreenlocker: "tela de bloqueio", "cinnamon-screensaver": "tela de bloqueio",
  login: "login no terminal", sudo: "sudo", su: "su", sshd: "acesso remoto (SSH)", "polkit-agent-helper-1": "pedido de senha do sistema"
};

const KINDS: Readonly<Record<string, string>> = { send_file: "enviar arquivo", lock_screen: "bloquear tela", webcam_photo: "foto da webcam" };

/** "bloquear tela · com PIN", "enviar arquivo relatorio.pdf · tropa"; a dash when the event has nothing to add. */
export function eventDetail(event: AuditEvent): string {
  const what = [event.kind ? KINDS[event.kind] ?? event.kind : null, event.file].filter(Boolean).join(" ");
  const where = event.source ? SOURCES[event.source] ?? event.source : null;
  const parts = [what, event.name, where, event.byPin ? "com PIN" : null].filter((part): part is string => Boolean(part));
  return parts.length > 0 ? parts.join(" · ") : "\u2014";
}

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

  return <>
    <section aria-labelledby="history-heading" className="title-row">
      <div><h1 id="history-heading">Histórico</h1><p className="title-row__sub">Tudo o que aconteceu na sua conta. Este registro não pode ser apagado nem alterado.</p></div>
      <div className="title-row__actions"><button className="button" disabled={state.kind === "loading"} onClick={() => void load()} type="button">Atualizar</button></div>
    </section>
    <section aria-label="Eventos" className="panel">
      <div className="panel__head"><h2>Últimos eventos</h2><p className="panel__meta">{state.kind === "ready" ? `${state.events.length} ${state.events.length === 1 ? "evento" : "eventos"}` : "\u2014"}</p></div>
      {state.kind === "loading" ? <div aria-hidden="true" className="skeleton-rows">{[0, 1, 2, 3].map((row) => <span className="skeleton skeleton--row" key={row} />)}</div> : null}
      {state.kind === "unavailable" ? <p className="panel__body" role="alert">Não foi possível carregar o histórico agora.</p> : null}
      {state.kind === "ready" && state.events.length === 0 ? <p className="panel__body">Nenhuma ação registrada ainda.</p> : null}
      {state.kind === "ready" && state.events.length > 0 ? <ol className="history-list">{state.events.map((event, index) => <li className={event.outcome === "success" ? "history-item" : "history-item history-item--failed"} key={`${event.occurredAt}-${index}`}>
        <time className="num" dateTime={event.occurredAt}>{when(event.occurredAt)}</time>
        <strong>{ACTION_LABELS[event.action] ?? event.action}</strong>
        <span className="history-item__name">{eventDetail(event)}</span>
        <small>por {ACTORS[event.actor] ?? event.actor}{event.outcome === "success" ? "" : " · falhou"}</small>
      </li>)}</ol> : null}
    </section>
  </>;
}
