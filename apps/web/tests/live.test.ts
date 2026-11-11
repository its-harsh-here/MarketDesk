import { describe, expect, it } from "vitest";
import { applyLive, etClock, extendedLive, liveSummary, streamable, type LiveTick } from "@/lib/live";

const quote = {
  last_price: "100",
  previous_close: "98",
  change: "2",
  change_percent: "2.0408",
  session_date: "2026-11-11",
  market_time: "2026-11-11T17:00:00Z", // 12:00 New York
} as never;
const tick = (time: string, price = 101, cancelled = false): LiveTick => ({ symbol: "AAPL", price, size: 5, time, cancelled });

describe("live IEX overlay", () => {
  it("streams only US listings", () => {
    expect(streamable("AAPL")).toBe(true);
    expect(streamable("BRK-B")).toBe(true);
    expect(streamable("RELIANCE.NS")).toBe(false);
    expect(streamable("^GSPC")).toBe(false);
    expect(streamable("SX:HALCYON")).toBe(false);
  });

  it("converts instants to the New York session clock", () => {
    expect(etClock("2026-11-11T14:30:00Z")).toEqual({ date: "2026-11-11", minutes: 570 });
    expect(etClock("2026-11-12T03:00:00Z")).toEqual({ date: "2026-11-11", minutes: 22 * 60 });
  });

  it("applies a newer regular-session trade against the previous close", () => {
    const q = applyLive(quote, tick("2026-11-11T17:00:05Z", 99));
    expect(q?.last_price).toBe("99");
    expect(Number(q?.change)).toBeCloseTo(1);
    expect(Number(q?.change_percent)).toBeCloseTo(1.0204, 3);
    expect(q?.market_time).toBe("2026-11-11T17:00:05Z");
  });

  it("refuses stale, cancelled, extended-hours and other-session trades", () => {
    expect(applyLive(quote, tick("2026-11-11T16:59:00Z"))).toBeNull(); // older than the quote
    expect(applyLive(quote, tick("2026-11-11T17:01:00Z", 101, true))).toBeNull();
    expect(applyLive(quote, tick("2026-11-11T21:30:00Z"))).toBeNull(); // 16:30 New York: after hours
    expect(applyLive(quote, tick("2026-11-12T15:00:00Z"))).toBeNull(); // next session; previous close would be wrong
    expect(applyLive(null, tick("2026-11-11T17:01:00Z"))).toBeNull();
  });

  it("summarises the stream state without claiming consolidated data", () => {
    const base = { message: null, feedLabel: "IEX (Alpaca) — single exchange, not consolidated", streamed: [], ticks: {} };
    expect(liveSummary({ ...base, status: "live" })?.text).toContain("not consolidated");
    expect(liveSummary({ ...base, status: "reconnecting" })?.text).toContain("polled");
    expect(liveSummary({ ...base, status: "off" })).toBeNull();
  });
});

describe("extended-hours IEX trades", () => {
  it("labels pre-market and after-hours trades against the latest regular price", () => {
    const after = extendedLive(quote, tick("2026-11-11T21:30:00Z", 99)); // 16:30 New York
    expect(after?.label).toBe("After hours");
    expect(after?.change).toBeCloseTo(-1);
    expect(after?.changePercent).toBeCloseTo(-1);
    expect(extendedLive(quote, tick("2026-11-12T13:00:00Z", 102))?.label).toBe("Pre-market"); // 08:00 New York
  });
  it("ignores regular-session, stale and cancelled trades", () => {
    expect(extendedLive(quote, tick("2026-11-11T17:05:00Z"))).toBeNull();
    expect(extendedLive(quote, tick("2026-11-11T12:00:00Z"))).toBeNull(); // before the quote's market time
    expect(extendedLive(quote, tick("2026-11-11T21:30:00Z", 99, true))).toBeNull();
  });
});
