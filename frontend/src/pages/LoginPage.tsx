import { useState } from "react";
import type { FormEvent, ReactElement } from "react";
import type { ApiClient } from "../api";
import type { ProvisionalContractResponse } from "../api/contracts";
import { navigate } from "../app/navigation";
import { useSession } from "../app/session";

function read(form: HTMLFormElement, name: string): string {
  return String(new FormData(form).get(name) ?? "");
}

function isContractPending(value: unknown): value is ProvisionalContractResponse {
  return typeof value === "object" && value !== null && "kind" in value && value.kind === "contract-pending";
}

export function LoginPage({ api }: { readonly api: ApiClient }): ReactElement {
  const { login } = useSession();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(false);
  const [contractPending, setContractPending] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [recoveryNotice, setRecoveryNotice] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const form = event.currentTarget;
    setError(false);
    setContractPending(false);
    setPending(true);
    try {
      const result = await login({ email: read(form, "email"), password: read(form, "password") });
      form.reset();
      if (isContractPending(result)) {
        setContractPending(true);
        return;
      }
      navigate("/devices");
    } catch {
      setError(true);
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="login-screen">
      <section aria-labelledby="login-title" className="login-card">
        <header className="login-branding">
          <div className="login-brand-row">
            <a aria-label="Bots Central" className="login-logo" href="/login">bc</a>
            <div><strong>Bots Central</strong><span>Camada de confiança / v2</span></div>
            <span className="secure-badge">Acesso seguro</span>
          </div>
          <p className="space-label">Espaço pessoal</p>
          <h1 id="login-title"><span>Veja o que está</span><span>seguro e pronto.</span></h1>
          <p className="login-intro">Um espaço claro para confirmar que seus computadores estão presentes, protegidos e disponíveis quando você precisar.</p>
        </header>

        <form className="login-form" onSubmit={submit} noValidate>
          <div className="login-field"><label htmlFor="login-email">E-mail</label><input autoComplete="email" id="login-email" inputMode="email" maxLength={320} name="email" required type="email" /></div>
          <div className="login-field"><div className="login-field__label"><label htmlFor="login-password">Senha</label><button aria-label={showPassword ? "Ocultar senha" : "Mostrar senha"} aria-pressed={showPassword} className="password-toggle" onClick={() => setShowPassword((visible) => !visible)} type="button">{showPassword ? "Ocultar" : "Mostrar"}</button></div><input autoComplete="current-password" id="login-password" maxLength={1024} name="password" required type={showPassword ? "text" : "password"} /></div>
          {error ? <p className="login-feedback login-feedback--error" role="alert">Não foi possível entrar. Confira seus dados e tente novamente.</p> : null}
          {contractPending ? <p className="login-feedback" role="status">O servidor respondeu, mas o contrato de sessão ainda está pendente. Nenhuma sessão foi mantida.</p> : null}
          {recoveryNotice ? <p className="login-feedback" role="status">Recuperação de conta ainda não está disponível nesta versão.</p> : null}
          <button className="login-submit" disabled={pending} type="submit">{pending ? "Entrando no Device Center…" : "Entrar no Device Center"}</button>
          <div className="login-links"><a href="/register" onClick={(event) => { event.preventDefault(); navigate("/register"); }}>Criar conta</a><button onClick={() => setRecoveryNotice(true)} type="button">Esqueci minha senha</button></div>
        </form>
        {api.adapterName === "mock" ? <p className="demo-note">Demonstração local; não representa uma autorização do servidor.</p> : null}
        <footer className="login-footer"><span>Sessão protegida</span><span>BC / 02</span></footer>
      </section>
    </main>
  );
}
