import { describe, expect, it } from "vitest";
import { bollinger, ema, macd, rsi, sma } from "@/lib/indicators";

describe("technical indicators (hand vectors)", () => {
  it("SMA and EMA", () => {
    expect(sma([1, 2, 3, 4, 5], 3)).toEqual([null, null, 2, 3, 4]);
    // EMA3, k = 0.5, seeded with SMA(1,2,3) = 2: 4·0.5+2·0.5 = 3, 5·0.5+3·0.5 = 4
    expect(ema([1, 2, 3, 4, 5], 3)).toEqual([null, null, 2, 3, 4]);
    const e = ema([2, 4, 6, 12], 2); // k = 2/3, seed 3: 6·⅔ + 3·⅓ = 5, 12·⅔ + 5·⅓ = 9.667
    expect(e.slice(0, 3)).toEqual([null, 3, 5]);
    expect(e[3]).toBeCloseTo(9.6667, 4);
  });

  it("Bollinger uses the population standard deviation", () => {
    const b = bollinger([2, 4, 4, 4, 5, 5, 7, 9], 8, 2); // classic set: mean 5, SD 2
    expect(b.mid[7]).toBe(5);
    expect(b.upper[7]).toBe(9);
    expect(b.lower[7]).toBe(1);
    expect(b.upper[6]).toBeNull();
  });

  it("RSI: all gains → 100, all losses → 0, flat → 50, Wilder smoothing", () => {
    expect(rsi([1, 2, 3, 4], 3)[3]).toBe(100);
    expect(rsi([4, 3, 2, 1], 3)[3]).toBe(0);
    expect(rsi([1, 1, 1, 1], 3)[3]).toBe(50);
    // n = 2: changes +2, −1 → avg gain 1, avg loss 0.5 → RSI 66.67; then +1 → gain (1·1+1)/2 = 1, loss 0.25 → 80
    const r = rsi([10, 12, 11, 12], 2);
    expect(r[2]).toBeCloseTo(66.6667, 3);
    expect(r[3]).toBeCloseTo(80, 6);
    expect(rsi([1, 2], 14).every((x) => x === null)).toBe(true);
  });

  it("MACD: a straight line has a constant MACD and a zero histogram once the signal exists", () => {
    const v = Array.from({ length: 60 }, (_, i) => 100 + i);
    const m = macd(v);
    expect(m.macd[24]).toBeNull();
    expect(m.macd[25]).not.toBeNull();
    expect(m.signal[33]).not.toBeNull();
    expect(m.signal[32]).toBeNull();
    expect(Math.abs(m.hist[59]!)).toBeLessThan(1e-9);
    expect(m.macd[59]).toBeCloseTo(7, 6); // lag difference of EMA12 and EMA26 on a slope of 1: (26−12)/2
  });
});
