import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { TelegramApi } from "../api/client";
import { UnauthenticatedError } from "../api/errors";
import { TelegramCard } from "./TelegramCard";

function fakeApi(linked = false): TelegramApi {
  return {
    status: vi.fn(async () => ({ linked, botUsername: "bots_central_bot" })),
    createLinkCode: vi.fn(async () => ({ code: "ABCDEFGH23", expiresAt: new Date(Date.now() + 600_000).toISOString(), botUsername: "bots_central_bot" })),
    unlink: vi.fn(async () => undefined)
  };
}

describe("TelegramCard", () => {
  it("generates a one-time code with a deep link", async () => {
    const api = fakeApi();
    render(<TelegramCard api={api} onUnauthenticated={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Vincular Telegram" }));
    expect(await screen.findByText("/vincular ABCDEFGH23")).toBeVisible();
    expect(screen.getByRole("link", { name: "Abrir no Telegram" })).toHaveAttribute("href", "https://t.me/bots_central_bot?start=ABCDEFGH23");
    expect(api.createLinkCode).toHaveBeenCalledTimes(1);
  });

  it("shows linked state and unlinks after confirmation", async () => {
    const api = fakeApi(true);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<TelegramCard api={api} onUnauthenticated={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Desvincular" }));
    await waitFor(() => expect(api.unlink).toHaveBeenCalledTimes(1));
  });

  it("reports an expired session", async () => {
    const api = fakeApi();
    api.status = vi.fn(async () => { throw new UnauthenticatedError(); });
    const onUnauthenticated = vi.fn();
    render(<TelegramCard api={api} onUnauthenticated={onUnauthenticated} />);
    await waitFor(() => expect(onUnauthenticated).toHaveBeenCalledTimes(1));
  });
});
