import { describe, expect, it } from "vitest";
import { periodLabel, periodTitle } from "@/lib/format";

describe("financial period labels", () => {
  it("names fiscal years and quarter months, not days", () => {
    expect(periodLabel("2026-03-31", "annual")).toBe("FY2026");
    expect(periodLabel("2025-09-27", "annual")).toBe("FY2025"); // a 52/53-week year ending late September
    expect(periodLabel("2026-09-30", "quarterly")).toBe("Sep 2026");
    expect(periodLabel("2024-06-29", "quarterly")).toBe("Jun 2024");
  });
  it("puts a period ending in a month's first week in the month before", () => {
    expect(periodLabel("2025-10-04", "quarterly")).toBe("Sep 2025");
    expect(periodLabel("2025-01-03", "annual")).toBe("FY2024");
  });
  it("keeps the exact end for the tooltip", () => {
    expect(periodTitle("2026-03-31", "annual")).toBe("Fiscal year ended 31 Mar 2026");
    expect(periodLabel(null, "annual")).toBe("—");
  });
});
