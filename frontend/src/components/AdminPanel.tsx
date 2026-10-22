import { useEffect, useRef, useState, type ReactElement } from "react";
import type { AdminApi } from "../api/client";
import type { AdminEvent, AdminFailure, AdminOverview, AdminUser } from "../api/contracts";
import { UnauthenticatedError } from "../api/errors";
import { ACTION_LABELS } from "./HistoryPanel";

type Data = { readonly overview: AdminOverview; readonly users: readonly AdminUser[]; readonly failures: readonly AdminFailure[]; readonly events: readonly AdminEvent[] };
type State = { readonly kind: "loading" } | { readonly kind: "ready"; readonly data: Data } | { readonly kind: "unavailable" };

const STATUS: Readonly<Record<string, string>> = { active: "ativa", pending_verification: "aguardando e-mail", locked: "travada", disabled: "desativada" };
const ACTIONS: Readonly<Record<string, string>> = { send_file: "enviar arquivo", lock_screen: "bloquear tela", webcam_photo: "foto" };
const OUTCOMES: Readonly<Record<string, string>> = { failed: "falhou", denied: "negado", expired: "expirou" };

function when(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(parsed);
}

function sum(values: Readonly<Record<string, number>>): number {
  return Object.values(values).reduce((total, value) => total + value, 0);
}

export function AdminPanel({ api, onUnauthenticated }: { readonly api: AdminApi; onUnauthenticated(): void }): ReactElement {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [busy, setBusy] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const mounted = useRef(true);

  async function load(): Promise<void> {
    try {
      const [overview, users, failures, events] = await Promise.all([api.overview(), api.users(), api.failures(), api.events()]);
      if (mounted.current) setState({ kind: "ready", data: { overview, users, failures, events } });
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

  async function activate(user: AdminUser): Promise<void> {
    if (!window.confirm(`Ativar a conta ${user.email} sem o código do e-mail?`)) return;
    setBusy(user.id);
    try { await api.activate(user.id); setNotice(`Conta ${user.email} ativada.`); await load(); }
    catch (error) { if (error instanceof UnauthenticatedError) onUnauthenticated(); else setNotice("Não foi possível ativar agora."); }
    finally { if (mounted.current) setBusy(undefined); }
  }

  if (state.kind === "loading") return <div className="admin">
    <section aria-labelledby="admin-title" className="title-row">
      <div><h1 id="admin-title">Administração</h1><p className="title-row__sub">Visível só para administradores. Não mostra arquivos, fotos, PINs nem senhas.</p></div>
      <div className="title-row__actions"><button className="button" disabled type="button">Atualizar</button></div>
    </section>
    <section aria-label="Carregando administração" className="panel"><div aria-hidden="true" className="skeleton-rows">{[0, 1, 2, 3].map((row) => <span className="skeleton skeleton--row" key={row} />)}</div></section>
  </div>;
  if (state.kind === "unavailable") return <section className="panel panel--state panel--warning"><h2>Administração indisponível</h2><p>O servidor não respondeu.</p><button className="button" onClick={() => void load()} type="button">Tentar novamente</button></section>;
  const { overview, users, failures, events } = state.data;
  const failedRecently = (overview.commands24h.failed ?? 0) + (overview.commands24h.denied ?? 0);

  return <div className="admin">
    <section aria-labelledby="admin-title" className="title-row">
      <div><h1 id="admin-title">Administração</h1><p className="title-row__sub">Visível só para administradores. Não mostra arquivos, fotos, PINs nem senhas.</p></div>
      <div className="title-row__actions"><button className="button" onClick={() => void load()} type="button">Atualizar</button></div>
    </section>
    {notice ? <p className="notice" role="status">{notice}</p> : null}
    <section aria-label="Saúde do sistema" className="panel">
      <dl className="admin__stats">
        <div><dt>Contas</dt><dd>{sum(overview.users)}</dd><small>{overview.users.pending_verification ?? 0} aguardando e-mail</small></div>
        <div><dt>Computadores online</dt><dd>{overview.devicesOnline} de {overview.devicesByLifecycle.active ?? 0}</dd><small>{overview.devicesByLifecycle.pending ?? 0} aguardando aprovação</small></div>
        <div><dt>Ações nas últimas 24 h</dt><dd>{sum(overview.commands24h)}</dd><small className={failedRecently ? "admin__bad" : undefined}>{failedRecently} com falha ou negadas</small></div>
        <div><dt>Telegram vinculado</dt><dd>{overview.telegramLinks}</dd><small>verificado {when(overview.checkedAt)}</small></div>
      </dl>
    </section>

    <section aria-labelledby="admin-users" className="panel">
      <div className="panel__head"><h2 id="admin-users">Contas</h2><p className="panel__meta">{users.length} no total</p></div>
      <div className="table-scroll"><table className="admin__table">
        <thead><tr><th>E-mail</th><th>Situação</th><th className="num">Computadores</th><th>Telegram</th><th>PIN</th><th className="num">Criada</th><th /></tr></thead>
        <tbody>{users.map((user) => <tr key={user.id}>
          <td className="cell-id">{user.email}{user.role === "admin" ? <small> admin</small> : null}</td>
          <td>{user.status === "active" ? STATUS.active : <span className={user.status === "pending_verification" ? "badge badge--pending" : "badge badge--revoked"}>{STATUS[user.status] ?? user.status}</span>}</td>
          <td className="num">{user.devices}</td>
          <td>{user.telegram ? "sim" : "não"}</td>
          <td>{user.pin ? "sim" : "não"}</td>
          <td className="num">{when(user.createdAt)}</td>
          <td>{user.status === "pending_verification" ? <button className="button" disabled={busy === user.id} onClick={() => void activate(user)} type="button">Ativar conta</button> : null}</td>
        </tr>)}</tbody>
      </table></div>
    </section>

    <section aria-labelledby="admin-failures" className="panel">
      <div className="panel__head"><h2 id="admin-failures">Ações que não deram certo</h2><p className="panel__meta">{failures.length === 0 ? "nenhuma" : `${failures.length} recentes`}</p></div>
      {failures.length === 0 ? <p className="panel__body">Nenhuma falha recente.</p> : <div className="table-scroll"><table className="admin__table">
        <thead><tr><th>Quando</th><th>Conta</th><th>Computador</th><th>Ação</th><th>Resultado</th><th>Erro</th></tr></thead>
        <tbody>{failures.map((item, index) => <tr key={`${item.at}-${index}`}><td>{when(item.at)}</td><td>{item.user}</td><td>{item.device}</td><td>{ACTIONS[item.action] ?? item.action}</td><td><span className="badge badge--failed">{OUTCOMES[item.status] ?? item.status}</span></td><td className="cell-mono">{item.error ?? "\u2014"}</td></tr>)}</tbody>
      </table></div>}
    </section>

    <section aria-labelledby="admin-events" className="panel">
      <div className="panel__head"><h2 id="admin-events">Histórico de todos</h2><p className="panel__meta">{events.length === 1 ? "1 evento" : `${events.length} eventos`}</p></div>
      <ol className="history-list">{events.map((event, index) => <li className={event.outcome === "success" ? "history-item" : "history-item history-item--failed"} key={`${event.occurredAt}-${index}`}>
        <time className="num" dateTime={event.occurredAt}>{when(event.occurredAt)}</time>
        <strong>{ACTION_LABELS[event.action] ?? event.action}</strong>
        <span className="history-item__name">{event.user ?? "sistema"}</span>
        <small>{event.outcome === "success" ? "ok" : "falhou"}</small>
      </li>)}</ol>
    </section>
  </div>;
}
