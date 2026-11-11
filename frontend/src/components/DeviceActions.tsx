import { useEffect, useRef, useState } from "react";
import type { ReactElement } from "react";
import type { ActionPinApi, DevicesApi } from "../api/client";
import type { ActionKind } from "../api/contracts";
import { UnauthenticatedError } from "../api/errors";

/*
 * Run a catalogue action from the panel (ADR-016, ADR-021), approved with the same PIN. For
 * when the phone is far: trigger here, type the PIN, see the result. The power actions
 * (shutdown/reboot/suspend) are destructive, so they ask for a second click to confirm on top
 * of the PIN.
 */

const ACTIONS: ReadonlyArray<{ readonly kind: ActionKind; readonly label: string; readonly effect: string }> = [
  { kind: "lock_screen", label: "Bloquear tela", effect: "trava a tela deste computador. Nenhum dado é enviado a você." },
  { kind: "webcam_photo", label: "Foto", effect: "tira uma foto da webcam e envia a imagem para você." },
  { kind: "network_scan", label: "Rede", effect: "lista os aparelhos na rede local e envia o texto para você." }
];

const POWER: ReadonlyArray<{ readonly mode: string; readonly label: string; readonly effect: string }> = [
  { mode: "reboot", label: "Reiniciar", effect: "reinicia o computador agora; programas abertos fecham." },
  { mode: "shutdown", label: "Desligar", effect: "desliga o computador agora; só liga de novo no botão." },
  { mode: "suspend", label: "Suspender", effect: "coloca o computador em suspensão (sleep)." }
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

export function DeviceActions({ api, pinApi, deviceId, deviceName, onUnauthenticated }: {
  readonly api: DevicesApi;
  readonly pinApi?: ActionPinApi;
  readonly deviceId: string;
  readonly deviceName?: string;
  onUnauthenticated(): void;
}): ReactElement | null {
  const [pin, setPin] = useState("");
  const [running, setRunning] = useState<string | null>(null);
  const [arming, setArming] = useState<string | null>(null); // power mode awaiting a confirm click
  const [outcome, setOutcome] = useState<Outcome>();
  const [configured, setConfigured] = useState<boolean>();
  const photoUrl = useRef<string | undefined>(undefined);
  const cancelled = useRef(false);

  useEffect(() => {
    cancelled.current = false;
    setArming(null);
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

  async function run(kind: ActionKind, mode?: string): Promise<void> {
    const key = mode ? `${kind}:${mode}` : kind;
    if (running || !/^[0-9]{6}$/.test(pin)) { if (!/^[0-9]{6}$/.test(pin)) setOutcome({ kind: "error", message: "Digite o seu PIN de 6 números." }); return; }
    setRunning(key);
    setArming(null);
    setOutcome(undefined);
    if (photoUrl.current) { URL.revokeObjectURL(photoUrl.current); photoUrl.current = undefined; }
    try {
      const started = mode ? await api.startAction!(deviceId, kind, pin, mode) : await api.startAction!(deviceId, kind, pin);
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
      <span className="action-panel__title">{deviceName ? `Ações em ${deviceName}` : "Ações"}</span>
      <span className="action-panel__note">Toda ação pede o seu PIN.</span>
    </div>
    <ul className="action-panel__effects">
      {ACTIONS.map((action) => <li key={action.kind}><strong>{action.label}</strong>: {action.effect}</li>)}
    </ul>
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
    <div className="action-panel__power">
      <span className="action-panel__power-title">Energia</span>
      <ul className="action-panel__effects">
        {POWER.map((item) => <li key={item.mode}><strong>{item.label}</strong>: {item.effect}</li>)}
      </ul>
      <div className="action-panel__buttons">
        {POWER.map((item) => {
          const key = `power:${item.mode}`;
          if (arming === item.mode) {
            return <span className="action-panel__confirm" key={item.mode}>
              <button className="button button--danger" disabled={running !== null} onClick={() => void run("power", item.mode)} type="button">
                {running === key ? "Aguardando..." : `Confirmar ${item.label.toLowerCase()}`}
              </button>
              <button className="button" disabled={running !== null} onClick={() => setArming(null)} type="button">Cancelar</button>
            </span>;
          }
          return <button className="button" disabled={running !== null} key={item.mode}
            onClick={() => { setOutcome(undefined); setArming(item.mode); }} type="button">{item.label}</button>;
        })}
      </div>
    </div>
    {outcome ? <div className={outcome.kind === "error" ? "action-panel__result action-panel__result--error" : "action-panel__result"} role="status">
      <p>{outcome.message}</p>
      {outcome.kind === "done" && outcome.text ? <pre className="action-panel__scan">{outcome.text}</pre> : null}
      {outcome.kind === "done" && outcome.photoUrl ? <img alt="Foto do computador" className="action-panel__photo" src={outcome.photoUrl} /> : null}
    </div> : null}
  </section>;
}
