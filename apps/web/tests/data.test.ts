import { describe, expect, it } from "vitest";
import { cleanBars, summarizeBars } from "@/features/market/PriceChart";
import { sortRows, type Row } from "@/features/watchlists/WatchlistTable";
import type { Bar, Snapshot } from "@/lib/api/client";

const bar = (time: string, close: string, o?: string, h?: string, l?: string): Bar => ({
  time,
  close,
  open: o ?? null,
  high: h ?? null,
  low: l ?? null,
  volume: 100,
});

describe("cleanBars (validation before rendering)", () => {
  it("sorts ascending, removes duplicate timestamps and invalid closes", () => {
    const { bars, dropped } = cleanBars([
      bar("2026-01-03", "12", "11", "13", "10"),
      bar("2026-01-01", "10", "10", "11", "9"),
      bar("2026-01-03", "12.5", "11", "13", "10"),
      bar("2026-01-02", "0"),
      bar("", "5"),
    ]);
    expect(bars.map((b) => b.time)).toEqual(["2026-01-01", "2026-01-03"]);
    expect(bars[1].close).toBe(12.5);
    expect(dropped).toBe(3);
  });

  it("removes inconsistent candle bodies but keeps the close", () => {
    const { bars, candleGaps } = cleanBars([bar("2026-01-01", "10", "10", "9", "8")]);
    expect(bars[0].open).toBeNull();
    expect(bars[0].close).toBe(10);
    expect(candleGaps).toBe(1);
  });

  it("produces an accessible text summary", () => {
    const { bars } = cleanBars([bar("2026-01-01", "100"), bar("2026-01-02", "110")]);
    expect(summarizeBars(bars, "INR")).toContain("+10.00%");
  });
});

function row(symbol: string, pct: string | null, position: number): Row {
  const snap = {
    symbol,
    instrument: { symbol },
    quote: pct === null ? null : { last_price: "1", change_percent: pct, market_time: "2026-06-30T10:00:00Z" },
    sparkline: [],
    meta: { source: "fixture", status: pct === null ? "missing" : "sample" },
  } as unknown as Snapshot;
  return { symbol, position, snap, name: symbol, exchange: null, country: null };
}

describe("watchlist sorting", () => {
  it("sorts by change and always puts missing values last instead of treating them as zero", () => {
    const rows = [row("A", "-1", 0), row("B", null, 1), row("C", "2", 2), row("D", "0", 3)];
    expect(sortRows(rows, { key: "change_percent", dir: "desc" }).map((r) => r.symbol)).toEqual(["C", "D", "A", "B"]);
    expect(sortRows(rows, { key: "change_percent", dir: "asc" }).map((r) => r.symbol)).toEqual(["A", "D", "C", "B"]);
  });
  it("manual order follows saved positions", () => {
    const rows = [row("A", "1", 2), row("B", "1", 0), row("C", "1", 1)];
    expect(sortRows(rows, { key: "manual", dir: "asc" }).map((r) => r.symbol)).toEqual(["B", "C", "A"]);
  });
});
