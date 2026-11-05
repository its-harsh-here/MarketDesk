import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Prefs } from "@/lib/api/client";
import { applyDensity, usePrefs } from "@/features/settings/api";

export type Workspace = {
  id: string;
  name: string;
  start: string;
  density: "comfortable" | "compact";
  default_watchlist_id: number | null;
  chart_symbol: string | null;
};
export type WorkspaceInput = Omit<Workspace, "id"> & { capture?: boolean };
export type Workspaces = { active: string | null; items: Workspace[]; start_pages: { path: string; label: string }[] };

export function useWorkspaces(enabled = true) {
  return useQuery({ queryKey: ["workspaces"], queryFn: () => api.get<Workspaces>("/api/workspaces"), staleTime: 5 * 60_000, enabled });
}

/** Apply a workspace: the server updates the preferences it names; the page follows its start page. */
export function useApplyWorkspace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<{ workspace: Workspace; prefs: Prefs; notes: string[] }>(`/api/workspaces/${id}/apply`),
    onSuccess: (r) => {
      qc.setQueryData(["prefs"], r.prefs);
      applyDensity(r.prefs.density);
      qc.setQueryData<Workspaces>(["workspaces"], (old) => (old ? { ...old, active: r.workspace.id } : old));
      qc.invalidateQueries({ queryKey: ["briefing"] });
    },
  });
}

export function useWorkspaceMutations() {
  const qc = useQueryClient();
  const done = () => qc.invalidateQueries({ queryKey: ["workspaces"] });
  return {
    create: useMutation({ mutationFn: (w: WorkspaceInput) => api.post<Workspace>("/api/workspaces", w), onSuccess: done }),
    replace: useMutation({ mutationFn: ({ id, ...w }: Workspace) => api.put<Workspace>(`/api/workspaces/${id}`, w), onSuccess: done }),
    remove: useMutation({ mutationFn: (id: string) => api.del<null>(`/api/workspaces/${id}`), onSuccess: done }),
  };
}

/** Browser polling interval for quotes and valuations from the owner's refresh preference (0 = manual only). */
export function useQuoteRefreshMs(): number | false {
  const { data } = usePrefs();
  const s = data?.quote_refresh_seconds ?? 60;
  return s === 0 ? false : s * 1000;
}

type Counter = { requests: number; cache_hits: number; upstream_calls: number; upstream_failures: number; stale_served: number };
export type Usage = {
  provider: {
    provider: string;
    sample: boolean;
    circuit: string;
    since: string;
    by_kind: Record<string, Counter>;
    cache_ttl_seconds: Record<string, number>;
    endpoints: Record<string, { circuit: string; consecutive_failures: number; last_error: { kind?: string; message?: string } | null }>;
    note: string;
  };
  sec: { enabled: boolean; reason: string | null; max_requests_per_second: number };
  ai: {
    enabled: boolean;
    reason: string | null;
    provider_label: string | null;
    model: string | null;
    free_tier: boolean;
    budget: { requests_used: number; requests_limit: number; tokens_used: number; tokens_limit: number | null; spent_usd: string; limit_usd: string | null };
    server_caps: { requests: number; tokens: number; usd: string };
    owner_quotas: { requests: number | null; tokens: number | null; usd: string | null };
  };
  refresh: { quote_refresh_seconds: number; worker_poll_seconds: number };
};

export function useUsage() {
  return useQuery({ queryKey: ["usage"], queryFn: () => api.get<Usage>("/api/usage"), refetchInterval: 60_000 });
}

export function useSetQuotas() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (q: { requests: number | null; tokens: number | null; usd: string | null }) => api.put("/api/usage/quotas", q),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["usage"] });
      qc.invalidateQueries({ queryKey: ["ai"] });
    },
  });
}

export type ExportSection = "ai" | "journal" | "holdings";

/** Download one instrument's research as Markdown. Private sections are only included when asked for. */
export async function downloadResearch(symbol: string, include: ExportSection[]) {
  const text = await api.get<string>("/api/export/research", { symbol, include: include.join(",") });
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `marketdesk-${symbol.replace(/[^A-Za-z0-9_-]/g, "-")}-${new Date().toISOString().slice(0, 10)}.md`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
