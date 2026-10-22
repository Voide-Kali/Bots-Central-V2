import { useState } from "react";
import type { FormEvent, ReactElement } from "react";
import type { ApiClient } from "../api";
import { ApiError } from "../api";
import { navigate } from "../app/navigation";
import { PageStatus } from "../components/PageStatus";
import { apiMessage } from "./shared";

export const MIN_PASSWORD = 15;
export const PENDING_EMAIL_KEY = "aval.pending-email";

function field(form: HTMLFormElement, name: string): string { return String(new FormData(form).get(name) ?? ""); }

export function RegisterPage({ api }: { readonly api: ApiClient }): ReactElement {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();
  const [password, setPassword] = useState("");
  const long = password.length >= MIN_PASSWORD;

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const form = event.currentTarget;
    const email = field(form, "email").trim();
    setError(undefined);
    if (!long) { setError(`A senha precisa ter pelo menos ${MIN_PASSWORD} caracteres. Uma frase funciona bem.`); return; }
    if (password !== field(form, "password-confirmation")) { setError("As duas senhas estão diferentes."); return; }
    setPending(true);
    try {
      await api.auth.register({ email, password });
      try { window.sessionStorage.setItem(PENDING_EMAIL_KEY, email); } catch { /* optional convenience */ }
      navigate("/verify");
    } catch (requestError) {
      setError(requestError instanceof ApiError && requestError.status === 422
        ? "Confira o e-mail e use uma senha com pelo menos 15 caracteres."
        : apiMessage(requestError));
    } finally { setPending(false); }
  }

  return <section aria-labelledby="register-title" className="auth-card">
    <h1 id="register-title">Criar conta</h1>
    <p className="auth-card__lead">Depois do cadastro, enviamos um código para o seu e-mail.</p>
    <form className="form" onSubmit={submit} noValidate>
      <div className="form-field"><label htmlFor="register-email">E-mail</label><input autoComplete="email" id="register-email" inputMode="email" maxLength={320} name="email" required type="email" /></div>
      <div className="form-field">
        <label htmlFor="register-password">Senha</label>
        <input aria-describedby="register-password-hint" autoComplete="new-password" id="register-password" maxLength={1024} name="password" onChange={(event) => setPassword(event.target.value)} required type="password" value={password} />
        <p className={long ? "form-field__hint form-field__hint--ok" : "form-field__hint"} id="register-password-hint">{long ? "Tamanho ok." : `Pelo menos ${MIN_PASSWORD} caracteres — faltam ${MIN_PASSWORD - password.length}. Ex.: "minha senha do aval 2026".`}</p>
      </div>
      <div className="form-field"><label htmlFor="register-password-confirmation">Repita a senha</label><input autoComplete="new-password" id="register-password-confirmation" maxLength={1024} name="password-confirmation" required type="password" /></div>
      {error === undefined ? null : <PageStatus kind="error">{error}</PageStatus>}
      <button className="button button--primary" disabled={pending} type="submit">{pending ? "Criando conta…" : "Criar conta"}</button>
    </form>
    <div className="auth-card__links"><span>Já tem conta?</span><a href="/login" onClick={(event) => { event.preventDefault(); navigate("/login"); }}>Entrar</a></div>
  </section>;
}
