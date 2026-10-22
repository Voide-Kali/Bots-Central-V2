import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AuditApi } from "../api/client";
import { UnauthenticatedError } from "../api/errors";
import { HistoryPanel } from "./HistoryPanel";

describe("HistoryPanel", () => {
  it("lists events with friendly labels and marks failures", async () => {
    const api: AuditApi = {
      list: vi.fn(async () => [
        { occurredAt: "2026-10-21T12:00:00+00:00", actor: "user", action: "device.approved", outcome: "success", name: "MAC-DO-LUCAS" },
        { occurredAt: "2026-10-21T11:00:00+00:00", actor: "telegram", action: "action.approval_failed", outcome: "failure", name: null },
        { occurredAt: "2026-10-21T10:00:00+00:00", actor: "system", action: "something.new", outcome: "success", name: null },
        { occurredAt: "2026-10-21T09:00:00+00:00", actor: "telegram", action: "action.approved", outcome: "success", name: null, kind: "lock_screen", file: null, byPin: true },
        { occurredAt: "2026-10-21T08:00:00+00:00", actor: "telegram", action: "pin.failed", outcome: "denied", name: null }
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
    expect(api.list).toHaveBeenCalledWith(50);
  });

  it("shows an empty state and reports an expired session", async () => {
    render(<HistoryPanel api={{ list: vi.fn(async () => []) }} onUnauthenticated={vi.fn()} />);
    expect(await screen.findByText("Nenhuma ação registrada ainda.")).toBeVisible();
    const onUnauthenticated = vi.fn();
    render(<HistoryPanel api={{ list: vi.fn(async () => { throw new UnauthenticatedError(); }) }} onUnauthenticated={onUnauthenticated} />);
    await waitFor(() => expect(onUnauthenticated).toHaveBeenCalledTimes(1));
  });
});
