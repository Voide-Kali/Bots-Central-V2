import { render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import type { ApiClient } from "../api";
import { ApiUnavailableError, UnauthenticatedError } from "../api";
import { SessionProvider, useSession } from "./session";

function SessionState(): ReactElement {
  const { state } = useSession();
  return <output>{state.kind === "authenticated" ? state.identity.email : state.kind}</output>;
}

function apiWith(refresh: ApiClient["auth"]["refresh"]): ApiClient {
  return {
    auth: {
      register: async () => ({ message: "" }), consumeVerificationCode: async () => ({ verified: true }), login: async () => undefined,
      refresh, logout: async () => undefined, me: async () => ({ id: "user-1", email: "operator@example.test" })
    },
    devices: { list: async () => [], createPairing: async () => ({ pairingId: "pairing", pairingToken: "test-only", expiresAt: "2026-09-12T12:00:00Z" }), revokePairing: async () => undefined, approve: async () => undefined, reject: async () => undefined }
  };
}

describe("SessionProvider", () => {
  it("bootstraps the session by refreshing then loading /me once", async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    render(<SessionProvider api={apiWith(refresh)}><SessionState /></SessionProvider>);
    await screen.findByText("operator@example.test");
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("treats an absent refresh cookie as unauthenticated", async () => {
    render(<SessionProvider api={apiWith(async () => { throw new UnauthenticatedError(); })}><SessionState /></SessionProvider>);
    await screen.findByText("unauthenticated");
  });

  it("exposes backend unavailability without assuming an authenticated identity", async () => {
    render(<SessionProvider api={apiWith(async () => { throw new ApiUnavailableError(); })}><SessionState /></SessionProvider>);
    await waitFor(() => expect(screen.getByText("unavailable")).toBeVisible());
  });
});
