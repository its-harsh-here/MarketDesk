import { afterEach, describe, expect, it } from "vitest";
import { clearRecents, readRecents, recordRecent } from "@/lib/recent";

describe("recently viewed instruments", () => {
  afterEach(() => localStorage.clear());

  it("keeps the newest first, one entry per symbol, at most eight", () => {
    for (let i = 0; i < 10; i++) recordRecent(`S${i}`, `Name ${i}`);
    recordRecent("S3", "Name 3 again");
    const r = readRecents();
    expect(r).toHaveLength(8);
    expect(r[0]).toMatchObject({ symbol: "S3", name: "Name 3 again" });
    expect(r.filter((x) => x.symbol === "S3")).toHaveLength(1);
    expect(r.map((x) => x.symbol)).not.toContain("S0"); // the oldest fell off
  });

  it("ignores corrupt storage and is erased on clear", () => {
    localStorage.setItem("md-recent-instruments", "{nope");
    expect(readRecents()).toEqual([]);
    recordRecent("AAPL", null);
    expect(readRecents()[0]).toMatchObject({ symbol: "AAPL", name: null });
    clearRecents();
    expect(readRecents()).toEqual([]);
  });
});

describe("forgetting a symbol", () => {
  it("removes only that entry", async () => {
    const { forgetRecent } = await import("@/lib/recent");
    recordRecent("A", null);
    recordRecent("B", null);
    forgetRecent("A");
    expect(readRecents().map((r) => r.symbol)).toEqual(["B"]);
    localStorage.clear();
  });
});
