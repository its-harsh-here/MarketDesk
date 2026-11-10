import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type FixtureState, type Prefs, type Session, type Status } from "@/lib/api/client";

export function useSession() {
  return useQuery({ queryKey: ["session"], queryFn: () => api.get<Session>("/api/auth/session"), staleTime: 60_000, retry: 1 });
}

export function usePrefs() {
  return useQuery({ queryKey: ["prefs"], queryFn: () => api.get<Prefs>("/api/settings"), staleTime: 5 * 60_000 });
}

export function usePatchPrefs() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<Prefs>) => api.patch<Prefs>("/api/settings", patch),
    onSuccess: (data) => {
      qc.setQueryData(["prefs"], data);
      qc.invalidateQueries({ queryKey: ["briefing"] });
    },
  });
}

export function useStatus() {
  return useQuery({ queryKey: ["status"], queryFn: () => api.get<Status>("/api/status"), refetchInterval: 60_000, staleTime: 30_000 });
}

export function useFixture() {
  return useQuery({ queryKey: ["fixture"], queryFn: () => api.get<FixtureState>("/api/fixture"), staleTime: 30_000 });
}

export function useFixtureAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (action: { kind: "advance" } | { kind: "reset" } | { kind: "fault"; enabled: boolean }) =>
      action.kind === "fault"
        ? api.post<FixtureState>("/api/fixture/fault", undefined, { enabled: action.enabled })
        : api.post<FixtureState>(`/api/fixture/${action.kind}`),
    onSuccess: (data) => {
      qc.setQueryData(["fixture"], data);
      // Every market panel depends on the replay cursor / outage switch.
      qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "session" && q.queryKey[0] !== "fixture" });
    },
  });
}

export function applyTheme(theme: Prefs["theme"]) {
  const resolved = theme === "system" ? (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark") : theme;
  document.documentElement.setAttribute("data-theme", resolved);
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", resolved === "light" ? "#F2F3FB" : "#060813");
  try {
    localStorage.setItem("md-theme", theme);
  } catch {
    /* storage unavailable */
  }
}

export function applyDensity(density: Prefs["density"]) {
  if (density === "compact" || density === "terminal") document.documentElement.setAttribute("data-density", density);
  else document.documentElement.removeAttribute("data-density");
  try {
    localStorage.setItem("md-density", density);
  } catch {
    /* storage unavailable */
  }
}
