import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { PropsWithChildren, ReactElement } from "react";
import type { ApiClient } from "../api";
import { ApiUnavailableError, UnauthenticatedError } from "../api";
import type { AuthenticatedUser, LoginRequest } from "../api/contracts";
import { accessTokenStore } from "../api/memoryAccessToken";

type SessionState =
  | { readonly kind: "bootstrapping" }
  | { readonly kind: "unauthenticated" }
  | { readonly kind: "unavailable" }
  | { readonly kind: "authenticated"; readonly identity: AuthenticatedUser };

interface SessionContextValue {
  readonly state: SessionState;
  login(input: LoginRequest): Promise<void>;
  logout(): Promise<void>;
  invalidate(): void;
  retryBootstrap(): Promise<void>;
}

const SessionContext = createContext<SessionContextValue | undefined>(undefined);

export function SessionProvider({ api, children }: PropsWithChildren<{ readonly api: ApiClient }>): ReactElement {
  const [state, setState] = useState<SessionState>({ kind: "bootstrapping" });
  const bootstrapStarted = useRef(false);
  const bootstrapInFlight = useRef<Promise<void> | undefined>(undefined);

  const invalidate = useCallback((): void => {
    accessTokenStore.clear();
    setState({ kind: "unauthenticated" });
  }, []);

  const retryBootstrap = useCallback(async (): Promise<void> => {
    const inFlight = bootstrapInFlight.current;
    if (inFlight !== undefined) return inFlight;
    const attempt = (async (): Promise<void> => {
      setState({ kind: "bootstrapping" });
      try {
        await api.auth.refresh();
        const identity = await api.auth.me();
        setState({ kind: "authenticated", identity });
      } catch (error) {
        if (error instanceof UnauthenticatedError) {
          invalidate();
          return;
        }
        accessTokenStore.clear();
        setState({ kind: "unavailable" });
      }
    })();
    bootstrapInFlight.current = attempt;
    try {
      await attempt;
    } finally {
      if (bootstrapInFlight.current === attempt) bootstrapInFlight.current = undefined;
    }
  }, [api, invalidate]);

  useEffect(() => {
    // Strict Mode replays effects in development. One promise avoids reusing a refresh
    // cookie concurrently, which the backend correctly treats as refresh-token replay.
    if (bootstrapStarted.current) return;
    bootstrapStarted.current = true;
    void retryBootstrap();
  }, [retryBootstrap]);

  const value = useMemo<SessionContextValue>(() => ({
    state,
    async login(input) {
      try {
        await api.auth.login(input);
        const identity = await api.auth.me();
        setState({ kind: "authenticated", identity });
      } catch (error) {
        if (error instanceof UnauthenticatedError) invalidate();
        else if (error instanceof ApiUnavailableError) setState({ kind: "unavailable" });
        throw error;
      }
    },
    async logout() {
      try {
        await api.auth.logout();
      } finally {
        invalidate();
      }
    },
    invalidate,
    retryBootstrap
  }), [api, invalidate, retryBootstrap, state]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (value === undefined) throw new Error("useSession must be used inside SessionProvider.");
  return value;
}
