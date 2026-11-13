import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  TickMarkType,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type MouseEventParams,
  type SeriesType,
  type Time,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import { fxActive } from "@/lib/fx";
import type { Bar } from "@/lib/api/client";
import { formatMoney, formatNumber, formatPercent, formatSessionDate, formatVolume, toNumber } from "@/lib/format";
import { cn } from "@/lib/cn";
import { bollinger, ema, macd, rsi, sma, type IndicatorKey, type Series } from "@/lib/indicators";

export type ChartKind = "line" | "candle";

export interface CleanBar {
  time: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number;
  volume: number | null;
}

/** Validate before rendering: ascending, unique session dates, finite positive closes, consistent OHLC. */
export function cleanBars(bars: Bar[]): { bars: CleanBar[]; dropped: number; candleGaps: number } {
  const byDate = new Map<string, CleanBar>();
  let dropped = 0;
  for (const b of bars) {
    const close = toNumber(b.close);
    if (!b.time || close === null || close <= 0) {
      dropped++;
      continue;
    }
    let open = toNumber(b.open);
    let high = toNumber(b.high);
    let low = toNumber(b.low);
    if (open === null || high === null || low === null || low > Math.min(open, close) || high < Math.max(open, close)) {
      open = high = low = null;
    }
    if (byDate.has(b.time)) dropped++;
    byDate.set(b.time, { time: b.time, open, high, low, close, volume: b.volume ?? null });
  }
  const out = [...byDate.values()].sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
  return { bars: out, dropped, candleGaps: out.filter((b) => b.open === null).length };
}

/** Chart time: a session date ("2026-11-11") stays a business day; an instant becomes a UTC timestamp in seconds. */
export function chartTime(t: string): Time {
  return (t.length > 10 ? Math.floor(Date.parse(t) / 1000) : t) as Time;
}

/** A bar's label: its session date, or for intraday bars the clock time in the given zone. */
export function barLabel(t: string, tz?: string) {
  if (t.length <= 10) return formatSessionDate(t);
  const d = new Date(t);
  return d.toLocaleString("en-GB", { timeZone: tz ?? "Asia/Kolkata", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
}

function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function palette() {
  return {
    text: cssVar("--chart-text") || "#A7B3C4",
    grid: cssVar("--chart-grid") || "#1C2531",
    border: cssVar("--border") || "#2A3545",
    pos: cssVar("--positive") || "#43D3A0",
    neg: cssVar("--negative") || "#FF7185",
    accent: cssVar("--chart-line") || cssVar("--accent") || "#F2B84B",
    a1: cssVar("--accent") || "#a78bfa",
    a2: cssVar("--accent-3") || "#f472b6",
    a3: cssVar("--warning") || "#f6c15b",
    info: cssVar("--info") || "#7cb4ff",
    panel: cssVar("--panel") || "#141B25",
  };
}

function hexAlpha(hex: string, alpha: number) {
  const h = hex.replace("#", "");
  if (h.length !== 6) return hex;
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export function PriceChart({
  bars,
  kind,
  showVolume,
  currency,
  height = 360,
  className,
  resetSignal,
  indicators = [],
  timeZone,
}: {
  bars: CleanBar[];
  kind: ChartKind;
  showVolume: boolean;
  currency: string | null | undefined;
  height?: number;
  className?: string;
  resetSignal?: number;
  indicators?: IndicatorKey[];
  /** Set for intraday bars: axis, crosshair and legend show clock times in this zone. */
  timeZone?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const priceRef = useRef<ISeriesApi<SeriesType> | null>(null);
  const volRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const indRef = useRef<ISeriesApi<SeriesType>[]>([]);
  const [hover, setHover] = useState<CleanBar | null>(null);
  // Width of the plot area (chart minus the price axis), so the legend never runs under the axis labels.
  const [plotWidth, setPlotWidth] = useState(0);
  const [theme, setTheme] = useState(() => document.documentElement.getAttribute("data-theme"));
  const byTime = useMemo(() => new Map(bars.map((b) => [String(chartTime(b.time)), b])), [bars]);

  useEffect(() => {
    const obs = new MutationObserver(() => setTheme(document.documentElement.getAttribute("data-theme")));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, []);

  // create chart once
  useEffect(() => {
    if (!ref.current) return;
    const p = palette();
    const chart = createChart(ref.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: p.text,
        fontFamily: "JetBrains Mono, ui-monospace, monospace",
        fontSize: 11,
        attributionLogo: true,
      },
      grid: { vertLines: { color: p.grid }, horzLines: { color: p.grid } },
      rightPriceScale: { borderColor: p.border },
      // Keep the fitted range when the container resizes (e.g. the layout settling), so no empty band appears.
      timeScale: { borderColor: p.border, rightOffset: 2, minBarSpacing: 0.5, lockVisibleTimeRangeOnResize: true, fixLeftEdge: true },
      crosshair: { mode: CrosshairMode.Magnet },
      localization: { priceFormatter: (v: number) => formatNumber(v, 2) },
    });
    chartRef.current = chart;
    const onSize = (width: number) => setPlotWidth(width);
    chart.timeScale().subscribeSizeChange(onSize);
    return () => {
      chart.timeScale().unsubscribeSizeChange(onSize);
      chart.remove();
      chartRef.current = null;
      priceRef.current = null;
      volRef.current = null;
      indRef.current = [];
    };
  }, []);

  // Intraday bars: show clock times in the chosen zone on the axis and crosshair (the chart itself works in UTC).
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const fmt = (opts: Intl.DateTimeFormatOptions) => (t: Time) =>
      typeof t === "number" ? new Date(t * 1000).toLocaleString("en-GB", { timeZone: timeZone ?? "Asia/Kolkata", hour12: false, ...opts }) : String(t);
    if (timeZone) {
      chart.applyOptions({
        timeScale: {
          timeVisible: true,
          secondsVisible: false,
          // Day-level ticks (a new session) show the date; the others show the clock time.
          tickMarkFormatter: (t: Time, type: TickMarkType) =>
            type <= TickMarkType.DayOfMonth ? fmt({ day: "numeric", month: "short" })(t) : fmt({ hour: "2-digit", minute: "2-digit" })(t),
        },
        localization: { timeFormatter: fmt({ day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) },
      });
    } else {
      chart.applyOptions({ timeScale: { timeVisible: false }, localization: { timeFormatter: undefined } });
    }
  }, [timeZone]);

  // theme colours
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const p = palette();
    chart.applyOptions({
      layout: { textColor: p.text },
      grid: { vertLines: { color: p.grid }, horzLines: { color: p.grid } },
      rightPriceScale: { borderColor: p.border },
      timeScale: { borderColor: p.border },
    });
  }, [theme]);

  // series + data
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const p = palette();
    if (priceRef.current) {
      chart.removeSeries(priceRef.current);
      priceRef.current = null;
    }
    if (volRef.current) {
      chart.removeSeries(volRef.current);
      volRef.current = null;
    }
    for (const s of indRef.current) chart.removeSeries(s);
    indRef.current = [];
    // remove empty lower panes left by indicators that were switched off
    for (let i = chart.panes().length - 1; i > 0; i--) chart.removePane(i);
    if (kind === "candle") {
      const s = chart.addSeries(CandlestickSeries, {
        upColor: p.pos,
        downColor: p.neg,
        borderUpColor: p.pos,
        borderDownColor: p.neg,
        wickUpColor: p.pos,
        wickDownColor: p.neg,
        priceLineVisible: false,
      });
      s.setData(
        bars.map((b) =>
          b.open === null ? { time: chartTime(b.time) } : { time: chartTime(b.time), open: b.open, high: b.high!, low: b.low!, close: b.close },
        ),
      );
      priceRef.current = s as unknown as ISeriesApi<SeriesType>;
    } else {
      // The price line with a gradient fill fading to nothing below it.
      const s = chart.addSeries(AreaSeries, { lineColor: p.accent, topColor: hexAlpha(p.accent, 0.34), bottomColor: hexAlpha(p.accent, 0), lineWidth: 2, priceLineVisible: false, crosshairMarkerRadius: 4 });
      s.setData(bars.map((b) => ({ time: chartTime(b.time), value: b.close })));
      // Decoration: the chart wipes in from the left when its data or style changes.
      const host = ref.current;
      if (host && fxActive()) {
        host.classList.remove("fx-chart-in");
        void host.offsetWidth;
        host.classList.add("fx-chart-in");
      }
      priceRef.current = s as unknown as ISeriesApi<SeriesType>;
    }
    if (showVolume && bars.some((b) => b.volume)) {
      const v = chart.addSeries(HistogramSeries, { priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
      chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      v.setData(
        bars
          .filter((b) => b.volume !== null)
          .map((b, i, arr) => {
            const prev = i > 0 ? arr[i - 1].close : b.open ?? b.close;
            return { time: chartTime(b.time), value: b.volume!, color: hexAlpha(b.close >= prev ? p.pos : p.neg, 0.35) };
          }),
      );
      volRef.current = v;
    }
    // ---- indicators: overlays on the price pane; RSI and MACD each get a pane below
    const closes = bars.map((b) => b.close);
    const line = (vals: Series, color: string, pane = 0, extra: object = {}) => {
      const s = chart.addSeries(LineSeries, { color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, ...extra }, pane);
      s.setData(bars.map((b, i) => (vals[i] === null ? { time: chartTime(b.time) } : { time: chartTime(b.time), value: vals[i]! })));
      indRef.current.push(s as unknown as ISeriesApi<SeriesType>);
      return s;
    };
    const on = new Set(indicators);
    if (on.has("sma20")) line(sma(closes, 20), p.a1);
    if (on.has("sma50")) line(sma(closes, 50), p.a3);
    if (on.has("sma200")) line(sma(closes, 200), p.a2);
    if (on.has("ema20")) line(ema(closes, 20), p.info, 0, { lineStyle: 2 });
    if (on.has("bb")) {
      const b = bollinger(closes);
      line(b.upper, hexAlpha(p.a1, 0.7));
      line(b.mid, hexAlpha(p.a1, 0.45), 0, { lineStyle: 2 });
      line(b.lower, hexAlpha(p.a1, 0.7));
    }
    let pane = 1;
    if (on.has("rsi")) {
      const s = line(rsi(closes), p.a1, pane, { lineWidth: 2, lastValueVisible: true, title: "RSI 14" });
      s.createPriceLine({ price: 70, color: hexAlpha(p.neg, 0.6), lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "" });
      s.createPriceLine({ price: 30, color: hexAlpha(p.pos, 0.6), lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "" });
      pane++;
    }
    if (on.has("macd")) {
      const m = macd(closes);
      const h = chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane);
      h.setData(bars.map((b, i) => (m.hist[i] === null ? { time: chartTime(b.time) } : { time: chartTime(b.time), value: m.hist[i]!, color: hexAlpha(m.hist[i]! >= 0 ? p.pos : p.neg, 0.5) })));
      indRef.current.push(h as unknown as ISeriesApi<SeriesType>);
      line(m.macd, p.info, pane, { lineWidth: 2, title: "MACD" });
      line(m.signal, p.a3, pane, { title: "signal" });
      pane++;
    }
    for (let i = 1; i < chart.panes().length; i++) chart.panes()[i].setHeight(Math.round(height * 0.22));
    chart.priceScale("right").applyOptions({ scaleMargins: { top: 0.08, bottom: showVolume ? 0.22 : 0.08 } });
    chart.timeScale().fitContent();
  }, [bars, kind, showVolume, theme, indicators, height]);

  useEffect(() => {
    chartRef.current?.timeScale().fitContent();
  }, [resetSignal]);

  // crosshair legend
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const fn = (param: MouseEventParams<Time>) => {
      if (!param.time || !param.point) {
        setHover(null);
        return;
      }
      setHover(byTime.get(String(param.time)) ?? null);
    };
    chart.subscribeCrosshairMove(fn);
    return () => chart.unsubscribeCrosshairMove(fn);
  }, [byTime]);

  const shown = hover ?? bars[bars.length - 1] ?? null;
  const prevOfShown = shown ? bars[bars.findIndex((b) => b.time === shown.time) - 1] : undefined;
  const chg = shown && prevOfShown ? ((shown.close - prevOfShown.close) / prevOfShown.close) * 100 : null;

  return (
    <div className={cn("relative", className)} style={{ minHeight: height }}>
      {shown && (
        <div
          className="pointer-events-none absolute top-1 left-2 z-10 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 rounded bg-panel/80 px-1.5 py-0.5 text-[11px] text-fg-2 backdrop-blur-[2px]"
          style={plotWidth > 0 ? { maxWidth: Math.max(120, plotWidth - 16) } : undefined}
          aria-hidden
        >
          <span className="num font-semibold text-fg">{barLabel(shown.time, timeZone)}</span>
          {kind === "candle" && shown.open !== null && (
            <>
              <span className="num">O {formatNumber(shown.open)}</span>
              <span className="num">H {formatNumber(shown.high)}</span>
              <span className="num">L {formatNumber(shown.low)}</span>
            </>
          )}
          <span className="num">C {formatMoney(shown.close, currency)}</span>
          {chg !== null && <span className={cn("num", chg > 0 ? "text-pos" : chg < 0 ? "text-neg" : "")}>{formatPercent(chg)}</span>}
          {showVolume && shown.volume !== null && <span className="num">Vol {formatVolume(shown.volume)}</span>}
        </div>
      )}
      <div ref={ref} className="absolute inset-0" />
    </div>
  );
}

export function summarizeBars(bars: CleanBar[], currency: string | null | undefined) {
  if (bars.length < 2) return "Not enough data to summarize.";
  const first = bars[0];
  const last = bars[bars.length - 1];
  const hi = bars.reduce((m, b) => (b.close > m.close ? b : m), first);
  const lo = bars.reduce((m, b) => (b.close < m.close ? b : m), first);
  const chg = ((last.close - first.close) / first.close) * 100;
  return `Daily closes from ${formatSessionDate(first.time)} to ${formatSessionDate(last.time)} (${bars.length} sessions): ${formatMoney(first.close, currency)} to ${formatMoney(last.close, currency)}, ${formatPercent(chg)}. Highest close ${formatMoney(hi.close, currency)} on ${formatSessionDate(hi.time)}; lowest ${formatMoney(lo.close, currency)} on ${formatSessionDate(lo.time)}.`;
}
