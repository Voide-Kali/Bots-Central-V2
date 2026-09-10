import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ApiClient } from "../api";
import { ApiUnavailableError } from "../api";
import type { Device } from "../api/contracts";
import { SessionProvider } from "../app/session";
import { DevicesPage } from "./DevicesPage";

const serverDevices: readonly Device[] = [
  { id: "PC000", name: "PC000", platform: "linux/amd64", status: "online", lifecycleStatus: "active", lastSeenAt: "2026-09-10T10:00:00Z", agentVersion: "0.1.0" },
  { id: "MBP-07", name: "Laptop de viagem", platform: "macOS/arm64", status: "offline", lifecycleStatus: "pending", lastSeenAt: null, agentVersion: null },
  { id: "NODE-02", name: "Servidor doméstico", platform: "linux/amd64", status: "online", lifecycleStatus: "active", lastSeenAt: "2026-09-10T09:56:00Z", agentVersion: "0.1.0" }
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
    devices: { list }
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
    expect(screen.getByText(/pairing\/enrollment/)).toBeVisible();
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
    expect(within(details).getByText("Pendente de aprovação")).toBeVisible();
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
