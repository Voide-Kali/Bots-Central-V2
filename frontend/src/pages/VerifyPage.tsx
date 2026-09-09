import { useState } from "react";
import type { FormEvent, ReactElement } from "react";
import type { ApiClient } from "../api";
import { navigate } from "../app/navigation";
import { FormField } from "../components/FormField";
import { PageStatus } from "../components/PageStatus";
import { AdapterNotice, apiMessage } from "./shared";
function field(form: HTMLFormElement, name: string): string { return String(new FormData(form).get(name) ?? "").trim(); }
export function VerifyPage({ api }: { readonly api: ApiClient }): ReactElement {
  const [pending, setPending] = useState(false); const [verified, setVerified] = useState(false); const [error, setError] = useState<string>();
  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault(); const form = event.currentTarget; setError(undefined); setVerified(false); setPending(true);
    try { const result = await api.auth.consumeVerificationCode({ challenge_id: field(form, "challenge-id"), code: field(form, "code") }); if (result.verified) { form.reset(); setVerified(true); } else setError("Não foi possível verificar este código. Solicite um novo código se necessário."); }
    catch (requestError) { setError(apiMessage(requestError)); } finally { setPending(false); }
  }
  return <section className="auth-layout" aria-labelledby="verify-title"><div className="page-intro"><p className="eyebrow">Ativação de conta</p><h1 id="verify-title">Verifique seu e-mail</h1><p>Informe o identificador do desafio e o código enviados pelo e-mail. Eles são usados apenas para esta solicitação e não são salvos neste navegador.</p></div><form className="panel form-panel" onSubmit={submit} noValidate><AdapterNotice api={api} />
    <FormField id="challenge-id" name="challenge-id" type="text" label="Identificador do desafio" autoComplete="off" spellCheck={false} required />
    <FormField id="verification-code" name="code" type="text" label="Código de verificação" autoComplete="one-time-code" inputMode="numeric" maxLength={9} pattern="[0-9]{4} ?[0-9]{4}" hint="Use os oito dígitos recebidos. Um espaço no meio é aceito." required />
    {error === undefined ? null : <PageStatus kind="error">{error}</PageStatus>}{verified ? <PageStatus kind="notice"><p>E-mail verificado. Agora você pode entrar.</p><button className="text-button" type="button" onClick={() => navigate("/login")}>Ir para entrar</button></PageStatus> : null}
    <button className="primary-button" type="submit" disabled={pending}>{pending ? "Verificando…" : "Verificar e-mail"}</button>
  </form></section>;
}
