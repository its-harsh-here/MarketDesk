import { describe, expect, it } from "vitest";
import { parseSpec, specKey } from "@/features/screener/api";

describe("screener universe keys", () => {
  it("round-trips built-in universes the API sends with id null", () => {
    const holdings = { kind: "holdings", id: null } as never;
    expect(specKey(holdings)).toBe("holdings");
    expect(parseSpec(specKey(holdings))).toEqual({ kind: "holdings" });
    expect(specKey({ kind: "watchlists" })).toBe("watchlists");
  });
  it("keeps numeric ids and rejects junk", () => {
    expect(parseSpec("watchlist:3")).toEqual({ kind: "watchlist", id: 3 });
    expect(specKey({ kind: "list", id: 7 })).toBe("list:7");
    expect(parseSpec("watchlist:null")).toEqual({ kind: "watchlist" });
    expect(parseSpec("everything")).toBeNull();
  });
});
