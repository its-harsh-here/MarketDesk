import { describe, expect, it } from "vitest";
import { lineDiff } from "@/lib/diff";

describe("lineDiff", () => {
  it("keeps unchanged lines and marks removals before additions", () => {
    expect(lineDiff("thesis\nrisk A\nexit", "thesis\nrisk B\nexit")).toEqual([
      { type: "same", text: "thesis" },
      { type: "del", text: "risk A" },
      { type: "add", text: "risk B" },
      { type: "same", text: "exit" },
    ]);
  });
  it("handles empty sides and identical text", () => {
    expect(lineDiff("", "new")).toEqual([{ type: "add", text: "new" }]);
    expect(lineDiff("old", "")).toEqual([{ type: "del", text: "old" }]);
    expect(lineDiff("same", "same")).toEqual([{ type: "same", text: "same" }]);
  });
});
