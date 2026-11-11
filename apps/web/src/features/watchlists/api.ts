import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ToastAction } from "@/components/ui/Toast";
import { api, errorMessage, type Watchlist } from "@/lib/api/client";

export function useWatchlists() {
  return useQuery({ queryKey: ["watchlists"], queryFn: () => api.get<Watchlist[]>("/api/watchlists"), staleTime: 30_000 });
}

export function useMembership(symbol: string | undefined) {
  return useQuery({
    queryKey: ["membership", symbol],
    queryFn: () => api.get<{ symbol: string; watchlist_ids: number[] }>("/api/watchlists/membership", { symbol: symbol! }),
    enabled: Boolean(symbol),
  });
}

function useInvalidate() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["watchlists"] });
    qc.invalidateQueries({ queryKey: ["membership"] });
    qc.invalidateQueries({ queryKey: ["briefing"] });
    qc.invalidateQueries({ queryKey: ["prefs"] });
  };
}

type Toast = (tone: "success" | "error" | "info", text: string, action?: ToastAction) => void;

/** Remove a symbol with a real undo (the toast's Undo re-adds it, at the end of the list). The notices are option-level
 * callbacks on purpose: the star that started the removal unmounts with its row, and callbacks passed to mutate()
 * would then be dropped. */
export function useRemoveWithUndo(toast: Toast) {
  const invalidate = useInvalidate();
  type V = { id: number; symbol: string; name: string };
  const restore = useMutation({
    mutationFn: (v: V) => api.post<Watchlist>(`/api/watchlists/${v.id}/items`, { symbol: v.symbol }),
    onSuccess: (_w, v) => {
      invalidate();
      toast("success", `${v.symbol} is back in ${v.name}.`);
    },
    onError: (e) => toast("error", errorMessage(e)),
  });
  return useMutation({
    mutationFn: (v: V) => api.del<Watchlist>(`/api/watchlists/${v.id}/items`, { symbol: v.symbol }),
    onSuccess: (_w, v) => {
      invalidate();
      toast("success", `Removed ${v.symbol} from ${v.name}.`, { label: "Undo", onClick: () => restore.mutate(v) });
    },
    onError: (e) => toast("error", errorMessage(e)),
  });
}

export function useWatchlistMutations() {
  const invalidate = useInvalidate();
  const opts = { onSuccess: invalidate };
  return {
    create: useMutation({ mutationFn: (name: string) => api.post<Watchlist>("/api/watchlists", { name }), ...opts }),
    rename: useMutation({ mutationFn: (v: { id: number; name: string }) => api.patch<Watchlist>(`/api/watchlists/${v.id}`, { name: v.name }), ...opts }),
    sort: useMutation({
      mutationFn: (v: { id: number; sort_key: string; sort_dir: "asc" | "desc" }) =>
        api.patch<Watchlist>(`/api/watchlists/${v.id}`, { sort_key: v.sort_key, sort_dir: v.sort_dir }),
      ...opts,
    }),
    remove: useMutation({ mutationFn: (id: number) => api.del<null>(`/api/watchlists/${id}`), ...opts }),
    addSymbol: useMutation({ mutationFn: (v: { id: number; symbol: string }) => api.post<Watchlist>(`/api/watchlists/${v.id}/items`, { symbol: v.symbol }), ...opts }),
    removeSymbol: useMutation({ mutationFn: (v: { id: number; symbol: string }) => api.del<Watchlist>(`/api/watchlists/${v.id}/items`, { symbol: v.symbol }), ...opts }),
    reorder: useMutation({ mutationFn: (v: { id: number; symbols: string[] }) => api.put<Watchlist>(`/api/watchlists/${v.id}/order`, { symbols: v.symbols }), ...opts }),
    starter: useMutation({ mutationFn: () => api.post<Watchlist>("/api/workspace/starter-watchlist"), ...opts }),
  };
}

export type KeyFigure = { v: string | null; as_of?: string | null; why?: string };
export interface WatchlistMetrics {
  items: Record<string, (Record<"market_cap" | "pe_ratio" | "from_52w_high_pct" | "return_1y_pct", KeyFigure | undefined> & { computed_at: string; stale: boolean }) | null>;
  refresh_hours: number;
  note: string;
}

/** Key figures from stored screening snapshots (no provider call). */
export function useWatchlistMetrics(id: number | undefined, enabled = true) {
  return useQuery({
    queryKey: ["watchlists", id, "metrics"],
    queryFn: () => api.get<WatchlistMetrics>(`/api/watchlists/${id}/metrics`),
    enabled: enabled && id !== undefined,
    staleTime: 5 * 60_000,
  });
}
