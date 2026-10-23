import { useState } from "react";
import type { FormEvent, ReactElement } from "react";
import type { ApiClient } from "../api";
import { ApiError } from "../api";
import { navigate } from "../app/navigation";
import { FormField } from "../components/FormField";
import { PageStatus } from "../components/PageStatus";
import { apiMessage } from "./shared";

function field(form: HTMLFormElement, name: string): string { return String(new FormData(form).get(name) ?? ""); }

export function RecoverPage({ api }: { readonly api: ApiClient }): ReactElement {
  const [email, setEmail] = useState<string>();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();
  const [done, setDone] = useState(false);
  const reset = api.passwordReset;

  async function requestCode(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!reset) return;
    const value = field(event.currentTarget, "email").trim();
    setError(undefined); setPending(true);
    try { await reset.request(value); setEmail(value); }
    catch (requestError) { setError(apiMessage(requestError)); }
    finally { setPending(false); }
  }

  async function confirm(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!reset || email === undefined) return;
    const form = event.currentTarget;
    const password = field(form, "password");
    setError(undefined);
    if (password !== field(form, "password-confirmation")) { setError("As senhas não coincidem."); return; }
    setPending(true);
    try {
      await reset.confirm({ email, code: field(form, "code").replace(/\s/g, ""), newPassword: password });
      form.reset(); setDone(true);
    } catch (requestError) {
      setError(requestError instanceof ApiError && requestError.status === 422
        ? "A senha nova não atende à política: use pelo menos 15 caracteres."
        : requestError instanceof ApiError && requestError.status === 400
          ? "Código inválido ou expirado. Confira o e-mail ou peça um novo código."
          : apiMessage(requestError));
    } finally { setPending(false); }
  }

  if (!reset) return <section aria-labelledby="recover-title" className="auth-card">
    <h1 id="recover-title">Trocar a senha</h1>
    <PageStatus kind="error">A recuperação de senha não está disponível agora. Fale com quem administra o Aval.</PageStatus>
    <p className="auth-card__links"><a href="/login" onClick={(event) => { event.preventDefault(); navigate("/login"); }}>Voltar para o login</a></p>
  </section>;

  return <section className="auth-card" aria-labelledby="recover-title">
    <h1 id="recover-title">Trocar a senha</h1>
    <p className="auth-card__lead">Enviamos um código de 8 números para o e-mail da conta. Ele vale 15 minutos. Ao trocar a senha, você sai de todos os aparelhos.</p>
    {done ? <div className="form"><PageStatus kind="notice">Senha alterada. Entre de novo com a senha nova.</PageStatus>
      <button className="button button--primary" onClick={() => navigate("/login")} type="button">Ir para o login</button></div>
    : email === undefined ? <form className="form" onSubmit={requestCode} noValidate>
      <FormField id="recover-email" name="email" type="email" label="E-mail da conta" autoComplete="email" inputMode="email" maxLength={320} required />
      {error === undefined ? null : <PageStatus kind="error">{error}</PageStatus>}
      <button className="button button--primary" disabled={pending} type="submit">{pending ? "Enviando…" : "Enviar código"}</button>
      <p className="auth-card__links">Lembrou? <a href="/login" onClick={(event) => { event.preventDefault(); navigate("/login"); }}>Entrar</a></p>
    </form>
    : <form className="form" onSubmit={confirm} noValidate>
      <PageStatus kind="notice">Se a conta existir, um código foi enviado para {email}.</PageStatus>
      <FormField id="recover-code" name="code" label="Código de 8 dígitos" autoComplete="one-time-code" inputMode="numeric" maxLength={9} required />
      <FormField id="recover-password" name="password" type="password" label="Senha nova" autoComplete="new-password" minLength={15} maxLength={1024} hint="Use pelo menos 15 caracteres." required />
      <FormField id="recover-password-confirmation" name="password-confirmation" type="password" label="Confirmar senha nova" autoComplete="new-password" minLength={15} maxLength={1024} required />
      {error === undefined ? null : <PageStatus kind="error">{error}</PageStatus>}
      <button className="button button--primary" disabled={pending} type="submit">{pending ? "Alterando…" : "Alterar senha"}</button>
      <p className="auth-card__links"><button className="text-button" onClick={() => { setEmail(undefined); setError(undefined); }} type="button">Pedir outro código</button></p>
    </form>}
  </section>;
}
