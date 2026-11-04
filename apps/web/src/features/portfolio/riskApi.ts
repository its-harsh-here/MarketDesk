import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export type PerfAccount = "INR" | "USD" | "ALL";

export interface Performance {
  available: boolean;
  reason?: string;
  account: PerfAccount;
  currency: string;
  start: string;
  end: string;
  days: number;
  observations: number;
  metrics: {
    end_value: string;
    net_flows: string;
    flows_count: number;
    twr_pct: string | null;
    twr_annualized_pct: string | null;
    mwr_annualized_pct: string | null;
    mwr_period_pct: string | null;
    volatility_pct: string | null;
    max_drawdown: { depth_pct: string | null; peak: string | null; trough: string | null; recovered: string | null };
    current_drawdown_pct: string | null;
    best_day: { day: string; pct: string } | null;
    worst_day: { day: string; pct: string } | null;
  };
  benchmark: {
    symbol: string;
    name: string | null;
    currency: string | null;
    total_pct: string | null;
    annualized_pct: string | null;
    volatility_pct: string | null;
    max_drawdown_pct: string | null;
    excess_pct: string | null;
    beta: string | null;
    correlation: string | null;
    n: number;
    beta_note: string | null;
    currency_note: string | null;
  } | null;
  series: { dates: string[]; value: string[]; index: number[]; benchmark: (number | null)[]; underwater: number[] };
  skipped: { count: number; examples: string[] };
  missing_history: string[];
  warnings: string[];
  notes: string[];
  policies: string[];
}

export interface Bucket {
  name: string;
  value: string;
  pct_of_total: string | null;
  pct_of_invested: string | null;
}

export interface Exposure {
  available: boolean;
  reason?: string;
  currency: string;
  total: string;
  invested: string;
  cash: string;
  cash_pct: string | null;
  by_holding: Bucket[];
  by_sector: Bucket[];
  by_country: Bucket[];
  by_currency: Bucket[];
  concentration: { largest_pct: string | null; top5_pct: string | null; hhi: string | null; effective_holdings: string | null; formula: string };
  unpriced: string[];
  note: string;
}

export interface CorrCell {
  r: string | null;
  n: number;
  method: "daily" | "weekly" | "same";
  why?: string | null;
}

export interface Correlations {
  available: boolean;
  reason?: string;
  symbols: string[];
  benchmark: string | null;
  matrix: CorrCell[][];
  missing: string[];
  truncated: number;
  window: string;
  method: string;
}

export interface Target {
  symbol: string;
  target_pct: string;
}

export interface SimRow {
  symbol: string;
  price: string;
  quantity: string;
  value: string;
  target_pct: string;
  target_value: string;
  trade_shares: string;
  trade_value: string;
  fee: string;
  new_quantity: string;
  new_value: string;
  weight_pct: string | null;
  new_weight_pct: string | null;
}

export interface Simulation {
  account: "INR" | "USD";
  currency: string;
  total: string;
  cash_before: string;
  extra_cash: string;
  cash_after: string;
  cash_weight_after_pct: string | null;
  fees: string;
  target_sum_pct: string;
  rows: SimRow[];
  unpriced: string[];
  targets_without_holding: string[];
  warnings: string[];
  note: string;
  marks_complete: boolean;
}

export function usePerformance(account: PerfAccount, benchmark: string | null) {
  return useQuery({
    queryKey: ["perf", account, benchmark],
    queryFn: () => api.get<Performance>("/api/portfolio/performance", { account, ...(benchmark ? { benchmark } : {}) }),
    staleTime: 60_000,
  });
}

export function useExposure(account: PerfAccount) {
  return useQuery({ queryKey: ["exposure", account], queryFn: () => api.get<Exposure>("/api/portfolio/exposure", { account }), staleTime: 60_000 });
}

export function useCorrelations(account: PerfAccount, benchmark: string | null) {
  return useQuery({
    queryKey: ["correlations", account, benchmark],
    queryFn: () => api.get<Correlations>("/api/portfolio/correlations", { account, ...(benchmark ? { benchmark } : {}) }),
    staleTime: 5 * 60_000,
  });
}

export function useTargets(account: "INR" | "USD") {
  return useQuery({ queryKey: ["targets", account], queryFn: () => api.get<{ account: string; targets: Target[] }>("/api/portfolio/targets", { account }) });
}

export function useSaveTargets(account: "INR" | "USD") {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (targets: Target[]) => api.put<{ targets: Target[] }>(`/api/portfolio/targets?account=${account}`, { targets }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["targets", account] }),
  });
}

export function useSimulate() {
  return useMutation({
    mutationFn: (body: { account: "INR" | "USD"; extra_cash: string; whole_shares: boolean; fee_pct: string }) =>
      api.post<Simulation>("/api/portfolio/rebalance", body),
  });
}
