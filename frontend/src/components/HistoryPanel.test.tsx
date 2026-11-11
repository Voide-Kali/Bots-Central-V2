import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AuditApi } from "../api/client";
import type { AuditEvent } from "../api/contracts";
import { UnauthenticatedError } from "../api/errors";
import { HistoryPanel, toCsv } from "./HistoryPanel";

describe("HistoryPanel", () => {
  it("lists events with friendly labels and marks failures", async () => {
    const api: AuditApi = {
      list: vi.fn(async () => [
        { occurredAt: "2026-10-21T12:00:00+00:00", actor: "user", action: "device.approved", outcome: "success", name: "MAC-DO-LUCAS" },
        { occurredAt: "2026-10-21T11:00:00+00:00", actor: "telegram", action: "action.approval_failed", outcome: "failure", name: null },
        { occurredAt: "2026-10-21T10:00:00+00:00", actor: "system", action: "something.new", outcome: "success", name: null },
        { occurredAt: "2026-10-21T09:00:00+00:00", actor: "telegram", action: "action.approved", outcome: "success", name: null, kind: "lock_screen", file: null, byPin: true },
        { occurredAt: "2026-10-21T08:00:00+00:00", actor: "telegram", action: "pin.failed", outcome: "denied", name: null },
        { occurredAt: "2026-10-21T07:00:00+00:00", actor: "device", action: "sensor.failed_login", outcome: "denied", name: "tropa", source: "gdm-password" }
      ])
    };
    render(<HistoryPanel api={api} onUnauthenticated={vi.fn()} />);
    expect(await screen.findByText("Dispositivo aprovado")).toBeVisible();
    expect(screen.getByText("MAC-DO-LUCAS")).toBeVisible();
    expect(screen.getByText("Código de aprovação incorreto")).toBeVisible();
    expect(screen.getAllByText("por Telegram · falhou")).toHaveLength(2);
    expect(screen.getByText("something.new")).toBeVisible(); // unknown actions still shown
    expect(screen.getByText("bloquear tela · com PIN")).toBeVisible();
    expect(screen.getByText("PIN incorreto")).toBeVisible();
    expect(screen.getByText("Senha errada no computador")).toBeVisible();
    expect(screen.getByText("tropa · tela de login")).toBeVisible();
    expect(api.list).toHaveBeenCalledWith(100);
  });

  it("filters to failures only and searches by text", async () => {
    const api: AuditApi = {
      list: vi.fn(async () => [
        { occurredAt: "2026-10-21T12:00:00+00:00", actor: "user", action: "auth.login", outcome: "success", name: null },
        { occurredAt: "2026-10-21T11:00:00+00:00", actor: "telegram", action: "pin.failed", outcome: "denied", name: null }
      ])
    };
    render(<HistoryPanel api={api} onUnauthenticated={vi.fn()} />);
    expect(await screen.findByText("Login no painel")).toBeVisible();
    expect(screen.getByText("PIN incorreto")).toBeVisible();
    // "Só falhas" hides the successful login.
    fireEvent.click(screen.getByRole("button", { name: "Só falhas" }));
    expect(screen.queryByText("Login no painel")).toBeNull();
    expect(screen.getByText("PIN incorreto")).toBeVisible();
    // Back to all, then search narrows to the login.
    fireEvent.click(screen.getByRole("button", { name: "Todos" }));
    fireEvent.change(screen.getByPlaceholderText("Buscar por evento, detalhe ou autor"), { target: { value: "login" } });
    expect(screen.getByText("Login no painel")).toBeVisible();
    expect(screen.queryByText("PIN incorreto")).toBeNull();
  });

  it("builds a semicolon-separated CSV with a header and ISO timestamp", () => {
    const events: readonly AuditEvent[] = [
      { occurredAt: "2026-10-21T07:00:00+00:00", actor: "device", action: "sensor.failed_login", outcome: "denied", name: "tropa", source: "gdm-password" }
    ];
    const csv = toCsv(events);
    const lines = csv.split("\r\n");
    expect(lines[0]).toBe('"Data e hora";"Evento";"Detalhe";"Por";"Resultado";"Quando (ISO)"');
    expect(lines[1]).toContain('"Senha errada no computador"');
    expect(lines[1]).toContain('"tropa · tela de login"');
    expect(lines[1]).toContain('"negado"');
    expect(lines[1]).toContain('"2026-10-21T07:00:00+00:00"');
  });

  it("escapes quotes in CSV fields", () => {
    const csv = toCsv([{ occurredAt: "2026-10-21T07:00:00+00:00", actor: "user", action: "device.approved", outcome: "success", name: 'PC "casa"' }]);
    expect(csv).toContain('"PC ""casa"""');
  });

  it("shows an empty state and reports an expired session", async () => {
    render(<HistoryPanel api={{ list: vi.fn(async () => []) }} onUnauthenticated={vi.fn()} />);
    expect(await screen.findByText("Nenhuma ação registrada ainda.")).toBeVisible();
    const onUnauthenticated = vi.fn();
    render(<HistoryPanel api={{ list: vi.fn(async () => { throw new UnauthenticatedError(); }) }} onUnauthenticated={onUnauthenticated} />);
    await waitFor(() => expect(onUnauthenticated).toHaveBeenCalledTimes(1));
  });
});
