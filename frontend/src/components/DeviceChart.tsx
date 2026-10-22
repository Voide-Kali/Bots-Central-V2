import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { PointerEvent, ReactElement } from "react";
import type { DevicesApi } from "../api/client";
import type { DeviceTelemetry } from "../api/contracts";
import { UnauthenticatedError } from "../api/errors";

/*
 * Live chart of one computer (ADR-018). While it is open the panel asks the agent for one
 * sample per second ("Ao vivo", last 2 minutes); "1 hora" shows the regular 30 s samples.
 * Drawn in SVG from the real samples: no smoothing, gaps stay gaps, peaks and lows marked.
 */

type Range = "live" | "hour";
type Metric = { readonly key: "cpu" | "mem" | "temp"; readonly label: string; readonly unit: string; readonly max: number; readonly value: (s: DeviceTelemetry) => number | null };

const METRICS: readonly Metric[] = [
  { key: "cpu", label: "CPU", unit: "%", max: 100, value: (s) => s.cpuPercent },
  { key: "mem", label: "Memória", unit: "%", max: 100, value: (s) => (s.memoryUsedBytes !== null && s.memoryTotalBytes ? (s.memoryUsedBytes / s.memoryTotalBytes) * 100 : null) },
  { key: "temp", label: "Temperatura", unit: "°C", max: 100, value: (s) => s.temperatureC }
];

const RANGES: Readonly<Record<Range, { readonly minutes: number; readonly seconds: number; readonly every: number; readonly gap: number; readonly label: string }>> = {
  live: { minutes: 2, seconds: 120, every: 1_000, gap: 5_000, label: "Ao vivo" },
  hour: { minutes: 60, seconds: 3_600, every: 10_000, gap: 95_000, label: "1 hora" }
};

const number = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const H = 150;
const PAD_L = 34;
const PAD_R = 8;
const PAD_T = 12;
const PAD_B = 20;

interface Point { readonly t: number; readonly v: number }

function ago(seconds: number): string {
  if (seconds <= 0) return "agora";
  if (seconds < 60) return `-${Math.round(seconds)} s`;
  return `-${Math.round(seconds / 60)} min`;
}

function Chart({ metric, points, now, range }: { readonly metric: Metric; readonly points: readonly Point[]; readonly now: number; readonly range: Range }): ReactElement {
  const gradient = useId();
  const [hover, setHover] = useState<Point>();
  // Draw in real pixels so the labels are never stretched.
  const frame = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(640);
  useEffect(() => {
    const element = frame.current;
    if (!element || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(([entry]) => { if (entry) setW(Math.max(200, Math.round(entry.contentRect.width))); });
    observer.observe(element);
    return () => { observer.disconnect(); };
  }, []);
  const span = RANGES[range].seconds * 1000;
  const top = metric.key === "temp" ? Math.max(100, Math.ceil(Math.max(0, ...points.map((p) => p.v)) / 10) * 10) : metric.max;
  const x = (t: number): number => PAD_L + ((t - (now - span)) / span) * (W - PAD_L - PAD_R);
  const y = (v: number): number => PAD_T + (1 - Math.min(Math.max(v, 0), top) / top) * (H - PAD_T - PAD_B);

  // Split where samples are missing, so an offline period is not drawn as a ramp.
  const segments = useMemo(() => {
    const out: Point[][] = [];
    let current: Point[] = [];
    for (const point of points) {
      const previous = current[current.length - 1];
      if (previous && point.t - previous.t > RANGES[range].gap) { out.push(current); current = []; }
      current.push(point);
    }
    if (current.length) out.push(current);
    return out;
  }, [points, range]);

  const last = points[points.length - 1];
  const peak = points.reduce<Point | undefined>((best, p) => (best === undefined || p.v > best.v ? p : best), undefined);
  const low = points.reduce<Point | undefined>((best, p) => (best === undefined || p.v < best.v ? p : best), undefined);
  const average = points.length ? points.reduce((sum, p) => sum + p.v, 0) / points.length : null;

  function onMove(event: PointerEvent<SVGSVGElement>): void {
    const box = event.currentTarget.getBoundingClientRect();
    const t = now - span + ((event.clientX - box.left) / box.width * W - PAD_L) / (W - PAD_L - PAD_R) * span;
    let best: Point | undefined;
    for (const p of points) if (best === undefined || Math.abs(p.t - t) < Math.abs(best.t - t)) best = p;
    setHover(best);
  }

  const shown = hover ?? last;
  return <figure className="chart">
    <figcaption className="chart__head">
      <span className="chart__label">{metric.label}</span>
      <span className="chart__value num">{shown ? number.format(shown.v) : "—"}<small>{shown ? ` ${metric.unit}` : ""}</small></span>
      <span className="chart__meta num">{hover ? new Date(hover.t).toLocaleTimeString("pt-BR") : peak && low && average !== null ? `pico ${number.format(peak.v)} · baixa ${number.format(low.v)} · média ${number.format(average)}` : "sem medições"}</span>
    </figcaption>
    <div ref={frame}><svg className="chart__svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${metric.label}: ${shown ? number.format(shown.v) + " " + metric.unit : "sem medições"}`} onPointerMove={onMove} onPointerLeave={() => setHover(undefined)}>
      <defs>
        <linearGradient id={gradient} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="var(--pen)" stopOpacity="0.45" />
          <stop offset="100%" stopColor="var(--pen)" stopOpacity="0" />
        </linearGradient>
      </defs>
      {[0, 0.25, 0.5, 0.75, 1].map((f) => <g key={f}>
        <line className="chart__grid" x1={PAD_L} x2={W - PAD_R} y1={y(top * f)} y2={y(top * f)} />
        <text className="chart__tick" x={PAD_L - 6} y={y(top * f) + 3} textAnchor="end">{number.format(top * f)}</text>
      </g>)}
      {[1, 0.5, 0].map((f) => <text className="chart__tick" key={f} x={x(now - span * f)} y={H - 5} textAnchor={f === 1 ? "start" : f === 0 ? "end" : "middle"}>{ago((span * f) / 1000)}</text>)}
      {segments.map((segment, index) => {
        const line = segment.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
        const first = segment[0]!;
        const end = segment[segment.length - 1]!;
        return <g key={index}>
          <path d={`${line} L${x(end.t).toFixed(1)},${y(0)} L${x(first.t).toFixed(1)},${y(0)} Z`} fill={`url(#${gradient})`} />
          <path className="chart__line" d={line} />
        </g>;
      })}
      {peak && points.length > 2 ? <g className="chart__mark chart__mark--peak"><circle cx={x(peak.t)} cy={y(peak.v)} r="3.5" /><text x={x(peak.t)} y={Math.max(y(peak.v) - 7, 10)} textAnchor="middle">pico</text></g> : null}
      {low && points.length > 2 && low.v !== peak?.v ? <g className="chart__mark"><circle cx={x(low.t)} cy={y(low.v)} r="3" /></g> : null}
      {last ? <circle className="chart__now" cx={x(last.t)} cy={y(last.v)} r="4" /> : null}
      {hover ? <g className="chart__cursor"><line x1={x(hover.t)} x2={x(hover.t)} y1={PAD_T} y2={H - PAD_B} /><circle cx={x(hover.t)} cy={y(hover.v)} r="4" /></g> : null}
    </svg></div>
  </figure>;
}

export function DeviceChart({ api, deviceId, onUnauthenticated }: { readonly api: DevicesApi; readonly deviceId: string; onUnauthenticated(): void }): ReactElement | null {
  const [range, setRange] = useState<Range>("live");
  const [samples, setSamples] = useState<readonly DeviceTelemetry[]>([]);
  const [failed, setFailed] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const busy = useRef(false);
  const [openedAt] = useState(() => Date.now());

  // Keep the agent live while this chart is open (the server window is 60 s).
  useEffect(() => {
    if (!api.watch) return undefined;
    const watch = (): void => { void api.watch?.(deviceId).catch((error: unknown) => { if (error instanceof UnauthenticatedError) onUnauthenticated(); }); };
    watch();
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") watch(); }, 30_000);
    return () => { window.clearInterval(timer); };
  }, [api, deviceId, onUnauthenticated]);

  useEffect(() => {
    if (!api.history) return undefined;
    let active = true;
    const load = async (): Promise<void> => {
      if (busy.current || document.visibilityState !== "visible") return;
      busy.current = true;
      try {
        const rows = await api.history!(deviceId, RANGES[range].minutes);
        if (active) { setSamples(rows); setNow(Date.now()); setFailed(false); }
      } catch (error) {
        if (error instanceof UnauthenticatedError) onUnauthenticated();
        else if (active) setFailed(true);
      } finally { busy.current = false; }
    };
    void load();
    const timer = window.setInterval(() => { void load(); }, RANGES[range].every);
    return () => { active = false; window.clearInterval(timer); };
  }, [api, deviceId, onUnauthenticated, range]);

  const series = useMemo(() => METRICS.map((metric) => ({
    metric,
    points: samples.flatMap((sample) => { const v = metric.value(sample); const t = Date.parse(sample.recordedAt); return v === null || !Number.isFinite(t) ? [] : [{ t, v }]; })
  })).filter((item) => item.metric.key !== "temp" || item.points.length > 0), [samples]);

  if (!api.history) return null;
  const lastAt = samples.length ? Date.parse(samples[samples.length - 1]!.recordedAt) : null;
  const liveNow = range === "live" && lastAt !== null && now - lastAt < 5_000;
  return <section aria-label="Gráfico" className="charts">
    <div className="charts__head">
      <span className={liveNow ? "charts__live charts__live--on" : "charts__live"}>{liveNow ? "Ao vivo, 1 medição por segundo" : range === "live" ? (now - openedAt > 20_000 ? "Sem modo ao vivo: atualize o agente deste computador (por enquanto, 1 medição a cada 30 s)" : "Ligando o modo ao vivo (até 10 s)") : "Última hora, 1 medição a cada 30 s"}</span>
      <div aria-label="Período" className="segmented" role="group">{(["live", "hour"] as const).map((item) => <button aria-pressed={range === item} key={item} onClick={() => setRange(item)} type="button">{RANGES[item].label}</button>)}</div>
    </div>
    {failed ? <p className="charts__error" role="status">Não foi possível atualizar o gráfico agora.</p> : null}
    <div className="charts__grid">{series.map(({ metric, points }) => <Chart key={metric.key} metric={metric} now={now} points={points} range={range} />)}</div>
  </section>;
}
