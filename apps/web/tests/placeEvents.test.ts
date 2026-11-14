import { describe, expect, it } from "vitest";
import { placeEvents, type ChartEvent } from "@/features/market/PriceChart";

const bar = (time: string) => ({ time, open: 1, high: 1, low: 1, close: 1, volume: null });

describe("chart event markers", () => {
  const ev = (date: string, kind: ChartEvent["kind"] = "dividend"): ChartEvent => ({ date, kind, label: kind });
  it("puts an event on its own session, or the next one when it fell on a holiday", () => {
    const bars = [bar("2026-06-10"), bar("2026-06-11"), bar("2026-06-15")];
    expect(placeEvents([ev("2026-06-11")], bars).map((p) => p.bar.time)).toEqual(["2026-06-11"]);
    expect(placeEvents([ev("2026-06-12")], bars).map((p) => p.bar.time)).toEqual(["2026-06-15"]);
  });
  it("puts an event on the weekly bar that contains it", () => {
    const weekly = [bar("2026-06-05"), bar("2026-06-12"), bar("2026-06-19")]; // last session of each week
    expect(placeEvents([ev("2026-06-09", "split")], weekly)[0].bar.time).toBe("2026-06-12");
  });
  it("leaves out events outside the bars shown and sorts by date", () => {
    const bars = [bar("2026-06-10"), bar("2026-06-20")];
    const out = placeEvents([ev("2026-06-18", "results"), ev("2026-01-02"), ev("2026-07-01"), ev("2026-06-12")], bars);
    expect(out.map((p) => p.event.date)).toEqual(["2026-06-12", "2026-06-18"]);
  });
});
