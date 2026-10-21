import { useMemo } from "react";
import type { ReactElement } from "react";
import { createApiClient } from "./api";
import { useAppPath } from "./app/navigation";
import { SessionProvider } from "./app/session";
import { AppShell } from "./components/AppShell";
import { DevicesPage } from "./pages/DevicesPage";
import { LoginPage } from "./pages/LoginPage";
import { RecoverPage } from "./pages/RecoverPage";
import { RegisterPage } from "./pages/RegisterPage";
import { VerifyPage } from "./pages/VerifyPage";
function RoutedPage({ path }: { readonly path: ReturnType<typeof useAppPath> }): ReactElement {
  const api = useMemo(() => createApiClient(), []);
  return <SessionProvider api={api}>
    {path === "/login" ? <LoginPage /> : null}
    {path === "/devices" ? <DevicesPage api={api} /> : null}
    {path === "/register" || path === "/verify" || path === "/recover" ? <AppShell currentPath={path}>
      {path === "/register" ? <RegisterPage api={api} /> : null}
      {path === "/recover" ? <RecoverPage api={api} /> : null}
      {path === "/verify" ? <VerifyPage api={api} /> : null}
    </AppShell> : null}
  </SessionProvider>;
}
export function App(): ReactElement { const path = useAppPath(); return <RoutedPage path={path} />; }
