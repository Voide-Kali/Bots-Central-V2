import { render, screen } from "@testing-library/react";
import { DeviceCard } from "./DeviceCard";
describe("DeviceCard", () => { it("presents the required device status fields", () => {
  render(<DeviceCard device={{ name: "Estação Financeiro", platform: "Windows 11", connection: "offline", lastSeen: "Há 15 minutos", agentVersion: "0.1.0-demo" }} />);
  expect(screen.getByRole("heading", { name: "Estação Financeiro" })).toBeVisible(); expect(screen.getByText("Windows 11")).toBeVisible(); expect(screen.getByText("Offline")).toBeVisible(); expect(screen.getByText("Há 15 minutos")).toBeVisible(); expect(screen.getByText("0.1.0-demo")).toBeVisible();
}); });
