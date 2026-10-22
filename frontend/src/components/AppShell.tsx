import type { PropsWithChildren, ReactElement } from "react";
import type { AppPath } from "../app/navigation";
import { interceptNavigation } from "../app/navigation";

const navigation: ReadonlyArray<{ readonly path: AppPath; readonly label: string }> = [
  { path: "/register", label: "Criar conta" }, { path: "/verify", label: "Verificar e-mail" },
  { path: "/login", label: "Entrar" }, { path: "/devices", label: "Dispositivos" }
];

export function AppShell({ currentPath, children }: PropsWithChildren<{ readonly currentPath: AppPath }>): ReactElement {
  return <div className="app-frame">
    <a className="skip-link" href="#main-content">Pular para o conteúdo</a>
    <header className="site-header">
      <a className="brand" href="/login" onClick={(event) => interceptNavigation(event, "/login")}>
        <span className="brand-mark" aria-hidden="true">BC</span>
        <span><strong>Aval</strong><small>a IA que só age com o seu aval</small></span>
      </a>
      <nav aria-label="Navegação principal"><ul className="nav-list">{navigation.map((item) => <li key={item.path}>
        <a href={item.path} aria-current={currentPath === item.path ? "page" : undefined} onClick={(event) => interceptNavigation(event, item.path)}>{item.label}</a>
      </li>)}</ul></nav>
    </header>
    <main id="main-content" className="content">{children}</main>
    <footer className="site-footer">Aval · Nenhuma ação acontece nos seus computadores sem o seu aval.</footer>
  </div>;
}
