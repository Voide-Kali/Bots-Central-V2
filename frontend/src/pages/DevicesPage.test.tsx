import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ApiClient } from "../api";
import { ApiUnavailableError, ForbiddenError, UnauthenticatedError } from "../api";
import type { Device } from "../api/contracts";
import { SessionProvider } from "../app/session";
import { createHttpApiClient } from "../api/httpAdapter";
import { accessTokenStore } from "../api/memoryAccessToken";
import { DevicesPage } from "./DevicesPage";

const serverDevices: readonly Device[] = [
  { id: "PC000", name: "PC000", platform: "linux/amd64", status: "online", lifecycleStatus: "active", lastSeenAt: "2026-09-10T10:00:00Z", agentVersion: "0.1.0", fingerprint: null, telemetry: { recordedAt: "2026-09-10T10:00:00Z", cpuPercent: 37.5, load1: 0.8, cpuCount: 8, memoryTotalBytes: 16 * 1024 ** 3, memoryUsedBytes: 4 * 1024 ** 3, diskTotalBytes: 512 * 1024 ** 3, diskUsedBytes: 128 * 1024 ** 3, temperatureC: 51.5, uptimeSeconds: 90_061 } },
  { id: "MBP-07", name: "Laptop de viagem", platform: "macOS/arm64", status: "offline", lifecycleStatus: "pending", lastSeenAt: null, agentVersion: null, fingerprint: "SHA256:AbC+/exact-fingerprint=", telemetry: null },
  { id: "NODE-02", name: "Servidor doméstico", platform: "linux/amd64", status: "online", lifecycleStatus: "active", lastSeenAt: "2026-09-10T09:56:00Z", agentVersion: "0.1.0", fingerprint: null, telemetry: null }
];

function fakeClient(list: ApiClient["devices"]["list"] = async () => serverDevices): ApiClient {
  return {
    auth: {
      register: async () => ({ message: "" }),
      consumeVerificationCode: async () => ({ verified: true }),
      login: async () => undefined,
      refresh: async () => undefined,
      logout: async () => undefined,
      me: async () => ({ id: "user-1", email: "operator@example.test" })
    },
    devices: { list, createPairing: vi.fn(async () => ({ pairingId: "pairing-id", pairingToken: "test-only-pairing", expiresAt: new Date(Date.now() + 60_000).toISOString() })), revokePairing: vi.fn(async () => undefined), approve: vi.fn(async () => undefined), reject: vi.fn(async () => undefined) }
  };
}

function renderDevices(api = fakeClient()): ApiClient {
  render(<SessionProvider api={api}><DevicesPage api={api} /></SessionProvider>);
  return api;
}

async function waitForDevices(): Promise<void> {
  await screen.findByRole("button", { name: /PC000/ });
}

describe("DevicesPage", () => {
  it("shows the latest server telemetry for an active device", async () => {
    renderDevices();
    await waitForDevices();
    fireEvent.click(screen.getByRole("button", { name: /PC000/ }));
    const panel = await screen.findByRole("region", { name: "Telemetria" });
    expect(panel).toHaveTextContent("37,5%");
    expect(panel).toHaveTextContent("4 GB de 16 GB (25%)");
    expect(panel).toHaveTextContent("128 GB de 512 GB (25%)");
    expect(panel).toHaveTextContent("51,5 °C");
    expect(panel).toHaveTextContent("1 d 1 h");
    fireEvent.click(screen.getByRole("button", { name: /Servidor doméstico/ }));
    expect(await screen.findByText(/Sem telemetria ainda/)).toBeVisible();
  });

  it("keeps the sidebar in the approved order and Soon items do not navigate", async () => {
    renderDevices();
    await waitForDevices();
    const items = within(screen.getByRole("navigation", { name: "Navegação do Device Center" })).getAllByRole("button");
    expect(items.map((item) => item.textContent?.replace("Soon", "").trim())).toEqual(["Devices", "Automations", "Notifications", "History", "Security", "Settings"]);
    expect(items[0]).toHaveAttribute("aria-current", "page");
    fireEvent.click(screen.getByRole("button", { name: /Automations/ }));
    expect(screen.getByText("Automations estará disponível em uma próxima versão.")).toBeVisible();
    expect(window.location.pathname).not.toBe("/automations");
  });

  it("derives summary and presence from server fields without a runtime mock", async () => {
    renderDevices();
    await waitForDevices();
    expect(screen.getByText("2/3")).toBeVisible();
    expect(screen.getByText("Pendentes")).toBeVisible();
    expect(screen.getAllByText("1")).not.toHaveLength(0);
    expect(screen.getByText("Dados do servidor")).toBeVisible();
    expect(screen.getByRole("button", { name: "Adicionar dispositivo" })).toBeVisible();
  });

  it("searches by server device ID, name, and platform", async () => {
    renderDevices();
    await waitForDevices();
    const search = screen.getByRole("searchbox", { name: "Buscar dispositivos" });
    fireEvent.change(search, { target: { value: "MBP-07" } });
    expect(screen.getByRole("button", { name: /Laptop de viagem/ })).toBeVisible();
    expect(screen.queryByRole("button", { name: /PC000/ })).not.toBeInTheDocument();
    fireEvent.change(search, { target: { value: "linux/amd64" } });
    expect(screen.getByRole("button", { name: /PC000/ })).toBeVisible();
  });

  it("filters server-owned online and offline presence", async () => {
    renderDevices();
    await waitForDevices();
    fireEvent.click(screen.getByRole("button", { name: "Online" }));
    expect(screen.getAllByRole("img", { name: "Indicador online" })).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Offline" }));
    expect(screen.getByRole("button", { name: /Laptop de viagem/ })).toBeVisible();
    expect(screen.getByRole("img", { name: "Indicador offline" })).toBeVisible();
  });

  it("shows pending lifecycle and real server metadata when a row expands", async () => {
    renderDevices();
    await waitForDevices();
    const row = screen.getByRole("button", { name: /Laptop de viagem/ });
    fireEvent.keyDown(row, { key: "Enter" });
    expect(row).toHaveAttribute("aria-expanded", "true");
    const details = screen.getByLabelText("Detalhes de Laptop de viagem");
    expect(within(details).getByText("Aguardando aprovação")).toBeVisible();
    expect(within(details).getByText("Ainda não recebido pelo servidor")).toBeVisible();
    expect(within(details).getByText("Não informado pelo servidor")).toBeVisible();
  });

  it("renders backend unavailable state and retries successfully", async () => {
    const list = vi.fn().mockRejectedValueOnce(new ApiUnavailableError()).mockResolvedValue(serverDevices);
    renderDevices(fakeClient(list));
    await screen.findByRole("heading", { name: "Não foi possível atualizar seus dispositivos." });
    fireEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));
    await waitForDevices();
    await waitFor(() => expect(screen.getByText("Lista de dispositivos atualizada com dados do servidor.")).toBeVisible());
  });

  it("preserves loading structure without enabled controls", async () => {
    renderDevices(fakeClient((): Promise<never> => new Promise(() => undefined)));
    await waitFor(() => expect(screen.getByRole("button", { name: "Atualizar" })).toBeDisabled());
    expect(screen.getByLabelText("Carregando resumo")).toBeVisible();
    expect(screen.getByLabelText("Buscar dispositivos")).toBeDisabled();
  });
});

function deferred<T>(): { promise: Promise<T>; resolve(value: T): void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

async function selectPending(): Promise<void> {
  fireEvent.click(screen.getByRole("button", { name: /Laptop de viagem/ }));
  fireEvent.change(screen.getByLabelText("Fingerprint exibido pelo Agent"), { target: { value: serverDevices[1]!.fingerprint } });
}

describe("Device Online pairing and decisions", () => {
  afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); accessTokenStore.clear(); });

  it("calls createPairing, copies the memory-only token, and clears it on cancel and remount", async () => {
    const persist = vi.spyOn(Storage.prototype, "setItem");
    const copy = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText: copy } });
    const location = window.location.href;
    const api = renderDevices();
    await waitForDevices();
    fireEvent.click(screen.getByRole("button", { name: "Adicionar dispositivo" }));
    expect(await screen.findByText("test-only-pairing")).toBeVisible();
    expect(api.devices.createPairing).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Expira em/).querySelector("time")).toHaveAttribute("dateTime");
    fireEvent.click(screen.getByRole("button", { name: "Copiar código" }));
    await waitFor(() => expect(copy).toHaveBeenCalledWith("test-only-pairing"));
    expect(persist).not.toHaveBeenCalled();
    expect(window.location.href).toBe(location);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Cancelar pairing" })); });
    expect(screen.queryByText("test-only-pairing")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Adicionar dispositivo" }));
    await screen.findByText("test-only-pairing");
    cleanup();
    renderDevices(api);
    await waitForDevices();
    expect(screen.queryByText("test-only-pairing")).not.toBeInTheDocument();
  });

  it("keeps pairing visible when server-side cancellation fails", async () => {
    const api = renderDevices();
    await waitForDevices();
    fireEvent.click(screen.getByRole("button", { name: "Adicionar dispositivo" }));
    await screen.findByText("test-only-pairing");
    api.devices.revokePairing = vi.fn(async () => { throw new Error("network"); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Cancelar pairing" })); });
    expect(await screen.findByText("Não foi possível cancelar o pairing no servidor.")).toBeVisible();
    expect(screen.getByText("test-only-pairing")).toBeVisible();
  });

  it("starts pairing through the production HTTP adapter", async () => {
    const fetchMock = vi.fn(async (path: string) => {
      const body = path.endsWith("/refresh") ? { access_token: "test-access", token_type: "Bearer", expires_in: 600 }
        : path.endsWith("/me") ? { id: "user", email: "operator@example.test" }
        : path.endsWith("/pairings") ? { pairing_id: "pairing-id", pairing_token: "http-pairing-token", expires_at: new Date(Date.now() + 60_000).toISOString() }
        : { devices: [] };
      return new Response(JSON.stringify(body), { status: path.endsWith("/pairings") ? 201 : 200, headers: { "Content-Type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderDevices(createHttpApiClient());
    fireEvent.click(await screen.findByRole("button", { name: "Adicionar dispositivo" }));
    expect(await screen.findByText("http-pairing-token")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/devices/pairings", expect.objectContaining({ method: "POST", body: "{}" }));
  });

  it("discards a late pairing response after logout", async () => {
    const api = fakeClient();
    const pending = deferred<{ pairingId: string; pairingToken: string; expiresAt: string }>();
    api.devices.createPairing = vi.fn(() => pending.promise);
    renderDevices(api); await waitForDevices();
    fireEvent.click(screen.getByRole("button", { name: "Adicionar dispositivo" }));
    fireEvent.click(screen.getByRole("button", { name: /operator@example.test/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Sair" }));
    await screen.findByText("Acesso necessário");
    vi.useFakeTimers();
    await act(async () => pending.resolve({ pairingId: "pairing-id", pairingToken: "late-secret", expiresAt: new Date(Date.now() + 60_000).toISOString() }));
    expect(screen.queryByText("late-secret")).not.toBeInTheDocument();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("blocks duplicate pairing creation while the request is pending", async () => {
    const api = fakeClient();
    const pending = deferred<{ pairingId: string; pairingToken: string; expiresAt: string }>();
    api.devices.createPairing = vi.fn(() => pending.promise);
    renderDevices(api);
    await waitForDevices();
    const button = screen.getByRole("button", { name: "Adicionar dispositivo" });
    fireEvent.click(button); fireEvent.click(button);
    expect(button).toBeDisabled();
    expect(api.devices.createPairing).toHaveBeenCalledTimes(1);
    await act(async () => pending.resolve({ pairingId: "pairing-id", pairingToken: "delayed", expiresAt: new Date(Date.now() + 60_000).toISOString() }));
  });

  it("displays the exact fingerprint and requires exact Agent comparison", async () => {
    renderDevices(); await waitForDevices();
    fireEvent.click(screen.getByRole("button", { name: /Laptop de viagem/ }));
    expect(screen.getByText(serverDevices[1]!.fingerprint!)).toHaveTextContent(/^SHA256:AbC\+\/exact-fingerprint=$/);
    expect(screen.getByText(/corresponder exatamente ao exibido pelo Agent/)).toBeVisible();
    const approve = screen.getByRole("button", { name: "Aprovar dispositivo" });
    expect(approve).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Fingerprint exibido pelo Agent"), { target: { value: "SHA256:wrong" } });
    expect(approve).toBeDisabled();
  });

  it("fails closed when a pending device has a null fingerprint", async () => {
    const api = renderDevices(fakeClient(async () => serverDevices.map((device) => ({ ...device, fingerprint: null }))));
    await waitForDevices();
    fireEvent.click(screen.getByRole("button", { name: /Laptop de viagem/ }));
    expect(screen.getByRole("alert")).toHaveTextContent("O servidor não retornou o fingerprint");
    fireEvent.click(screen.getByRole("button", { name: "Aprovar dispositivo" }));
    expect(screen.getByRole("button", { name: "Aprovar dispositivo" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Rejeitar dispositivo" })).toBeDisabled();
    expect(api.devices.approve).not.toHaveBeenCalled();
  });

  it.each(["approve", "reject"] as const)("%s sends the exact fingerprint, blocks duplicates, and waits for server lifecycle and presence", async (decision) => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const action = deferred<void>();
    const refresh = deferred<readonly Device[]>();
    const list = vi.fn().mockResolvedValueOnce(serverDevices).mockReturnValue(refresh.promise);
    const api = fakeClient(list);
    api.devices[decision] = vi.fn(() => action.promise);
    renderDevices(api); await waitForDevices();
    fireEvent.click(screen.getByRole("button", { name: "Adicionar dispositivo" }));
    await screen.findByText("test-only-pairing");
    await selectPending();
    const button = screen.getByRole("button", { name: decision === "approve" ? "Aprovar dispositivo" : "Rejeitar dispositivo" });
    fireEvent.click(button); fireEvent.click(button);
    expect(api.devices[decision]).toHaveBeenCalledExactlyOnceWith("MBP-07", "SHA256:AbC+/exact-fingerprint=");
    expect(button).toBeDisabled();
    expect(list).toHaveBeenCalledTimes(1);
    await act(async () => action.resolve());
    expect(list).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("test-only-pairing")).not.toBeInTheDocument();
    const row = screen.getByRole("button", { name: /Laptop de viagem/ });
    expect(within(row).getByText("Aguardando aprovação")).toBeVisible();
    expect(within(row).getByRole("img", { name: "Indicador offline" })).toBeVisible();
    expect(within(row).queryByText("Ativo")).not.toBeInTheDocument();
    expect(within(row).queryByText("Revogado")).not.toBeInTheDocument();
    await act(async () => refresh.resolve(serverDevices.map((device) => device.id === "MBP-07" ? { ...device, lifecycleStatus: decision === "approve" ? "active" : "revoked", status: "offline" } : device)));
    expect(within(screen.getByRole("button", { name: /Laptop de viagem/ })).getByText(decision === "approve" ? "Ativo" : "Revogado")).toBeVisible();
  });

  it("does not reject without explicit confirmation", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const api = renderDevices(); await waitForDevices(); await selectPending();
    fireEvent.click(screen.getByRole("button", { name: "Rejeitar dispositivo" }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(api.devices.reject).not.toHaveBeenCalled();
  });

  it.each(["cancel", "expiry", "unmount", "completion"])("stops pairing polling on %s", async (ending) => {
    const list = vi.fn().mockResolvedValue(serverDevices);
    renderDevices(fakeClient(list)); await waitForDevices();
    vi.useFakeTimers();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Adicionar dispositivo" })); });
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(list).toHaveBeenCalledTimes(2);
    if (ending === "cancel") await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Cancelar pairing" })); });
    if (ending === "unmount") cleanup();
    if (ending === "expiry") await act(async () => { await vi.advanceTimersByTimeAsync(55_000); });
    if (ending === "completion") {
      await selectPending();
      await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Aprovar dispositivo" })); });
    }
    expect(screen.queryByText("test-only-pairing")).not.toBeInTheDocument();
    const count = list.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(20_000); });
    expect(list).toHaveBeenCalledTimes(count);
  });

  it("never overlaps list calls, including a decision refresh during a slow poll", async () => {
    const slow = deferred<readonly Device[]>();
    const list = vi.fn().mockResolvedValueOnce(serverDevices).mockReturnValueOnce(slow.promise).mockResolvedValue(serverDevices);
    renderDevices(fakeClient(list)); await waitForDevices();
    vi.useFakeTimers();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Adicionar dispositivo" })); });
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(list).toHaveBeenCalledTimes(2);
    await selectPending();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Aprovar dispositivo" })); });
    expect(list).toHaveBeenCalledTimes(2);
    await act(async () => slow.resolve(serverDevices));
    expect(list).toHaveBeenCalledTimes(3);
  });

  it.each(["createPairing", "approve", "reject"] as const)("preserves 401/403 session semantics for %s", async (method) => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const api = fakeClient();
    api.devices[method] = vi.fn().mockRejectedValueOnce(new ForbiddenError()).mockRejectedValueOnce(new UnauthenticatedError());
    accessTokenStore.replace("session-token");
    renderDevices(api); await waitForDevices();
    if (method !== "createPairing") await selectPending();
    const name = method === "createPairing" ? "Adicionar dispositivo" : method === "approve" ? "Aprovar dispositivo" : "Rejeitar dispositivo";
    fireEvent.click(screen.getByRole("button", { name }));
    await screen.findByText(method === "createPairing" ? "Não foi possível iniciar o pairing." : "O servidor não aceitou a decisão.");
    expect(accessTokenStore.read()).toBe("session-token");
    expect(screen.queryByText("Acesso necessário")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name }));
    await screen.findByText("Acesso necessário");
    expect(accessTokenStore.read()).toBeUndefined();
  });
});
