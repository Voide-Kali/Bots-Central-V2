import { createContext, useContext, useMemo, useState } from "react";
import type { PropsWithChildren, ReactElement } from "react";
import type { ApiClient } from "../api";
import type { LoginResult, MockIdentity, ProvisionalLoginRequest } from "../api/contracts";

type SessionState = { readonly kind: "unauthenticated" } | { readonly kind: "mock"; readonly identity: MockIdentity };
interface SessionContextValue {
  readonly state: SessionState;
  login(input: ProvisionalLoginRequest): Promise<LoginResult>;
  logout(): Promise<void>;
}

const SessionContext = createContext<SessionContextValue | undefined>(undefined);

export function SessionProvider({ api, children }: PropsWithChildren<{ readonly api: ApiClient }>): ReactElement {
  const [state, setState] = useState<SessionState>({ kind: "unauthenticated" });
  const value = useMemo<SessionContextValue>(() => ({
    state,
    async login(input) {
      const result = await api.auth.login(input);
      if (result.kind === "mock") setState({ kind: "mock", identity: result });
      return result;
    },
    async logout() {
      await api.auth.logout();
      setState({ kind: "unauthenticated" });
    }
  }), [api, state]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (value === undefined) throw new Error("useSession must be used inside SessionProvider.");
  return value;
}
