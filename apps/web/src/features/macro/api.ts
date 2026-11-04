import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { UniverseSpec } from "@/features/screener/api";

export interface Change {
  value: string | null;
  unit: "%" | "pp";
  from?: string;
}

export interface MacroSeries {
  symbol: string;
  name: string;
  group: string;
  unit: string;
  kind: "level" | "yield";
  frequency: string;
  revision: string;
  provider: string;
  fetched_at: string | null;
  message: string | null;
  value: string | null;
  observed?: string;
  session_date?: string;
  change_1d?: Change | null;
  changes: Record<"1w" | "1m" | "3m" | "1y", (Change & { from: string }) | null>;
  spark: [string, string][];
  status?: string;
}

export type Window = "1w" | "1m" | "3m" | "1y";

export interface Watchboard {
  series: MacroSeries[];
  not_configured: { name: string; source: string; status: string; why: string }[];
  provider: string;
  note: string;
  briefing: { window: Window; items: { series: string; text: string; linked: { symbol: string; relation: string; direction: string; note: string }[] }[]; note: string };
}

export interface RelRow {
  symbol: string;
  name: string | null;
  sector: string;
  return_pct: string | null;
  why: string | null;
  sector_avg_pct: string | null;
  sector_n: number;
  vs_sector_pp: string | null;
  benchmark_pct: string | null;
  vs_benchmark_pp: string | null;
}

export interface MacroLink {
  id: number;
  symbol: string;
  name: string | null;
  series_symbol: string;
  relation: string;
  direction: "up_helps" | "up_hurts" | "unclear";
  note: string;
  correlation?: { r: string | null; n: number; method: string | null; why: string | null } | null;
}

export function useWatchboard(window: Window) {
  return useQuery({ queryKey: ["macro", "board", window], queryFn: () => api.get<Watchboard>("/api/macro/watchboard", { window }), placeholderData: keepPreviousData, staleTime: 60_000 });
}

export function useSectorRelative(u: UniverseSpec | null, metric: string) {
  return useQuery({
    queryKey: ["macro", "rel", u, metric],
    queryFn: () => api.get<{ rows: RelRow[]; method: string; universe: { label: string } }>("/api/macro/sector-relative", { kind: u!.kind, ...(u!.id !== undefined ? { id: u!.id } : {}), metric }),
    enabled: Boolean(u),
    placeholderData: keepPreviousData,
  });
}

export function useLinks() {
  return useQuery({ queryKey: ["macro", "links"], queryFn: () => api.get<{ links: MacroLink[]; series: { symbol: string; name: string }[]; note: string }>("/api/macro/links", { with_correlation: true }) });
}

export function useLinkMutations() {
  const qc = useQueryClient();
  const onSuccess = () => qc.invalidateQueries({ queryKey: ["macro"] });
  return {
    add: useMutation({ mutationFn: (b: Omit<MacroLink, "id" | "name" | "correlation">) => api.post<MacroLink>("/api/macro/links", b), onSuccess }),
    remove: useMutation({ mutationFn: (id: number) => api.del<null>(`/api/macro/links/${id}`), onSuccess }),
  };
}
