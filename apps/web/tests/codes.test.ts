import { describe, expect, it } from "vitest";
import { parseCommand, securityPath } from "@/lib/codes";

describe("function codes", () => {
  it("reads SYMBOL CODE, a bare security code and global codes", () => {
    const a = parseCommand("reliance.ns fa");
    expect(a?.kind).toBe("security");
    expect(a && a.kind === "security" && a.symbol).toBe("RELIANCE.NS");
    const b = parseCommand("  ern ");
    expect(b && b.kind === "security" && b.symbol).toBeNull();
    expect(parseCommand("eqs")?.kind).toBe("global");
    expect(parseCommand("AAPL EQS")).toBeNull(); // global codes take no symbol
    expect(parseCommand("glasswing")).toBeNull(); // plain searches are not commands
    expect(parseCommand("a b c d")).toBeNull();
  });

  it("builds the instrument URL for a code", () => {
    const fa = parseCommand("AAPL FA");
    expect(fa && fa.kind === "security" && securityPath("AAPL", fa.def)).toBe("/instrument/AAPL?tab=financials");
    const des = parseCommand("SX:AURORA DES");
    expect(des && des.kind === "security" && securityPath("SX:AURORA", des.def)).toBe("/instrument/SX%3AAURORA");
    const hds = parseCommand("AAPL HDS");
    expect(hds && hds.kind === "security" && securityPath("AAPL", hds.def)).toBe("/instrument/AAPL?tab=holders");
  });
});
