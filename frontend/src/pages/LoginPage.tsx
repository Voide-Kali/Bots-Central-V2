import { useState } from "react";
import type { FormEvent, ReactElement } from "react";
import type { ApiClient } from "../api";
import type { ProvisionalContractResponse } from "../api/contracts";
import { navigate } from "../app/navigation";
import { useSession } from "../app/session";
import { FormField } from "../components/FormField";
import { PageStatus } from "../components/PageStatus";
import { AdapterNotice, apiMessage } from "./shared";
function read(form: HTMLFormElement, name: string): string { return String(new FormData(form).get(name) ?? ""); }
function isContractPending(value: unknown): value is ProvisionalContractResponse { return typeof value === "object" && value !== null && "kind" in value && value.kind === "contract-pending"; }
export function LoginPage({ api }: { readonly api: ApiClient }): ReactElement {
  const { login } = useSession(); const [pending, setPending] = useState(false); const [error, setError] = useState<string>(); const [contractPending, setContractPending] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault(); const form = event.currentTarget; setError(undefined); setContractPending(false); setPending(true);
    try { const result = await login({ email: read(form, "email"), password: read(form, "password") }); form.reset(); if (isContractPending(result)) { setContractPending(true); return; } navigate("/devices"); }
    catch (requestError) { setError(apiMessage(requestError)); } finally { setPending(false); }
  }
  return <section className="auth-layout" aria-labelledby="login-title"><div className="page-intro"><p className="eyebrow">Acesso à central</p><h1 id="login-title">Entre na sua conta</h1><p>A autenticação é confirmada pelo servidor. Esta tela não atribui permissões nem habilita operações sobre dispositivos.</p></div><form className="panel form-panel" onSubmit={submit} noValidate><AdapterNotice api={api} />
    <FormField id="login-email" name="email" type="email" label="E-mail" autoComplete="email" inputMode="email" maxLength={320} required />
    <FormField id="login-password" name="password" type="password" label="Senha" autoComplete="current-password" maxLength={1024} required />
    {error === undefined ? null : <PageStatus kind="error">{error}</PageStatus>}{contractPending ? <PageStatus kind="notice">O servidor respondeu, mas o contrato de sessão ainda não foi integrado a esta interface. Nenhuma sessão foi mantida.</PageStatus> : null}
    <button className="primary-button" type="submit" disabled={pending}>{pending ? "Entrando…" : "Entrar"}</button><p className="form-footnote">Ainda não tem conta? <a href="/register" onClick={(event) => { event.preventDefault(); navigate("/register"); }}>Criar conta</a></p>
  </form></section>;
}
