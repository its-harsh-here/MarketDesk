import { describe, expect, it } from "vitest";
import {
  DASH,
  formatInstant,
  formatLargeMoney,
  formatMoney,
  formatPercent,
  formatQuantity,
  formatRatio,
  formatSessionDate,
  formatSignedMoney,
  tone,
} from "@/lib/format";

describe("missing values", () => {
  it("renders an em dash, never zero", () => {
    for (const v of [null, undefined, "", "not-a-number"]) {
      expect(formatMoney(v)).toBe(DASH);
      expect(formatPercent(v)).toBe(DASH);
      expect(formatRatio(v)).toBe(DASH);
      expect(formatLargeMoney(v)).toBe(DASH);
    }
  });
});

describe("percent versus ratio", () => {
  it("formats percent points as percentages", () => {
    expect(formatPercent("6.02", { signed: false })).toBe("6.02%");
    expect(formatPercent("2.5")).toBe("+2.50%");
    expect(formatPercent("-0.3813435025")).toBe("−0.38%");
    expect(formatPercent("0")).toBe("0.00%");
  });
  it("formats ratios with a multiplication sign, never as percent", () => {
    expect(formatRatio("16.79")).toBe("16.79×");
    expect(formatRatio("16.79")).not.toContain("%");
  });
});

describe("money", () => {
  it("uses Indian digit grouping for INR and rounds only for display", () => {
    expect(formatMoney("455835.25")).toBe("₹4,55,835.25");
    expect(formatMoney("111")).toBe("₹111.00");
    expect(formatMoney("55.5")).toBe("₹55.50");
    expect(formatMoney("66.666666666667")).toBe("₹66.67");
  });
  it("shows signs for gains and losses", () => {
    expect(formatSignedMoney("435")).toBe("+₹435.00");
    expect(formatSignedMoney("-45419.75")).toBe("−₹45,419.75");
    expect(tone("-1")).toBe("negative");
    expect(tone("0")).toBe("neutral");
  });
  it("expresses INR market cap in crore and other currencies compactly", () => {
    expect(formatLargeMoney("3343514075136", "INR")).toBe("₹3,34,351 Cr");
    expect(formatLargeMoney("18500000000", "USD")).toBe("$18.5B");
  });
  it("keeps fractional quantities without padding", () => {
    expect(formatQuantity("4.5")).toBe("4.5");
    expect(formatQuantity("30")).toBe("30");
  });
});

describe("dates", () => {
  it("keeps exchange session dates as calendar dates (no timezone shift)", () => {
    expect(formatSessionDate("2026-06-30")).toBe("30 Jun 2026");
  });
  it("renders UTC instants in the display timezone", () => {
    expect(formatInstant("2026-06-30T10:00:00Z", "Asia/Kolkata")).toMatch(/^30 Jun 2026, 15:30 (IST|GMT\+5:30)$/);
    expect(formatInstant("2026-06-30T10:00:00Z", "UTC")).toMatch(/^30 Jun 2026, 10:00 (UTC|GMT)$/);
  });
});
