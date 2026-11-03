import { describe, expect, it } from "vitest";
import { alertPollMs } from "@/features/alerts/api";

describe("alertPollMs", () => {
  it("follows the worker's sampling interval within 10–60 s", () => {
    expect(alertPollMs(2)).toBe(10_000); // test harness samples every 2 s
    expect(alertPollMs(30)).toBe(30_000);
    expect(alertPollMs(300)).toBe(60_000); // production default: no point polling faster than ~1/min
  });
  it("falls back to one minute when the worker interval is unknown", () => {
    expect(alertPollMs(undefined)).toBe(60_000);
    expect(alertPollMs(0)).toBe(60_000);
  });
});
