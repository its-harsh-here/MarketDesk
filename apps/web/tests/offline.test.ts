import { afterEach, describe, expect, it, vi } from "vitest";
import { clearOffline, offlineEnabled, readSnapshot, setOfflineEnabled, syncSnapshot } from "@/lib/offline";

const SNAP = { version: 1, synced_at: "2026-11-05T10:00:00Z", timezone: "Asia/Kolkata", watchlists: [], accounts: [] };

describe("offline copy", () => {
  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("is off by default and writes nothing while off", async () => {
    expect(offlineEnabled()).toBe(false);
    const spy = vi.spyOn(globalThis, "fetch");
    expect(await syncSnapshot("Asia/Kolkata")).toBeNull();
    expect(spy).not.toHaveBeenCalled();
    expect(readSnapshot()).toBeNull();
  });

  it("turning it off or clearing (sign-out) erases the copy", () => {
    setOfflineEnabled(true);
    localStorage.setItem("md-offline-snapshot", JSON.stringify(SNAP));
    expect(readSnapshot()?.synced_at).toBe(SNAP.synced_at);
    clearOffline();
    expect(readSnapshot()).toBeNull();
    expect(offlineEnabled()).toBe(false);
    setOfflineEnabled(true);
    localStorage.setItem("md-offline-snapshot", JSON.stringify(SNAP));
    setOfflineEnabled(false);
    expect(localStorage.getItem("md-offline-snapshot")).toBeNull();
  });

  it("ignores unknown or corrupt snapshots instead of showing them", () => {
    localStorage.setItem("md-offline-snapshot", "{not json");
    expect(readSnapshot()).toBeNull();
    localStorage.setItem("md-offline-snapshot", JSON.stringify({ ...SNAP, version: 2 }));
    expect(readSnapshot()).toBeNull();
  });
});
