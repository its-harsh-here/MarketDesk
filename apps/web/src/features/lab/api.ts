import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export interface Summary {
  start: string;
  end: string;
  days: number;
  end_value: string;
  total_return_pct: number;
  cagr_pct: number | null;
  max_drawdown_pct: number;
  volatility_pct: number | null;
  trades?: number;
  exposure_pct?: number;
  fees?: string;
  symbol?: string;
  error?: string;
}

export interface Run {
  id: number;
  created_at: string;
  symbol: string;
  rule: "buy_and_hold" | "sma_cross" | "momentum";
  params: Record<string, number>;
  costs: { fee_pct: string; slippage_bps: string; starting_cash: string; benchmark: string | null };
  data: { provider: string; range: string; adjustment: string; bars: number; first: string; last: string; hash: string; dividends: number; currency: string | null; dropped_without_open: number };
  summary: { strategy: Summary; buy_and_hold: Summary; benchmark?: Summary };
  results?: {
    strategy: Summary;
    buy_and_hold: Summary;
    benchmark?: Summary;
    trades: { day: string; signal_day: string; side: "BUY" | "SELL"; qty: string; price: string; fee: string }[];
    equity: [string, string][];
    hold_equity: [string, string][];
  };
  label: string;
}

export interface PaperState {
  id: number;
  name: string;
  currency: string;
  starting_cash: string;
  fee_pct: string;
  slippage_bps: string;
  cash: string;
  value: string;
  return_pct: string;
  positions: { symbol: string; quantity: string; last_close: string; as_of: string; market_value: string; cost: string | null }[];
  orders: { id: number; side: string; symbol: string; quantity: string; placed_session: string; status: "pending" | "filled" | "rejected"; reason?: string; fill_day?: string; fill_price?: string; fee?: string }[];
  label: string;
  method: string;
}

export function useRuns() {
  return useQuery({ queryKey: ["lab", "runs"], queryFn: () => api.get<Run[]>("/api/lab/runs") });
}
export function useRun(id: number | null) {
  return useQuery({ queryKey: ["lab", "run", id], queryFn: () => api.get<Run>(`/api/lab/runs/${id}`), enabled: id !== null });
}
export function useReview() {
  return useQuery({ queryKey: ["lab", "review"], queryFn: () => api.get<{ items: { title: string; text: string }[]; label: string }>("/api/lab/review"), staleTime: Infinity });
}
export function useLabMutations() {
  const qc = useQueryClient();
  const inv = () => qc.invalidateQueries({ queryKey: ["lab"] });
  return {
    run: useMutation({ mutationFn: (b: Record<string, unknown>) => api.post<Run>("/api/lab/runs", b), onSuccess: inv }),
    reproduce: useMutation({ mutationFn: (id: number) => api.post<{ same_data: boolean; same_results: boolean; explanation: string }>(`/api/lab/runs/${id}/reproduce`) }),
    removeRun: useMutation({ mutationFn: (id: number) => api.del<null>(`/api/lab/runs/${id}`), onSuccess: inv }),
    createPaper: useMutation({ mutationFn: (b: Record<string, unknown>) => api.post<{ id: number; name: string }>("/api/lab/paper", b), onSuccess: inv }),
    order: useMutation({ mutationFn: ({ id, ...b }: { id: number; side: string; symbol: string; quantity: string }) => api.post<PaperState>(`/api/lab/paper/${id}/orders`, b), onSuccess: inv }),
    cancel: useMutation({ mutationFn: ({ id, oid }: { id: number; oid: number }) => api.del<PaperState>(`/api/lab/paper/${id}/orders/${oid}`), onSuccess: inv }),
  };
}
export function usePaperList() {
  return useQuery({ queryKey: ["lab", "paper"], queryFn: () => api.get<{ id: number; name: string; currency: string }[]>("/api/lab/paper") });
}
export function usePaper(id: number | null) {
  return useQuery({ queryKey: ["lab", "paper", id], queryFn: () => api.get<PaperState>(`/api/lab/paper/${id}`), enabled: id !== null });
}
