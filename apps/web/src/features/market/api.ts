import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, type ActionsResponse, type CompareResponse, type Fundamentals, type HistoryResponse, type Instrument, type DataMeta, type MarketSession, type Snapshot } from "@/lib/api/client";

export type Range = "1M" | "3M" | "6M" | "1Y" | "5Y";
export const RANGES: Range[] = ["1M", "3M", "6M", "1Y", "5Y"];

export function useSnapshots(symbols: string[], enabled = true) {
  const key = symbols.join(",");
  return useQuery({
    queryKey: ["snapshots", key],
    queryFn: ({ signal }) => api.get<Snapshot[]>("/api/market/snapshots", { symbols: key }, signal),
    enabled: enabled && symbols.length > 0,
    refetchInterval: 60_000, // paused automatically while the tab is hidden
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

export function useBenchmarks() {
  return useQuery({
    queryKey: ["benchmarks"],
    queryFn: ({ signal }) => api.get<Snapshot[]>("/api/market/benchmarks", undefined, signal),
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

export function useHistory(symbol: string | null | undefined, range: Range) {
  return useQuery({
    queryKey: ["history", symbol, range],
    queryFn: ({ signal }) => api.get<HistoryResponse>("/api/market/history", { symbol: symbol!, range }, signal),
    enabled: Boolean(symbol),
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
  });
}

export function useFundamentals(symbol: string | undefined) {
  return useQuery({
    queryKey: ["fundamentals", symbol],
    queryFn: ({ signal }) => api.get<Fundamentals>("/api/market/fundamentals", { symbol: symbol! }, signal),
    enabled: Boolean(symbol),
    staleTime: 60 * 60_000,
  });
}

export function useActions(symbol: string | undefined) {
  return useQuery({
    queryKey: ["actions", symbol],
    queryFn: ({ signal }) => api.get<ActionsResponse>("/api/market/actions", { symbol: symbol! }, signal),
    enabled: Boolean(symbol),
    staleTime: 60 * 60_000,
  });
}

export interface SearchResponse {
  results: Instrument[];
  meta: DataMeta;
}

export type Region = "all" | "IN" | "US";

/** Remote symbol search. TanStack Query aborts superseded requests through the signal. */
export function useSymbolSearch(q: string, region: Region = "all") {
  const query = q.trim();
  return useQuery({
    queryKey: ["search", query.toLowerCase(), region],
    queryFn: ({ signal }) => api.get<SearchResponse>("/api/market/search", { q: query, limit: 8, region }, signal),
    enabled: query.length >= 1,
    staleTime: 10 * 60_000,
    placeholderData: keepPreviousData,
  });
}

/** Exchange session states from published calendars (refreshed each minute; not a live exchange feed). */
export function useSessions() {
  return useQuery({
    queryKey: ["sessions"],
    queryFn: ({ signal }) => api.get<MarketSession[]>("/api/market/sessions", undefined, signal),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

export function useCompare(symbols: string[], range: Range) {
  const key = symbols.join(",");
  return useQuery({
    queryKey: ["compare", key, range],
    queryFn: ({ signal }) => api.get<CompareResponse>("/api/market/compare", { symbols: key, range }, signal),
    enabled: symbols.length >= 2,
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
  });
}
