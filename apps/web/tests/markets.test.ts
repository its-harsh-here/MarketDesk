import { describe, expect, it } from "vitest";
import { listingLabel, sessionFor, sessionText } from "@/lib/markets";
import type { MarketSession } from "@/lib/api/client";

const base = { name: "US (NYSE/Nasdaq)", timezone: "America/New_York", calendar: "XNYS", source: "exchange_calendars 4.13.2", as_of: "2026-11-27T17:00:00Z" };

describe("listingLabel", () => {
  it("distinguishes listings that share a company name", () => {
    expect(listingLabel({ exchange: "NSE", country: "IN", currency: "INR", kind: "EQUITY" })).toBe("NSE · IN · INR");
    expect(listingLabel({ exchange: "NYSE", country: "US", currency: "USD", kind: "EQUITY" })).toBe("NYSE · US · USD");
    expect(listingLabel({ exchange: "NasdaqGS", country: "US", currency: null, kind: "ETF" })).toBe("NasdaqGS · US · ETF");
  });
});

describe("sessionText", () => {
  it("states open, closed and unknown in the exchange's own time", () => {
    const open: MarketSession = { ...base, market: "US", state: "open", reason: "Early close today.", closes_at: "2026-11-27T18:00:00Z" };
    expect(sessionText(open)).toMatch(/^Open · closes 27 Nov 2026, 13:00 GMT-5 \(early close\)$/);
    const holiday: MarketSession = { ...base, market: "US", state: "closed", reason: "Exchange holiday.", next_open: "2026-11-27T14:30:00Z" };
    expect(sessionText(holiday)).toMatch(/^Closed · Exchange holiday · opens /);
    const unknown: MarketSession = { ...base, market: "IN", state: "unknown", reason: "Outside the calendar's published data." };
    expect(sessionText(unknown)).toBe("Status unknown · Outside the calendar's published data");
  });
  it("maps an instrument's country to its market", () => {
    const rows = [{ ...base, market: "US", state: "open" as const, reason: "Regular session." }];
    expect(sessionFor(rows, "US")?.market).toBe("US");
    expect(sessionFor(rows, null)).toBeUndefined();
  });
});
