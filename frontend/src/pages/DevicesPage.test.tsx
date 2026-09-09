import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useEffect, useRef } from "react";
import type { ReactElement } from "react";
import type { ApiClient } from "../api";
import { ApiUnavailableError } from "../api";
import { SessionProvider, useSession } from "../app/session";
import { mockDevices } from "../api/mockAdapter";
import { DevicesPage } from "./DevicesPage";

function AuthenticatedDevices({ api }: { readonly api: ApiClient }): ReactElement {
  const { login } = useSession();
  const started = useRef(false);
  useEffect(() => {
    if (!started.current) {
      started.current = true;
      void login({ email: "demo@example.test", password: "not-a-real-password" });
    }
  }, [login]);
  return <DevicesPage api={api} />;
}

function mockClient(list: ApiClient["devices"]["list"]): ApiClient {
  return {
    adapterName: "mock",
    auth: {
      register: async () => ({ message: "" }),
      consumeVerificationCode: async () => ({ verified: true }),
      login: async () => ({ kind: "mock", displayName: "Operador de demonstração" }),
      refresh: async () => ({ kind: "mock", displayName: "Operador de demonstração" }),
      logout: async () => undefined,
      me: async () => ({ kind: "mock", displayName: "Operador de demonstração" })
    },
    devices: { list }
  };
}

function renderDevices(api = mockClient(async () => ({ kind: "mock", devices: mockDevices }))): ApiClient {
  render(<SessionProvider api={api}><AuthenticatedDevices api={api} /></SessionProvider>);
  return api;
}

async function waitForDevices(): Promise<void> {
  await screen.findByRole("button", { name: /Estação de trabalho/ });
}

describe("DevicesPage", () => {
  it("keeps the sidebar in the approved order and Soon items do not navigate", async () => {
    renderDevices();
    await waitForDevices();
    const items = within(screen.getByRole("navigation", { name: "Navegação do Device Center" })).getAllByRole("button");
    expect(items.map((item) => item.textContent?.replace("Soon", "").trim())).toEqual(["Devices", "Automations", "Notifications", "History", "Security", "Settings"]);
    expect(items[0]).toHaveAttribute("aria-current", "page");
    for (const item of items.slice(1)) expect(item).not.toHaveAttribute("aria-disabled");
    fireEvent.click(screen.getByRole("button", { name: /Automations/ }));
    expect(screen.getByText("Automations estará disponível em uma próxima versão.")).toBeVisible();
    expect(window.location.pathname).not.toBe("/automations");
  });

  it("derives summary and coverage values from the mock list", async () => {
    renderDevices();
    await waitForDevices();
    expect(screen.getByText("Total")).toBeVisible();
    expect(screen.getByText("2/3")).toBeVisible();
    expect(screen.getByText("Precisa de atenção")).toBeVisible();
    expect(screen.getByText("1")).toBeVisible();
    expect(screen.getByText("Demonstração local")).toBeVisible();
    expect(screen.queryByText("Visão ao vivo")).not.toBeInTheDocument();
  });

  it("searches by device ID, name, and platform", async () => {
    renderDevices();
    await waitForDevices();
    const search = screen.getByRole("searchbox", { name: "Buscar dispositivos" });
    fireEvent.change(search, { target: { value: "MBP-07" } });
    expect(screen.getByRole("button", { name: /Laptop de viagem/ })).toBeVisible();
    expect(screen.queryByRole("button", { name: /Estação de trabalho/ })).not.toBeInTheDocument();
    fireEvent.change(search, { target: { value: "Estação" } });
    expect(screen.getByRole("button", { name: /Estação de trabalho/ })).toBeVisible();
    fireEvent.change(search, { target: { value: "Ubuntu" } });
    expect(screen.getByRole("button", { name: /Servidor doméstico/ })).toBeVisible();
  });

  it("filters online and offline devices, then clears filters", async () => {
    renderDevices();
    await waitForDevices();
    fireEvent.click(screen.getByRole("button", { name: "Online" }));
    expect(screen.getAllByRole("img", { name: "Indicador online" })).toHaveLength(2);
    expect(screen.queryByText("Laptop de viagem")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Offline" }));
    expect(screen.getByText("Laptop de viagem")).toBeVisible();
    fireEvent.change(screen.getByRole("searchbox", { name: "Buscar dispositivos" }), { target: { value: "nenhum" } });
    expect(screen.getByText("Nenhum dispositivo encontrado.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Limpar filtros" }));
    expect(screen.getByRole("button", { name: /Estação de trabalho/ })).toBeVisible();
  });

  it("uses text and an indicator for both connection states", async () => {
    renderDevices();
    await waitForDevices();
    expect(screen.getAllByText("Online")).not.toHaveLength(0);
    expect(screen.getAllByRole("img", { name: "Indicador online" })).not.toHaveLength(0);
    expect(screen.getAllByText("Offline")).not.toHaveLength(0);
    expect(screen.getByRole("img", { name: "Indicador offline" })).toBeVisible();
  });

  it("selects and expands a row with keyboard interaction", async () => {
    renderDevices();
    await waitForDevices();
    const row = screen.getByRole("button", { name: /Estação de trabalho/ });
    fireEvent.keyDown(row, { key: "Enter" });
    expect(row).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("Detalhes de Estação de trabalho")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Ver detalhes" }));
    expect(screen.getByText("Os detalhes de PC000 estão atualizados.")).toBeVisible();
  });

  it("opens the mobile sidebar interaction without bottom navigation", async () => {
    renderDevices();
    await waitForDevices();
    fireEvent.click(screen.getByRole("button", { name: "Abrir menu" }));
    expect(document.querySelector(".device-center")).toHaveClass("device-center--sidebar-open");
  });

  it("renders approved unavailable state and retries successfully", async () => {
    const list = vi.fn().mockRejectedValueOnce(new ApiUnavailableError()).mockResolvedValue({ kind: "mock", devices: mockDevices });
    renderDevices(mockClient(list));
    await screen.findByRole("heading", { name: "Não foi possível atualizar seus dispositivos." });
    expect(screen.getByText("Não foi possível carregar uma atualização do servidor. Tente novamente em alguns instantes.")).toBeVisible();
    expect(screen.queryByText(/Seus dados anteriores continuam seguros/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));
    await waitForDevices();
    await waitFor(() => expect(screen.getByText("Lista de dispositivos atualizada agora.")).toBeVisible());
  });

  it("preserves the loading structure without enabled controls or details", async () => {
    const list = (): Promise<never> => new Promise(() => undefined);
    renderDevices(mockClient(list));
    await screen.findByLabelText("Carregando resumo");
    expect(screen.getByRole("button", { name: "Atualizar" })).toBeDisabled();
    expect(screen.getByLabelText("Buscar dispositivos")).toBeDisabled();
    expect(document.querySelectorAll(".skeleton-row")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: "Ver detalhes" })).not.toBeInTheDocument();
  });

  it("keeps mock devices restricted to the approved field set", () => {
    for (const device of mockDevices) {
      expect(Object.keys(device).sort()).toEqual(["agentVersion", "connection", "id", "lastSeen", "name", "platform"]);
    }
  });
});
