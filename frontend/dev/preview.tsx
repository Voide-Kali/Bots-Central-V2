/*
 * Local design preview with sample data. Never built or shipped: `vite build` only uses
 * index.html. Run `npx vite` and open /dev/preview.html (?view=login, ?empty=1, ?user=1).
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import type { ApiClient } from "../src/api";
import type { AuditEvent, Device } from "../src/api/contracts";
import { App } from "../src/App";
import "../src/styles.css";

const params = new URLSearchParams(window.location.search);
const now = Date.now();
const ago = (minutes: number): string => new Date(now - minutes * 60_000).toISOString();
const GB = 1024 ** 3;

const devices: Device[] = params.has("empty") ? [] : [
  { id: "9f2c1d4e-7a1b-4c55-9e0a-3b6f2d8c1a77", name: "tropa", platform: "linux/amd64", status: "online", lifecycleStatus: "active", lastSeenAt: ago(0.5), agentVersion: "0.4.0", fingerprint: null,
    telemetry: { recordedAt: ago(0.5), cpuPercent: 12, load1: 0.42, cpuCount: 4, memoryTotalBytes: 14.6 * GB, memoryUsedBytes: 8.1 * GB, diskTotalBytes: 234 * GB, diskUsedBytes: 196 * GB, temperatureC: 48, uptimeSeconds: 6 * 86_400 + 4 * 3_600 } },
  { id: "3c8e0b9a-21f4-4d7e-8b3a-5e9c7f1d2b40", name: "MacMaker", platform: "darwin/arm64", status: "online", lifecycleStatus: "active", lastSeenAt: ago(1), agentVersion: "0.4.0", fingerprint: null,
    telemetry: { recordedAt: ago(1), cpuPercent: 18, load1: 1.99, cpuCount: 10, memoryTotalBytes: 16 * GB, memoryUsedBytes: 11.8 * GB, diskTotalBytes: 460 * GB, diskUsedBytes: 115 * GB, temperatureC: null, uptimeSeconds: 2 * 86_400 + 7 * 3_600 } },
  { id: "c41d7e2f-0b6a-4f93-a8d1-7e2b9c5f3a18", name: "pc-sala", platform: "linux/amd64", status: "offline", lifecycleStatus: "active", lastSeenAt: ago(60 * 26), agentVersion: "0.3.2", fingerprint: null,
    telemetry: { recordedAt: ago(60 * 26), cpuPercent: 4, load1: 0.1, cpuCount: 2, memoryTotalBytes: 7.7 * GB, memoryUsedBytes: 2.3 * GB, diskTotalBytes: 110 * GB, diskUsedBytes: 41 * GB, temperatureC: 39, uptimeSeconds: 3 * 3_600 } },
  { id: "e7a90c3b-5d2f-4e18-b6c4-1a8f0d7e9c25", name: "notebook-escola", platform: "linux/amd64", status: "offline", lifecycleStatus: "pending", lastSeenAt: null, agentVersion: null, fingerprint: "SHA256:k2Qf-9xTa-71Lm-pB4z", telemetry: null }
];

const labels: Array<[number, string, string, string, string | null]> = [
  [2, "user", "device.enrolled", "success", "notebook-escola"],
  [4, "user", "device.pairing_created", "success", null],
  [38, "device", "action.completed", "success", "MacMaker"],
  [38, "telegram", "action.approved", "success", "MacMaker"],
  [39, "telegram", "action.requested", "success", "MacMaker"],
  [95, "telegram", "action.approval_failed", "failure", "tropa"],
  [180, "device", "action.delivered", "success", "tropa"],
  [181, "telegram", "action.approved", "success", "tropa"],
  [60 * 20, "telegram", "telegram.linked", "success", null],
  [60 * 21, "user", "auth.login", "success", null]
];
const events: AuditEvent[] = labels.map(([minutes, actor, action, outcome, name]) => ({ occurredAt: ago(minutes), actor, action, outcome, name }));

const user = params.has("user") ? "user" : "admin";
const api: ApiClient = {
  auth: {
    register: async () => ({ message: "ok" }),
    consumeVerificationCode: async () => ({ verified: true }),
    login: async () => undefined,
    refresh: async () => { if (params.get("view") === "login") throw new (await import("../src/api")).UnauthenticatedError(); },
    logout: async () => undefined,
    me: async () => ({ id: "u1", email: "voide.kali@gmail.com", role: user })
  },
  devices: {
    list: async () => devices,
    createPairing: async () => ({ pairingId: "p1", pairingToken: "AVAL-7KQ2-M9XD-4TFP", expiresAt: new Date(now + 10 * 60_000).toISOString() }),
    revokePairing: async () => undefined,
    approve: async () => undefined,
    reject: async () => undefined
  },
  telegram: { status: async () => ({ linked: true, botUsername: "aval_tropa_bot" }), createLinkCode: async () => ({ code: "481-220", expiresAt: new Date(now + 600_000).toISOString(), botUsername: "aval_tropa_bot" }), unlink: async () => undefined },
  actionPin: { status: async () => ({ configured: true, lockedUntil: null }), set: async () => undefined },
  audit: { list: async () => events },
  admin: {
    overview: async () => ({ checkedAt: ago(0), users: { active: 2, pending_verification: 1 }, devicesByLifecycle: { active: 3, pending: 1 }, devicesOnline: 2, commands24h: { completed: 5, failed: 1 }, telegramLinks: 1 }),
    users: async () => [
      { id: "u1", email: "voide.kali@gmail.com", status: "active", role: "admin", createdAt: ago(60 * 24 * 9), devices: 4, telegram: true, pin: true },
      { id: "u2", email: "helder.prof@ifms.edu.br", status: "active", role: "user", createdAt: ago(60 * 24 * 2), devices: 0, telegram: false, pin: false },
      { id: "u3", email: "colega.4a@estudante.ifms.edu.br", status: "pending_verification", role: "user", createdAt: ago(60 * 5), devices: 0, telegram: false, pin: false }
    ],
    failures: async () => [{ at: ago(95), user: "voide.kali@gmail.com", device: "tropa", action: "lock_screen", status: "failed", error: "unsupported" }],
    events: async () => events.slice(0, 8).map((event) => ({ occurredAt: event.occurredAt, user: "voide.kali@gmail.com", action: event.action, outcome: event.outcome })),
    activate: async () => undefined
  }
};

window.history.replaceState({}, "", params.get("view") === "login" ? "/login" : "/devices");
createRoot(document.getElementById("root")!).render(<StrictMode><App api={api} /></StrictMode>);
