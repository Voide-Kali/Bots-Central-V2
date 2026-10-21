import { useEffect, useRef, useState, type ReactElement } from "react";
import type { TelegramApi } from "../api/client";
import type { TelegramLinkCode } from "../api/contracts";
import { UnauthenticatedError } from "../api/errors";

type CardState =
  | { readonly kind: "loading" }
  | { readonly kind: "unavailable" }
  | { readonly kind: "unlinked"; readonly botUsername: string | null; readonly code?: TelegramLinkCode }
  | { readonly kind: "linked"; readonly botUsername: string | null };

export function TelegramCard({ api, onUnauthenticated }: { readonly api: TelegramApi; onUnauthenticated(): void }): ReactElement {
  const [state, setState] = useState<CardState>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const mounted = useRef(true);

  async function load(): Promise<void> {
    try {
      const status = await api.status();
      if (mounted.current) setState(status.linked ? { kind: "linked", botUsername: status.botUsername } : { kind: "unlinked", botUsername: status.botUsername });
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

  async function run(action: () => Promise<void>): Promise<void> {
    if (busy) return;
    setBusy(true);
    try { await action(); }
    catch (error) {
      if (error instanceof UnauthenticatedError) onUnauthenticated();
      else if (mounted.current) setState({ kind: "unavailable" });
    } finally { if (mounted.current) setBusy(false); }
  }

  const generate = (): Promise<void> => run(async () => {
    const code = await api.createLinkCode();
    if (mounted.current) setState({ kind: "unlinked", botUsername: code.botUsername, code });
  });
  const unlink = (): Promise<void> => run(async () => {
    if (!window.confirm("Desvincular o Telegram? Você deixará de receber alertas.")) return;
    await api.unlink();
    await load();
  });

  return <section aria-label="Telegram" className="pairing-notice telegram-card">
    <h2>Telegram</h2>
    {state.kind === "loading" ? <p>Carregando…</p> : null}
    {state.kind === "unavailable" ? <><p>Não foi possível consultar o Telegram agora.</p><button onClick={() => void load()} type="button">Tentar novamente</button></> : null}
    {state.kind === "linked" ? <>
      <p>✅ Telegram vinculado. Alertas e o comando /status já funcionam.</p>
      <button disabled={busy} onClick={() => void unlink()} type="button">Desvincular</button>
    </> : null}
    {state.kind === "unlinked" ? <>
      {state.code ? <>
        <p>Envie este código ao bot{state.botUsername ? <> <strong>@{state.botUsername}</strong></> : null} antes de <time dateTime={state.code.expiresAt}>{new Intl.DateTimeFormat("pt-BR", { timeStyle: "short" }).format(new Date(state.code.expiresAt))}</time>:</p>
        <code>/vincular {state.code.code}</code>
        {state.botUsername ? <p><a href={`https://t.me/${state.botUsername}?start=${state.code.code}`} rel="noreferrer" target="_blank">Abrir no Telegram</a></p> : null}
        <button disabled={busy} onClick={() => void load()} type="button">Já enviei</button>
      </> : <>
        <p>Receba alertas e consulte seus dispositivos pelo Telegram.</p>
        <button disabled={busy} onClick={() => void generate()} type="button">Vincular Telegram</button>
      </>}
    </> : null}
  </section>;
}
