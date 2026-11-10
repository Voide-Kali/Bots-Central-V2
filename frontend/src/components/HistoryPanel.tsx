import { useEffect, useMemo, useRef, useState, type ReactElement } from "react";
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
  return parts.length > 0 ? parts.join(" · ") : "—";
}

const ACTORS: Readonly<Record<string, string>> = { user: "você", device: "dispositivo", system: "sistema", telegram: "Telegram" };
const OUTCOMES: Readonly<Record<string, string>> = { success: "sucesso", failure: "falha", denied: "negado" };
const NO_EVENTS: readonly AuditEvent[] = [];

type PanelState =
  | { readonly kind: "loading" }
  | { readonly kind: "unavailable" }
  | { readonly kind: "ready"; readonly events: readonly AuditEvent[] };

function when(timestamp: string): string {
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(new Date(timestamp));
}

function actorLabel(actor: string): string { return ACTORS[actor] ?? actor; }
function outcomeLabel(outcome: string): string { return OUTCOMES[outcome] ?? outcome; }
function detailText(event: AuditEvent): string { const text = eventDetail(event); return text === "—" ? "" : text; }

/** One CSV cell: everything quoted, inner quotes doubled, so names or details with ; or , are safe. */
function cell(value: string): string { return `"${value.replace(/"/g, '""')}"`; }

/**
 * The visible history as CSV. Semicolon-separated and with a UTF-8 BOM so it opens straight
 * into columns in a pt-BR Excel/LibreOffice; also keeps the exact ISO timestamp for precision.
 * Pure function (no DOM): the download wrapper calls it and tests check the text.
 */
export function toCsv(events: readonly AuditEvent[]): string {
  const header = ["Data e hora", "Evento", "Detalhe", "Por", "Resultado", "Quando (ISO)"];
  const rows = events.map((event) => [
    when(event.occurredAt),
    ACTION_LABELS[event.action] ?? event.action,
    detailText(event),
    actorLabel(event.actor),
    outcomeLabel(event.outcome),
    event.occurredAt
  ]);
  return [header, ...rows].map((columns) => columns.map(cell).join(";")).join("\r\n");
}

/** Save text as a file the person's browser downloads. No-op where the browser APIs are absent. */
function downloadCsv(filename: string, text: string): void {
  try {
    if (typeof URL === "undefined" || typeof URL.createObjectURL !== "function") return;
    const blob = new Blob(["﻿", text], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  } catch { /* download is best-effort */ }
}

export function HistoryPanel({ api, onUnauthenticated }: { readonly api: AuditApi; onUnauthenticated(): void }): ReactElement {
  const [state, setState] = useState<PanelState>({ kind: "loading" });
  const [search, setSearch] = useState("");
  const [onlyFailures, setOnlyFailures] = useState(false);
  const mounted = useRef(true);

  async function load(): Promise<void> {
    setState({ kind: "loading" });
    try {
      const events = await api.list(100);
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

  const all = state.kind === "ready" ? state.events : NO_EVENTS;
  const shown = useMemo(() => {
    const events = state.kind === "ready" ? state.events : NO_EVENTS;
    const term = search.trim().toLocaleLowerCase();
    return events.filter((event) => {
      if (onlyFailures && event.outcome === "success") return false;
      if (term === "") return true;
      const haystack = [ACTION_LABELS[event.action] ?? event.action, detailText(event), actorLabel(event.actor)].join(" ").toLocaleLowerCase();
      return haystack.includes(term);
    });
  }, [state, onlyFailures, search]);

  function exportCsv(): void {
    const stamp = new Date().toISOString().slice(0, 10);
    downloadCsv(`aval-historico-${stamp}.csv`, toCsv(shown));
  }

  return <>
    <section aria-labelledby="history-heading" className="title-row">
      <div><h1 id="history-heading">Histórico</h1><p className="title-row__sub">Tudo o que aconteceu na sua conta. Este registro não pode ser apagado nem alterado.</p></div>
      <div className="title-row__actions">
        <button className="button" disabled={state.kind !== "ready" || shown.length === 0} onClick={exportCsv} type="button">Exportar CSV</button>
        <button className="button" disabled={state.kind === "loading"} onClick={() => void load()} type="button">Atualizar</button>
      </div>
    </section>
    <section aria-label="Eventos" className="panel">
      <div className="panel__head"><h2>Últimos eventos</h2><p className="panel__meta">{state.kind === "ready" ? `${shown.length} de ${all.length} ${all.length === 1 ? "evento" : "eventos"}` : "—"}</p></div>
      {state.kind === "ready" && all.length > 0 ? <div className="list-controls">
        <label className="list-controls__search"><span className="sr-only">Buscar no histórico</span><input onChange={(event) => setSearch(event.target.value)} placeholder="Buscar por evento, detalhe ou autor" type="search" value={search} /></label>
        <div aria-label="Filtrar" className="segmented" role="group">
          <button aria-pressed={!onlyFailures} onClick={() => setOnlyFailures(false)} type="button">Todos</button>
          <button aria-pressed={onlyFailures} onClick={() => setOnlyFailures(true)} type="button">Só falhas</button>
        </div>
      </div> : null}
      {state.kind === "loading" ? <div aria-hidden="true" className="skeleton-rows">{[0, 1, 2, 3].map((row) => <span className="skeleton skeleton--row" key={row} />)}</div> : null}
      {state.kind === "unavailable" ? <p className="panel__body" role="alert">Não foi possível carregar o histórico agora.</p> : null}
      {state.kind === "ready" && all.length === 0 ? <p className="panel__body">Nenhuma ação registrada ainda.</p> : null}
      {state.kind === "ready" && all.length > 0 && shown.length === 0 ? <p className="panel__body">Nenhum evento corresponde ao filtro.</p> : null}
      {state.kind === "ready" && shown.length > 0 ? <ol className="history-list">{shown.map((event, index) => <li className={event.outcome === "success" ? "history-item" : "history-item history-item--failed"} key={`${event.occurredAt}-${index}`}>
        <time className="num" dateTime={event.occurredAt}>{when(event.occurredAt)}</time>
        <strong>{ACTION_LABELS[event.action] ?? event.action}</strong>
        <span className="history-item__name">{eventDetail(event)}</span>
        <small>por {ACTORS[event.actor] ?? event.actor}{event.outcome === "success" ? "" : " · falhou"}</small>
      </li>)}</ol> : null}
    </section>
  </>;
}
