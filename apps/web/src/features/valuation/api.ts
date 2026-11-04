import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export const FIELDS = ["fcf0", "years", "growth_pct", "terminal_growth_pct", "discount_pct", "shares"] as const;
export type Field = (typeof FIELDS)[number];
export type DcfValues = Record<Field, string>;
export type Axis = "discount_pct" | "terminal_growth_pct" | "growth_pct";

export interface ValuationInputs {
  symbol: string;
  name: string | null;
  currency: string;
  price: string | null;
  price_time: string | null;
  sector: string | null;
  dcf_applicable: boolean;
  dcf_reason: string | null;
  defaults: Record<Field, { value: string | null; source: string; warning?: string }>;
  labels: Record<Field, string>;
  cash_flow_definition: string;
  notes: string[];
  hypothetical: string;
}

export interface DcfResult {
  symbol: string;
  currency: string;
  price: string | null;
  inputs: Record<Field, string | number>;
  result: {
    rows: { year: number; fcf: string; discount_factor: string; pv: string }[];
    pv_forecast: string;
    terminal_value: string;
    pv_terminal: string;
    equity_value: string;
    per_share: string;
    terminal_share_pct: string;
    vs_price_pct: string | null;
  };
  sensitivity: { rows_axis: Axis; cols_axis: Axis; rows: string[]; cols: string[]; grid: { value: string | null; why: string | null }[][] };
  hypothetical: string;
  formula: string;
}

export interface RangeOut {
  label: string;
  own_per_share: string | null;
  available: boolean;
  why?: string;
  n?: number;
  multiples?: Record<"min" | "p25" | "median" | "p75" | "max", string>;
  implied?: Record<"min" | "p25" | "median" | "p75" | "max", string>;
}

export interface Multiples {
  symbol: string;
  currency: string | null;
  price: string | null;
  own: { pe_ratio: string | null; price_to_book: string | null };
  peer_source: string;
  peers: { symbol: string; name: string | null; pe_ratio: string | null; price_to_book: string | null; as_of: string | null }[];
  ranges: Record<"pe_ratio" | "price_to_book", RangeOut>;
  method: string;
  hypothetical: string;
}

export interface Scenario {
  id: number;
  name: string;
  case: "bear" | "base" | "bull" | "custom";
  inputs: Record<Field, string | number>;
  notes: string;
  updated_at: string | null;
}

const enc = encodeURIComponent;

export function useValuationInputs(symbol: string) {
  return useQuery({ queryKey: ["valuation", "inputs", symbol], queryFn: () => api.get<ValuationInputs>(`/api/valuation/${enc(symbol)}/inputs`) });
}

export function useDcf() {
  return useMutation({
    mutationFn: (v: { symbol: string; inputs: DcfValues; rows_axis: Axis; cols_axis: Axis }) =>
      api.post<DcfResult>(`/api/valuation/${enc(v.symbol)}/dcf`, { inputs: v.inputs, rows_axis: v.rows_axis, cols_axis: v.cols_axis }),
  });
}

export function useMultiples(symbol: string) {
  return useQuery({ queryKey: ["valuation", "multiples", symbol], queryFn: () => api.get<Multiples>(`/api/valuation/${enc(symbol)}/multiples`), retry: false });
}

export function useScenarios(symbol: string) {
  return useQuery({ queryKey: ["valuation", "scenarios", symbol], queryFn: () => api.get<Scenario[]>(`/api/valuation/${enc(symbol)}/scenarios`) });
}

export function useScenarioMutations(symbol: string) {
  const qc = useQueryClient();
  const onSuccess = () => qc.invalidateQueries({ queryKey: ["valuation", "scenarios", symbol] });
  return {
    create: useMutation({ mutationFn: (s: Omit<Scenario, "id" | "updated_at">) => api.post<Scenario>(`/api/valuation/${enc(symbol)}/scenarios`, s), onSuccess }),
    update: useMutation({ mutationFn: ({ id, ...s }: Omit<Scenario, "updated_at">) => api.put<Scenario>(`/api/valuation/scenarios/${id}`, s), onSuccess }),
    remove: useMutation({ mutationFn: (id: number) => api.del<null>(`/api/valuation/scenarios/${id}`), onSuccess }),
  };
}

export interface StressResult {
  available: boolean;
  reason?: string;
  base: string;
  before: string;
  after: string;
  change: string;
  change_pct: string | null;
  rows: { symbol: string; currency: string; market: string; price_shock_pct: string; fx_shock_pct: string; before: string; after: string; change: string }[];
  cash: { currency: string; fx_shock_pct: string; before: string; after: string; change: string }[];
  unpriced: string[];
  rates: Record<string, { rate: string | null; status: string | null; market_time: string | null }>;
  markets: string[];
  method: string;
  hypothetical: string;
}

export function useStress() {
  return useMutation({
    mutationFn: (body: { account: "INR" | "USD" | "ALL"; market_shocks: Record<string, string>; fx_shocks: Record<string, string>; symbol_shocks?: Record<string, string> }) =>
      api.post<StressResult>("/api/portfolio/stress", body),
  });
}
