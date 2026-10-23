import { useEffect, useRef, useState } from "react";
import type { ReactElement } from "react";
import type { ActionPinApi, DevicesApi } from "../api/client";
import type { ActionKind } from "../api/contracts";
import { UnauthenticatedError } from "../api/errors";

/*
 * Run a Telegram action from the panel (ADR-021), approved with the same PIN. For when the
 * phone is far: trigger here, type the PIN, see the result. Same core, no new power.
 */

const ACTIONS: ReadonlyArray<{ readonly kind: ActionKind; readonly label: string }> = [
  { kind: "lock_screen", label: "Bloquear tela" },
  { kind: "webcam_photo", label: "Foto" },
  { kind: "network_scan", label: "Rede" }
];

const TERMINAL = new Set(["completed", "delivered", "failed", "expired", "denied"]);
const POLL_MS = 1200;
const MAX_POLLS = 40; // ~48 s

type Outcome =
  | { readonly kind: "done"; readonly message: string; readonly text?: string; readonly photoUrl?: string }
  | { readonly kind: "error"; readonly message: string };

const PIN_MESSAGES: Readonly<Record<string, string>> = {
  wrong_pin: "PIN incorreto.",
  locked: "PIN bloqueado por tentativas. Aguarde alguns minutos.",
  busy: "Você já tem um pedido em andamento. Aguarde terminar.",
  not_found: "Computador não encontrado ou não está ativo.",
  failed: "Não foi possível iniciar a ação agora."
};

export function DeviceActions({ api, pinApi, deviceId, onUnauthenticated }: {
  readonly api: DevicesApi;
  readonly pinApi?: ActionPinApi;
  readonly deviceId: string;
  onUnauthenticated(): void;
}): ReactElement | null {
  const [pin, setPin] = useState("");
  const [running, setRunning] = useState<ActionKind | null>(null);
  const [outcome, setOutcome] = useState<Outcome>();
  const [configured, setConfigured] = useState<boolean>();
  const photoUrl = useRef<string | undefined>(undefined);
  const cancelled = useRef(false);

  useEffect(() => {
    cancelled.current = false;
    return () => {
      cancelled.current = true;
      if (photoUrl.current) { URL.revokeObjectURL(photoUrl.current); photoUrl.current = undefined; }
    };
  }, [deviceId]);

  useEffect(() => {
    if (!pinApi) { setConfigured(true); return; }
    let active = true;
    void pinApi.status()
      .then((status) => { if (active) setConfigured(status.configured); })
      .catch((error: unknown) => { if (error instanceof UnauthenticatedError) onUnauthenticated(); else if (active) setConfigured(true); });
    return () => { active = false; };
  }, [pinApi, onUnauthenticated]);

  if (!api.startAction || !api.actionStatus) return null;

  async function run(kind: ActionKind): Promise<void> {
    if (running || !/^[0-9]{6}$/.test(pin)) { if (!/^[0-9]{6}$/.test(pin)) setOutcome({ kind: "error", message: "Digite o seu PIN de 6 números." }); return; }
    setRunning(kind);
    setOutcome(undefined);
    if (photoUrl.current) { URL.revokeObjectURL(photoUrl.current); photoUrl.current = undefined; }
    try {
      const started = await api.startAction!(deviceId, kind, pin);
      if (!started.ok) { setOutcome({ kind: "error", message: PIN_MESSAGES[started.reason] ?? PIN_MESSAGES.failed! }); return; }
      setPin("");
      for (let attempt = 0; attempt < MAX_POLLS; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, POLL_MS));
        if (cancelled.current) return;
        const status = await api.actionStatus!(deviceId, started.commandId);
        if (!TERMINAL.has(status.status)) continue;
        if (status.status === "completed" || status.status === "delivered") {
          const message = status.message ?? "Pronto.";
          if (status.hasPhoto && api.actionPhoto) {
            const blob = await api.actionPhoto(deviceId, started.commandId);
            if (cancelled.current) return;
            const url = URL.createObjectURL(blob);
            photoUrl.current = url;
            setOutcome({ kind: "done", message, photoUrl: url });
          } else {
            setOutcome({ kind: "done", message, text: status.text ?? undefined });
          }
        } else {
          setOutcome({ kind: "error", message: status.message ?? "A ação não foi concluída." });
        }
        return;
      }
      setOutcome({ kind: "error", message: "A ação demorou demais. Confira o computador e tente de novo." });
    } catch (error) {
      if (error instanceof UnauthenticatedError) onUnauthenticated();
      else setOutcome({ kind: "error", message: "Não foi possível falar com o servidor." });
    } finally {
      if (!cancelled.current) setRunning(null);
    }
  }

  if (configured === false) {
    return <section aria-label="Ações" className="action-panel action-panel--hint">
      <p>Para controlar este computador pelo site, crie um PIN no cartão <strong>Seu aval</strong>.</p>
    </section>;
  }

  return <section aria-label="Ações" className="action-panel">
    <div className="action-panel__head">
      <span className="action-panel__title">Ações</span>
      <span className="action-panel__note">Toda ação pede o seu PIN.</span>
    </div>
    <div className="action-panel__row">
      <label className="action-panel__pin">
        <span className="sr-only">PIN de 6 números</span>
        <input autoComplete="off" disabled={running !== null} inputMode="numeric" maxLength={6}
          onChange={(event) => setPin(event.target.value.replace(/[^0-9]/g, "").slice(0, 6))}
          placeholder="PIN" type="password" value={pin} />
      </label>
      <div className="action-panel__buttons">
        {ACTIONS.map((action) => <button className="button" disabled={running !== null} key={action.kind}
          onClick={() => void run(action.kind)} type="button">
          {running === action.kind ? "Aguardando..." : action.label}
        </button>)}
      </div>
    </div>
    {outcome ? <div className={outcome.kind === "error" ? "action-panel__result action-panel__result--error" : "action-panel__result"} role="status">
      <p>{outcome.message}</p>
      {outcome.kind === "done" && outcome.text ? <pre className="action-panel__scan">{outcome.text}</pre> : null}
      {outcome.kind === "done" && outcome.photoUrl ? <img alt="Foto do computador" className="action-panel__photo" src={outcome.photoUrl} /> : null}
    </div> : null}
  </section>;
}
