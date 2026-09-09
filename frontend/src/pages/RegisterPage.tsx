import { useState } from "react";
import type { FormEvent, ReactElement } from "react";
import type { ApiClient } from "../api";
import { navigate } from "../app/navigation";
import { FormField } from "../components/FormField";
import { PageStatus } from "../components/PageStatus";
import { AdapterNotice, apiMessage } from "./shared";
function field(form: HTMLFormElement, name: string): string { return String(new FormData(form).get(name) ?? ""); }
export function RegisterPage({ api }: { readonly api: ApiClient }): ReactElement {
  const [pending, setPending] = useState(false); const [message, setMessage] = useState<string>(); const [error, setError] = useState<string>();
  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault(); const form = event.currentTarget; const password = field(form, "password");
    setMessage(undefined); setError(undefined);
    if (password !== field(form, "password-confirmation")) { setError("As senhas não coincidem."); return; }
    setPending(true);
    try { const result = await api.auth.register({ email: field(form, "email"), password }); form.reset(); setMessage(result.message); }
    catch (requestError) { setError(apiMessage(requestError)); } finally { setPending(false); }
  }
  return <section className="auth-layout" aria-labelledby="register-title"><div className="page-intro"><p className="eyebrow">Primeiro acesso</p><h1 id="register-title">Crie sua conta</h1><p>Use um e-mail que você possa verificar. A ativação é concluída somente após a confirmação enviada pelo servidor.</p></div><form className="panel form-panel" onSubmit={submit} noValidate><AdapterNotice api={api} />
    <FormField id="register-email" name="email" type="email" label="E-mail" autoComplete="email" inputMode="email" maxLength={320} required />
    <FormField id="register-password" name="password" type="password" label="Senha" autoComplete="new-password" minLength={15} maxLength={1024} hint="Use pelo menos 15 caracteres. A validação final é feita pelo servidor." required />
    <FormField id="register-password-confirmation" name="password-confirmation" type="password" label="Confirmar senha" autoComplete="new-password" minLength={15} maxLength={1024} required />
    {error === undefined ? null : <PageStatus kind="error">{error}</PageStatus>}{message === undefined ? null : <PageStatus kind="notice"><p>{message}</p><button className="text-button" type="button" onClick={() => navigate("/verify")}>Já tenho o código de verificação</button></PageStatus>}
    <button className="primary-button" type="submit" disabled={pending}>{pending ? "Criando conta…" : "Criar conta"}</button><p className="form-footnote">Já verificou o e-mail? <a href="/login" onClick={(event) => { event.preventDefault(); navigate("/login"); }}>Entrar</a></p>
  </form></section>;
}
