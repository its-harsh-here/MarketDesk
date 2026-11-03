import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Watchlist } from "@/lib/api/client";

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
