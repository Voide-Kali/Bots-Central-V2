import { useEffect, useRef, useState, type FormEvent, type ReactElement } from "react";
import type { ActionPinApi } from "../api/client";
import { ApiError, ForbiddenError, UnauthenticatedError } from "../api/errors";

type State = { readonly kind: "loading" } | { readonly kind: "ready"; readonly configured: boolean; readonly lockedUntil: string | null } | { readonly kind: "unavailable" };

export function PinCard({ api, onUnauthenticated }: { readonly api: ActionPinApi; onUnauthenticated(): void }): ReactElement {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ readonly ok: boolean; readonly text: string }>();
  const mounted = useRef(true);

  async function load(): Promise<void> {
    try {
      const status = await api.status();
      if (mounted.current) setState({ kind: "ready", configured: status.configured, lockedUntil: status.lockedUntil });
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

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const pin = String(data.get("pin") ?? "");
    if (!/^[0-9]{6}$/.test(pin)) { setMessage({ ok: false, text: "O PIN tem exatamente 6 números." }); return; }
    if (pin !== String(data.get("pin-confirmation") ?? "")) { setMessage({ ok: false, text: "Os dois PINs estão diferentes." }); return; }
    setBusy(true);
    setMessage(undefined);
    try {
      await api.set(String(data.get("password") ?? ""), pin);
      form.reset();
      setEditing(false);
      setMessage({ ok: true, text: "PIN salvo. Use-o no Telegram para aprovar as ações." });
      await load();
    } catch (error) {
      if (error instanceof UnauthenticatedError) onUnauthenticated();
      else if (error instanceof ForbiddenError) setMessage({ ok: false, text: "Senha da conta incorreta." });
      else if (error instanceof ApiError && error.status === 422) setMessage({ ok: false, text: "PIN fácil demais (ex.: 123456, 000000). Escolha outro." });
      else setMessage({ ok: false, text: "Não foi possível salvar agora. Tente de novo." });
    } finally { if (mounted.current) setBusy(false); }
  }

  return <section aria-label="PIN de aprovação" className="card seal-row">
    <span aria-hidden="true" className={state.kind === "ready" && state.configured && !state.lockedUntil ? "seal seal--on" : "seal"} />
    <div>
    <div className="seal-row__head"><h3>PIN de aprovação</h3>{state.kind === "ready" && state.configured && !editing ? <button className="link-button" onClick={() => { setEditing(true); setMessage(undefined); }} type="button">Trocar PIN</button> : null}</div>
    {state.kind === "loading" ? <p>Carregando…</p> : null}
    {state.kind === "unavailable" ? <><p>Não foi possível consultar o PIN agora.</p><button className="button" onClick={() => void load()} type="button">Tentar novamente</button></> : null}
    {state.kind === "ready" ? <p>
      {state.configured ? "PIN criado. No Telegram, as ações (bloquear, foto, arquivo) pedem esse PIN." : "Crie um PIN de 6 números para aprovar ações no Telegram sem precisar do e-mail."}
      {state.lockedUntil ? <> <strong>Travado</strong> por tentativas erradas até {new Intl.DateTimeFormat("pt-BR", { timeStyle: "short" }).format(new Date(state.lockedUntil))}.</> : null}
    </p> : null}
    {message ? <p className={message.ok ? "card__ok" : "notice notice--error"} role={message.ok ? "status" : "alert"}>{message.text}</p> : null}
    {state.kind === "ready" && !state.configured && !editing ? <button className="button button--primary" onClick={() => { setEditing(true); setMessage(undefined); }} type="button">Criar PIN</button> : null}
    {editing ? <form className="form" onSubmit={(event) => void submit(event)} noValidate>
      <div className="form-field"><label htmlFor="pin-new">PIN (6 números)</label><input autoComplete="off" className="input--code" id="pin-new" inputMode="numeric" maxLength={6} name="pin" type="password" /></div>
      <div className="form-field"><label htmlFor="pin-confirmation">Repita o PIN</label><input autoComplete="off" className="input--code" id="pin-confirmation" inputMode="numeric" maxLength={6} name="pin-confirmation" type="password" /></div>
      <div className="form-field"><label htmlFor="pin-password">Senha da conta</label><input autoComplete="current-password" id="pin-password" name="password" type="password" /></div>
      <div className="callout__actions"><button className="button button--primary" disabled={busy} type="submit">{busy ? "Salvando…" : "Salvar PIN"}</button><button className="button" onClick={() => setEditing(false)} type="button">Cancelar</button></div>
    </form> : null}
    </div>
  </section>;
}
