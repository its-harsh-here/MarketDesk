import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useCallback, useRef } from "react";
import { api, type Snapshot } from "@/lib/api/client";

/**
 * Prefetch an instrument page when the pointer rests on a link to it (docs/PERFORMANCE_ROADMAP.md 4.2): the page's
 * code and its first data (quote and description) load in the background, so the click opens with data on screen.
 * Uses the same query keys as the page, so nothing is fetched twice.
 */
const done = new Map<string, number>();

export function prefetchInstrument(qc: QueryClient, symbol: string) {
  const last = done.get(symbol) ?? 0;
  if (Date.now() - last < 60_000) return;
  done.set(symbol, Date.now());
  void import("@/features/instrument/InstrumentPage");
  void qc.prefetchQuery({
    queryKey: ["snapshots", symbol],
    queryFn: ({ signal }) => api.get<Snapshot[]>("/api/market/snapshots", { symbols: symbol }, signal),
    staleTime: 30_000,
  });
  void qc.prefetchQuery({
    queryKey: ["terminal", "description", symbol],
    queryFn: () => api.get("/api/terminal/description", { symbol }),
    staleTime: 5 * 60_000,
  });
}

/** Handlers for a link or row: prefetch after the pointer rests ~120 ms (a passing pointer does not trigger it). */
export function usePrefetchOnHover(symbol: string | null | undefined) {
  const qc = useQueryClient();
  const timer = useRef<number | undefined>(undefined);
  const onPointerEnter = useCallback(() => {
    if (!symbol) return;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => prefetchInstrument(qc, symbol), 120);
  }, [qc, symbol]);
  const onPointerLeave = useCallback(() => window.clearTimeout(timer.current), []);
  return { onPointerEnter, onPointerLeave, onFocus: onPointerEnter };
}
