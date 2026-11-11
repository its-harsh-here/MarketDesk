import { describe, expect, it } from "vitest";
import { resample, type OHLCV } from "@/lib/resample";

const bar = (time: string, o: number, h: number, l: number, c: number, v: number | null = 10): OHLCV => ({ time, open: o, high: h, low: l, close: c, volume: v });

describe("resample daily bars", () => {
  const days = [
    bar("2026-06-26", 10, 11, 9, 10.5), // Fri, week of 22 Jun
    bar("2026-06-29", 10.5, 12, 10, 11), // Mon, week of 29 Jun
    bar("2026-06-30", 11, 13, 10.8, 12.5), // Tue (month end)
    bar("2026-07-01", 12.5, 12.6, 11, 11.2), // Wed, July
  ];
  it("weekly: first open, max high, min low, last close, summed volume, dated by last session", () => {
    const w = resample(days, "weekly");
    expect(w.map((b) => b.time)).toEqual(["2026-06-26", "2026-07-01"]);
    expect(w[1]).toMatchObject({ open: 10.5, high: 13, low: 10, close: 11.2, volume: 30, sessions: 3 });
  });
  it("monthly splits at the calendar month", () => {
    const m = resample(days, "monthly");
    expect(m.map((b) => [b.time, b.open, b.high, b.low, b.close, b.volume])).toEqual([
      ["2026-06-30", 10, 13, 9, 12.5, 30],
      ["2026-07-01", 12.5, 12.6, 11, 11.2, 10],
    ]);
  });
  it("missing OHLC or volume in any session leaves the period's value missing, not guessed", () => {
    const m = resample([bar("2026-06-29", 1, 2, 0.5, 1.5), { time: "2026-06-30", open: null, high: null, low: null, close: 1.7, volume: null }], "monthly");
    expect(m[0]).toMatchObject({ open: null, high: null, low: null, close: 1.7, volume: null, sessions: 2 });
    expect(resample(days, "daily")).toHaveLength(4);
  });
});
