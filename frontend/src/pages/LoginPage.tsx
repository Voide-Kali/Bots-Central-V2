import { useState } from "react";
import type { FormEvent, ReactElement } from "react";
import { navigate } from "../app/navigation";
import { useSession } from "../app/session";

function read(form: HTMLFormElement, name: string): string {
  return String(new FormData(form).get(name) ?? "");
}

export function LoginPage(): ReactElement {
  const { login, retryBootstrap, state } = useSession();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const bootstrapping = state.kind === "bootstrapping";

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const form = event.currentTarget;
    setError(false);
    setPending(true);
    try {
      await login({ email: read(form, "email"), password: read(form, "password") });
      form.reset();
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
            <a aria-label="Aval" className="login-logo" href="/login">av</a>
            <div><strong>Aval</strong><span>a IA que só age com o seu aval</span></div>
            <span className="secure-badge">Acesso seguro</span>
          </div>
          <p className="space-label">Espaço pessoal</p>
          <h1 id="login-title"><span>Veja o que está</span><span>seguro e pronto.</span></h1>
          <p className="login-intro">Um espaço claro para confirmar que seus computadores estão presentes, protegidos e disponíveis quando você precisar.</p>
        </header>

        <form className="login-form" onSubmit={submit} noValidate>
          <div className="login-field"><label htmlFor="login-email">E-mail</label><input autoComplete="email" disabled={bootstrapping} id="login-email" inputMode="email" maxLength={320} name="email" required type="email" /></div>
          <div className="login-field"><div className="login-field__label"><label htmlFor="login-password">Senha</label><button aria-label={showPassword ? "Ocultar senha" : "Mostrar senha"} aria-pressed={showPassword} className="password-toggle" disabled={bootstrapping} onClick={() => setShowPassword((visible) => !visible)} type="button">{showPassword ? "Ocultar" : "Mostrar"}</button></div><input autoComplete="current-password" disabled={bootstrapping} id="login-password" maxLength={1024} name="password" required type={showPassword ? "text" : "password"} /></div>
          {error ? <p className="login-feedback login-feedback--error" role="alert">Não foi possível entrar. Confira seus dados e tente novamente.</p> : null}
          {state.kind === "unavailable" ? <p className="login-feedback login-feedback--error" role="status">O servidor está indisponível no momento. Você pode tentar novamente.</p> : null}
          <button className="login-submit" disabled={pending || bootstrapping} type="submit">{bootstrapping ? "Verificando sessão…" : pending ? "Entrando no Device Center…" : "Entrar no Device Center"}</button>
          {state.kind === "unavailable" ? <button className="text-button" onClick={() => void retryBootstrap()} type="button">Tentar restaurar sessão</button> : null}
          <div className="login-links"><a href="/register" onClick={(event) => { event.preventDefault(); navigate("/register"); }}>Criar conta</a><a href="/recover" onClick={(event) => { event.preventDefault(); navigate("/recover"); }}>Esqueci minha senha</a></div>
        </form>
        <footer className="login-footer"><span>Sessão protegida</span><span>BC / 02</span></footer>
      </section>
    </main>
  );
}
