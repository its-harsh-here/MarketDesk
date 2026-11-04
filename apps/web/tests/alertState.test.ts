import { describe, expect, it } from "vitest";
import { alertState } from "@/features/alerts/AlertsPage";
import type { Alert } from "@/lib/api/client";

const base = { active: false, rule: "PRICE", rearm_at: null, events: [], arm_seq: 1 } as unknown as Alert;
const now = Date.parse("2026-11-04T10:00:00Z");

describe("alertState", () => {
  it("names a cooldown and when it ends instead of calling the alert paused", () => {
    expect(alertState({ ...base, rearm_at: "2026-11-04T10:30:00Z" } as Alert, now)).toEqual({ label: "Rearms in 30 min", tone: "info" });
    expect(alertState({ ...base, rearm_at: "2026-11-04T14:00:00Z" } as Alert, now).label).toBe("Rearms in 4 h");
  });
  it("distinguishes triggered (this arm fired) from paused, and filing watches from armed price rules", () => {
    const fired = { ...base, events: [{ arm_seq: 1 }] } as unknown as Alert;
    expect(alertState(fired, now).label).toBe("Triggered");
    expect(alertState({ ...fired, arm_seq: 2 } as Alert, now).label).toBe("Paused");
    expect(alertState({ ...base, active: true } as Alert, now).label).toBe("Armed");
    expect(alertState({ ...base, active: true, rule: "FILING" } as Alert, now).label).toBe("Watching");
  });
});
