import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export type MetricUnit = "currency" | "percent" | "multiple" | "shares";

export interface MetricDef {
  key: string;
  label: string;
  group: string;
  unit: MetricUnit;
  source: "quote" | "history" | "fundamentals" | "statements";
  formula: string;
}

export interface Catalog {
  metrics: MetricDef[];
  text_fields: { key: string; label: string }[];
  heatmap_metrics: string[];
  default_columns: string[];
}

export type UniverseKind = "watchlists" | "watchlist" | "holdings" | "list";
export interface UniverseSpec {
  kind: UniverseKind;
  id?: number;
}
export interface UniverseOption extends UniverseSpec {
  label: string;
  count: number;
  name?: string;
  symbols?: string[];
}

export interface Cell {
  v: string | null;
  why?: string | null;
  as_of?: string | null;
  from?: string;
  n?: number;
}

export interface InputMeta {
  status: string;
  source?: string;
  fetched_at?: string | null;
  message?: string | null;
  adjustment?: string | null;
  source_label?: string | null;
}

export interface ScreenRow {
  symbol: string;
  name: string | null;
  exchange: string | null;
  currency: string | null;
  country: string | null;
  kind: string | null;
  sector: string | null;
  industry: string | null;
  metrics: Record<string, Cell | null> | null;
  computed_at: string | null;
  inputs: Record<string, InputMeta> | null;
}

export interface Filter {
  metric: string;
  op: "gte" | "lte" | "between" | "in";
  value?: string;
  value2?: string;
  currency?: "INR" | "USD";
  values?: string[];
}

export interface DatasetStatus {
  members: number;
  loaded: number;
  stale: number;
  not_loaded: string[];
  oldest: string | null;
  newest: string | null;
  refresh_hours: number;
}

export interface FxNote {
  pair?: string;
  rate: string | null;
  market_time?: string | null;
  status?: string | null;
  source?: string | null;
  message?: string;
}

export interface UniverseInfo {
  spec: UniverseSpec;
  label: string;
  excluded: string[];
  truncated: number;
}

export interface ScreenResult {
  universe: UniverseInfo;
  filters: Filter[];
  funnel: { filter: Filter; passed: number; failed: number; missing: number }[];
  matched: number;
  rows: ScreenRow[];
  coverage: Record<string, { with_value: number; members: number; as_of_min: string | null; as_of_max: string | null }>;
  dataset: DatasetStatus;
  fx: FxNote | null;
  note: string;
}

export interface SavedScreen {
  id: number;
  name: string;
  universe: UniverseSpec;
  filters: Filter[];
  sort: { key: string; dir: "asc" | "desc" } | null;
}

export interface RefreshState {
  running: boolean;
  label?: string;
  done?: number;
  total?: number | null;
  started_at?: string;
  finished_at?: string;
  result?: { due: number; refreshed: number; failed: { symbol: string; error: string }[]; remaining: number };
  error?: string;
}

export interface HeatSector {
  sector: string;
  members: number;
  used: number;
  value: string | null;
  weight_total_inr: string | null;
  items: { symbol: string; name: string | null; value: string | null; why: string | null; as_of: string | null; market_cap_inr: string | null }[];
}

export interface Heatmap {
  universe: UniverseInfo;
  metric: string;
  weighting: "equal" | "market_cap";
  requested_weighting: string;
  sectors: HeatSector[];
  dataset: DatasetStatus;
  fx: FxNote | null;
  notes: string[];
  method: string;
}

export interface Peers {
  symbol: string;
  source: "saved" | "suggested";
  peers: { symbol: string; reason: string }[];
  rows: ScreenRow[];
  fx: FxNote | null;
  note: string;
}

// The API sends `id: null` for the built-in universes (all watchlists, holdings): treat null like a missing id, or
// the key becomes "holdings:null", parses back to NaN and never matches an option (the list switch did nothing).
export const specKey = (u: UniverseSpec) => (u.id == null ? u.kind : `${u.kind}:${u.id}`);
export const parseSpec = (s: string | null): UniverseSpec | null => {
  if (!s) return null;
  const [kind, id] = s.split(":");
  if (!["watchlists", "watchlist", "holdings", "list"].includes(kind)) return null;
  const n = Number(id);
  return id && Number.isInteger(n) ? { kind: kind as UniverseKind, id: n } : { kind: kind as UniverseKind };
};

export function useCatalog() {
  return useQuery({ queryKey: ["screener", "catalog"], queryFn: () => api.get<Catalog>("/api/screener/catalog"), staleTime: Infinity });
}

export function useUniverses() {
  return useQuery({
    queryKey: ["screener", "universes"],
    queryFn: () => api.get<{ options: UniverseOption[]; max_size: number }>("/api/screener/universes"),
    staleTime: 30_000,
  });
}

export function useScreen(universe: UniverseSpec | null, filters: Filter[], sort: { key: string; dir: "asc" | "desc" } | null) {
  return useQuery({
    queryKey: ["screener", "run", universe, filters, sort],
    queryFn: () => api.post<ScreenResult>("/api/screener/run", { universe, filters, sort }),
    enabled: Boolean(universe),
    placeholderData: keepPreviousData,
    retry: false,
  });
}

export function useHeatmap(universe: UniverseSpec | null, metric: string, weighting: string) {
  return useQuery({
    queryKey: ["screener", "heatmap", universe, metric, weighting],
    queryFn: () => api.get<Heatmap>("/api/screener/heatmap", { kind: universe!.kind, ...(universe!.id !== undefined ? { id: universe!.id } : {}), metric, weighting }),
    enabled: Boolean(universe),
    placeholderData: keepPreviousData,
    retry: false,
  });
}

/** A refresh finished: screens, heatmaps and peers now read the new snapshots. */
function refreshed(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["screener", "run"] });
  qc.invalidateQueries({ queryKey: ["screener", "heatmap"] });
  qc.invalidateQueries({ queryKey: ["screener", "peers"] });
}

export function useRefreshState() {
  const qc = useQueryClient();
  return useQuery({
    queryKey: ["screener", "refresh"],
    queryFn: async () => {
      const prev = qc.getQueryData<RefreshState>(["screener", "refresh"]);
      const st = await api.get<RefreshState>("/api/screener/refresh");
      if (prev && !st.running && st.finished_at && st.finished_at !== prev.finished_at) refreshed(qc);
      return st;
    },
    refetchInterval: (q) => (q.state.data?.running ? 1500 : false),
  });
}

export function useStartRefresh() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (universe: UniverseSpec) => api.post<RefreshState>("/api/screener/refresh", { universe }),
    onSuccess: (st) => {
      qc.setQueryData(["screener", "refresh"], st);
      // Nothing was due (for example the worker had already loaded the members): the job finished before this
      // response, so no poll will see it finish. Re-read the results now rather than keep showing the old ones.
      if (!st.running) refreshed(qc);
    },
  });
}

export function useSavedScreens() {
  return useQuery({ queryKey: ["screener", "screens"], queryFn: () => api.get<SavedScreen[]>("/api/screener/screens") });
}

export function useScreenMutations() {
  const qc = useQueryClient();
  const onSuccess = () => qc.invalidateQueries({ queryKey: ["screener", "screens"] });
  return {
    create: useMutation({ mutationFn: (s: Omit<SavedScreen, "id">) => api.post<SavedScreen>("/api/screener/screens", s), onSuccess }),
    update: useMutation({ mutationFn: ({ id, ...s }: Partial<SavedScreen> & { id: number }) => api.patch<SavedScreen>(`/api/screener/screens/${id}`, s), onSuccess }),
    remove: useMutation({ mutationFn: (id: number) => api.del<null>(`/api/screener/screens/${id}`), onSuccess }),
  };
}

export interface ListOut {
  id: number;
  name: string;
  symbols: string[];
  skipped: { symbol: string; reason: string }[];
}

export function useListMutations() {
  const qc = useQueryClient();
  // A list's members changed: its count, results, heatmap and data status are all out of date. Returning the promise
  // makes the mutation wait for the refetch, so the page switches to the saved list with its new members.
  const onSuccess = () => qc.invalidateQueries({ queryKey: ["screener"] });
  return {
    create: useMutation({ mutationFn: (v: { name: string; symbols: string }) => api.post<ListOut>("/api/screener/universes", v), onSuccess }),
    update: useMutation({ mutationFn: ({ id, ...v }: { id: number; name?: string; symbols?: string }) => api.patch<ListOut>(`/api/screener/universes/${id}`, v), onSuccess }),
    remove: useMutation({ mutationFn: (id: number) => api.del<null>(`/api/screener/universes/${id}`), onSuccess }),
  };
}

export function usePeers(symbol: string) {
  return useQuery({ queryKey: ["screener", "peers", symbol], queryFn: () => api.get<Peers>(`/api/screener/peers/${encodeURIComponent(symbol)}`), retry: false, staleTime: 10 * 60_000 });
}

export function usePeerMutations(symbol: string) {
  const qc = useQueryClient();
  const onSuccess = (p: Peers) => qc.setQueryData(["screener", "peers", symbol], p);
  return {
    save: useMutation({ mutationFn: (symbols: string[]) => api.put<Peers>(`/api/screener/peers/${encodeURIComponent(symbol)}`, { symbols }), onSuccess }),
    reset: useMutation({ mutationFn: () => api.del<Peers>(`/api/screener/peers/${encodeURIComponent(symbol)}`), onSuccess }),
  };
}

/** Download the current screen as CSV (a POST, so it goes through fetch with the CSRF-free read endpoint). */
export async function downloadScreenCsv(universe: UniverseSpec, filters: Filter[], sort: { key: string; dir: "asc" | "desc" } | null) {
  const res = await fetch("/api/screener/export", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/csv" },
    credentials: "same-origin",
    body: JSON.stringify({ universe, filters, sort }),
  });
  if (!res.ok) throw new Error(`Export failed (HTTP ${res.status}).`);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = "marketdesk-screen.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
