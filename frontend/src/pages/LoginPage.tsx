import { useState } from "react";
import type { FormEvent, ReactElement } from "react";
import { navigate } from "../app/navigation";
import { useSession } from "../app/session";
import { Brand } from "../components/Brand";

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
    <div className="auth-frame">
      <header className="auth-frame__header"><a aria-label="Aval" className="brand-link" href="/login"><Brand withTagline /></a></header>
      <main className="auth-frame__main">
        <section aria-labelledby="login-title" className="auth-card">
          <h1 id="login-title">Entrar</h1>
          <p className="auth-card__lead">Veja seus computadores e aprove o que a IA pedir para fazer.</p>
          <form className="form" onSubmit={submit} noValidate>
            <div className="form-field"><label htmlFor="login-email">E-mail</label><input autoComplete="email" disabled={bootstrapping} id="login-email" inputMode="email" maxLength={320} name="email" required type="email" /></div>
            <div className="form-field">
              <div className="form-field__row"><label htmlFor="login-password">Senha</label><button aria-label={showPassword ? "Ocultar senha" : "Mostrar senha"} aria-pressed={showPassword} className="link-button" disabled={bootstrapping} onClick={() => setShowPassword((visible) => !visible)} type="button">{showPassword ? "Ocultar" : "Mostrar"}</button></div>
              <input autoComplete="current-password" disabled={bootstrapping} id="login-password" maxLength={1024} name="password" required type={showPassword ? "text" : "password"} />
            </div>
            {error ? <p className="notice notice--error" role="alert">E-mail ou senha incorretos. Se a conta é nova, confirme o e-mail antes de entrar.</p> : null}
            {state.kind === "unavailable" ? <p className="notice notice--error" role="status">O servidor não respondeu. Confira se o Tailscale está ligado e tente de novo.</p> : null}
            <button className="button button--primary" disabled={pending || bootstrapping} type="submit">{bootstrapping ? "Verificando sessão…" : pending ? "Entrando…" : "Entrar"}</button>
            {state.kind === "unavailable" ? <button className="link-button" onClick={() => void retryBootstrap()} type="button">Tentar de novo</button> : null}
          </form>
          <div className="auth-card__links">
            <a href="/register" onClick={(event) => { event.preventDefault(); navigate("/register"); }}>Criar conta</a>
            <a href="/recover" onClick={(event) => { event.preventDefault(); navigate("/recover"); }}>Esqueci minha senha</a>
          </div>
        </section>
      </main>
      <footer className="auth-frame__footer">Nada acontece nos seus computadores sem o seu aval.</footer>
    </div>
  );
}
