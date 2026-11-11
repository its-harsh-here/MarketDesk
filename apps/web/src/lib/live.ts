import { useEffect, useMemo, useState } from "react";
import type { Snapshot } from "@/lib/api/client";

/** Streaming IEX trades (roadmap M04; docs/DECISIONS.md #65). IEX is one exchange, not consolidated data. */
export interface LiveTick {
  symbol: string;
  price: number;
  size: number | null;
  time: string;
  cancelled: boolean;
}

export type LiveStatus = "off" | "idle" | "connecting" | "live" | "reconnecting" | "error" | "paused";

export interface LiveState {
  status: LiveStatus;
  message: string | null;
  feedLabel: string;
  streamed: string[];
  ticks: Record<string, LiveTick>;
}

const FEED_LABEL = "single-exchange trades (IEX), not consolidated";

/** Symbols the server could stream: US listings only (no Indian suffixes, indices, currencies or sample names). */
export function streamable(symbol: string): boolean {
  return /^[A-Z][A-Z0-9.-]{0,9}$/.test(symbol) && !/\.(NS|BO)$/.test(symbol);
}

const etParts = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/** New York session date and minutes after midnight for an instant. */
export function etClock(iso: string): { date: string; minutes: number } | null {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const p = Object.fromEntries(etParts.formatToParts(d).map((x) => [x.type, x.value]));
  return { date: `${p.year}-${p.month}-${p.day}`, minutes: Number(p.hour) * 60 + Number(p.minute) };
}

/**
 * The polled quote with a newer IEX trade applied, or null when the trade must not replace it: cancelled, not newer
 * than the quote, outside the regular 09:30–16:00 New York session (extended-hours trades are not the session's
 * last price), or from a different session than the quote (its previous close would be the wrong basis).
 */
export function applyLive(quote: NonNullable<Snapshot["quote"]> | null | undefined, tick: LiveTick | undefined) {
  if (!quote || !tick || tick.cancelled) return null;
  const clock = etClock(tick.time);
  if (!clock || clock.minutes < 570 || clock.minutes >= 960) return null;
  if (quote.session_date && quote.session_date !== clock.date) return null;
  if (quote.market_time && new Date(tick.time) <= new Date(quote.market_time)) return null;
  const prev = quote.previous_close != null ? Number(quote.previous_close) : null;
  const change = prev != null && Number.isFinite(prev) ? tick.price - prev : null;
  return {
    ...quote,
    last_price: String(tick.price),
    change: change == null ? null : change.toFixed(4),
    change_percent: change == null || !prev ? null : ((change / prev) * 100).toFixed(4),
    market_time: tick.time,
  };
}

/** Subscribe to the server's IEX trade stream for the given symbols; pauses while the tab is hidden. */
export function useLiveTrades(symbols: string[], enabled = true): LiveState {
  const list = useMemo(() => [...new Set(symbols.filter(streamable))].sort().slice(0, 30), [symbols]);
  const key = list.join(",");
  const [state, setState] = useState<LiveState>({ status: "idle", message: null, feedLabel: FEED_LABEL, streamed: [], ticks: {} });
  const [visible, setVisible] = useState(() => typeof document === "undefined" || document.visibilityState === "visible");

  useEffect(() => {
    const on = () => setVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", on);
    return () => document.removeEventListener("visibilitychange", on);
  }, []);

  useEffect(() => {
    if (!enabled || !key || typeof EventSource === "undefined") return;
    if (!visible) {
      setState((s) => (s.status === "off" ? s : { ...s, status: "paused", message: "Paused while the tab is hidden." }));
      return;
    }
    let closed = false;
    const es = new EventSource(`/api/stream/quotes?symbols=${encodeURIComponent(key)}`);
    es.addEventListener("status", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      setState((s) => ({ ...s, status: d.status, message: d.message ?? null, feedLabel: d.feed_label ?? FEED_LABEL, streamed: d.streamed ?? [] }));
      if (d.status === "off") {
        closed = true;
        es.close(); // the server cannot stream here; do not let EventSource retry forever
      }
    });
    es.addEventListener("trades", (e) => {
      const d = JSON.parse((e as MessageEvent).data) as { trades: LiveTick[] };
      setState((s) => {
        const ticks = { ...s.ticks };
        for (const t of d.trades) ticks[t.symbol] = t;
        return { ...s, ticks };
      });
    });
    es.onerror = () => {
      if (!closed) setState((s) => ({ ...s, status: "reconnecting", message: "Connection to the stream lost; showing polled quotes." }));
    };
    return () => {
      closed = true;
      es.close();
    };
  }, [key, enabled, visible]);

  return state;
}

export function liveSummary(s: LiveState): { tone: "live" | "warn" | "muted"; text: string } | null {
  switch (s.status) {
    case "live":
      return { tone: "live", text: `Live trades: ${s.feedLabel}. Other listings are polled.` };
    case "connecting":
      return { tone: "muted", text: "Connecting to live trades…" };
    case "reconnecting":
      return { tone: "warn", text: `Stream reconnecting — showing polled quotes. ${s.message ?? ""}`.trim() };
    case "error":
      return { tone: "warn", text: `Stream unavailable — showing polled quotes. ${s.message ?? ""}`.trim() };
    case "paused":
      return { tone: "muted", text: "Stream paused while this tab is hidden." };
    default:
      return null; // "off" (not configured) and "idle": polling is the normal state; nothing to announce
  }
}

/**
 * An IEX trade outside the regular session, shown separately (Yahoo-style "Pre-market" / "After hours") with its
 * change from the latest regular-session price. Never replaces the session price itself.
 */
export function extendedLive(quote: NonNullable<Snapshot["quote"]> | null | undefined, tick: LiveTick | undefined) {
  if (!quote || !tick || tick.cancelled) return null;
  const clock = etClock(tick.time);
  if (!clock || (clock.minutes >= 570 && clock.minutes < 960)) return null;
  if (quote.market_time && new Date(tick.time) <= new Date(quote.market_time)) return null;
  const base = Number(quote.last_price);
  if (!Number.isFinite(base) || base <= 0) return null;
  const change = tick.price - base;
  return {
    label: clock.minutes < 570 ? "Pre-market" : "After hours",
    price: tick.price,
    change,
    changePercent: (change / base) * 100,
    time: tick.time,
  };
}
