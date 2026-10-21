import type { PropsWithChildren, ReactElement } from "react";
import type { AppPath } from "../app/navigation";
import { interceptNavigation } from "../app/navigation";
import { Brand } from "./Brand";

export function AppShell({ children }: PropsWithChildren<{ readonly currentPath: AppPath }>): ReactElement {
  return <div className="auth-frame">
    <a className="skip-link" href="#main-content">Pular para o conteúdo</a>
    <header className="auth-frame__header">
      <a aria-label="Aval — entrar" className="brand-link" href="/login" onClick={(event) => interceptNavigation(event, "/login")}><Brand withTagline /></a>
    </header>
    <main id="main-content" className="auth-frame__main">{children}</main>
    <footer className="auth-frame__footer">Nada acontece nos seus computadores sem o seu aval.</footer>
  </div>;
}
