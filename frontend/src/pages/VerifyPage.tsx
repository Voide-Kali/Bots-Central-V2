import { useMemo, useState } from "react";
import type { FormEvent, ReactElement } from "react";
import type { ApiClient } from "../api";
import { navigate } from "../app/navigation";
import { PageStatus } from "../components/PageStatus";
import { PENDING_EMAIL_KEY } from "./RegisterPage";
import { apiMessage } from "./shared";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const UUID_INSIDE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

/** Accepts the bare identifier or the whole "Confirmar e-mail" link pasted from the message. */
export function challengeFrom(text: string): string | undefined {
  return UUID_INSIDE.exec(text)?.[0].toLowerCase();
}

function field(form: HTMLFormElement, name: string): string { return String(new FormData(form).get(name) ?? "").trim(); }

function linkedChallenge(): string | undefined {
  const value = new URLSearchParams(window.location.search).get("challenge") ?? "";
  return UUID.test(value) ? value : undefined;
}

function pendingEmail(): string | undefined {
  try { return window.sessionStorage.getItem(PENDING_EMAIL_KEY) ?? undefined; } catch { return undefined; }
}

export function VerifyPage({ api }: { readonly api: ApiClient }): ReactElement {
  const challenge = useMemo(linkedChallenge, []);
  const email = useMemo(pendingEmail, []);
  const [pending, setPending] = useState(false);
  const [verified, setVerified] = useState(false);
  const [error, setError] = useState<string>();
  const [resent, setResent] = useState(false);

  async function resend(): Promise<void> {
    if (email === undefined || api.auth.resendVerification === undefined) return;
    setError(undefined);
    try { await api.auth.resendVerification(email); setResent(true); }
    catch (requestError) { setError(apiMessage(requestError)); }
  }

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const form = event.currentTarget;
    setError(undefined);
    const challengeId = challenge ?? challengeFrom(field(form, "challenge-id"));
    const code = field(form, "code");
    if (challengeId === undefined) { setError("Falta o link do e-mail. Abra o botão Confirmar e-mail na mensagem, ou cole aqui o link dele (ou o Identificador que aparece no fim)."); return; }
    if (!/^[0-9]{4} ?[0-9]{4}$/.test(code)) { setError("O código tem 8 números, como 1234 5678."); return; }
    setPending(true);
    try {
      const result = await api.auth.consumeVerificationCode({ challenge_id: challengeId, code });
      if (result.verified) {
        form.reset();
        setVerified(true);
        try { window.sessionStorage.removeItem(PENDING_EMAIL_KEY); } catch { /* optional */ }
      } else setError("Código incorreto ou expirado. Confira o e-mail mais recente.");
    } catch (requestError) { setError(apiMessage(requestError)); } finally { setPending(false); }
  }

  if (verified) {
    return <section aria-labelledby="verify-title" className="auth-card">
      <h1 id="verify-title">E-mail confirmado</h1>
      <p className="auth-card__lead">Sua conta está ativa. Agora é só entrar.</p>
      <button className="button button--primary" onClick={() => navigate("/login")} type="button">Ir para o login</button>
    </section>;
  }

  return <section aria-labelledby="verify-title" className="auth-card">
    <h1 id="verify-title">Confirme seu e-mail</h1>
    {challenge
      ? <p className="auth-card__lead">Digite o código de 8 números que chegou junto com este link.</p>
      : <p className="auth-card__lead">{email ? <>Enviamos um e-mail para <strong>{email}</strong>. </> : null}Abra o botão <strong>Confirmar e-mail</strong> que está nele: a página abre já preparada e você só digita o código.</p>}
    <form className="form" onSubmit={submit} noValidate>
      {challenge ? null : <div className="form-field"><label htmlFor="challenge-id">Link do e-mail ou identificador</label><input autoComplete="off" id="challenge-id" name="challenge-id" spellCheck={false} type="text" /><p className="form-field__hint">Se não conseguir abrir o botão, copie o link dele e cole aqui, ou cole o Identificador que aparece no fim do e-mail.</p></div>}
      <div className="form-field"><label htmlFor="verification-code">Código de 8 números</label><input autoComplete="one-time-code" className="input--code" id="verification-code" inputMode="numeric" maxLength={9} name="code" pattern="[0-9]{4} ?[0-9]{4}" placeholder="1234 5678" required type="text" /></div>
      {error === undefined ? null : <PageStatus kind="error">{error}</PageStatus>}
      <button className="button button--primary" disabled={pending} type="submit">{pending ? "Confirmando…" : "Confirmar e-mail"}</button>
    </form>
    <p className="auth-card__fine">Não chegou? Olhe o spam.{email && api.auth.resendVerification ? <> {resent ? "Pedimos um novo código — use o e-mail mais recente." : <button className="link-button" onClick={() => void resend()} type="button">Enviar outro código</button>}</> : null}</p>
  </section>;
}
