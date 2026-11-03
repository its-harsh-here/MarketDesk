import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export type ResearchStatus = "available" | "cached" | "stale" | "not_configured" | "not_applicable" | "missing" | "unavailable";

export interface ResearchEnvelope<T> {
  symbol: string;
  source: string;
  status: ResearchStatus;
  reason?: string | null;
  cik?: number | null;
  fetched_at?: string | null;
  checks?: Record<string, { last_checked_at: string | null; last_success_at: string | null; last_error: string | null }> | null;
  data: T | null;
}

export interface FactValue {
  value: string;
  unit: string;
  taxonomy: string;
  tag: string;
  start: string | null;
  end: string;
  form: string;
  filed: string;
  accession: string;
  restated: boolean;
  prior: { value: string; filed: string; accession: string; form: string }[];
  source_url: string;
}

export interface StatementLine {
  key: string;
  label: string;
  statement: "income" | "balance" | "cashflow";
  kind: "duration" | "instant";
  status: "available" | "unavailable" | "not_applicable";
  reason?: string;
  values: FactValue[];
}

export interface Ratio {
  key: string;
  formula: string;
  value: string | null;
  unit: string | null;
  inputs: (FactValue | null)[];
  price?: string | null;
  price_date?: string | null;
}

export interface Statements {
  period: "annual" | "quarterly";
  taxonomy: string | null;
  template: "industrial" | "financial";
  currency: string | null;
  period_ends: string[];
  lines: StatementLine[];
  ratios: Ratio[];
  entity: string | null;
  facts_url: string;
}

export interface Filing {
  form: string;
  filing_date: string;
  report_date: string | null;
  accession: string;
  description: string;
  items: string[];
  document_url: string | null;
  index_url: string;
  event?: string;
  certainty?: "confirmed" | "estimated";
}

function useResearch<T>(kind: string, symbol: string, params: Record<string, string> = {}, enabled = true) {
  return useQuery({
    queryKey: ["research", kind, symbol, params],
    queryFn: ({ signal }) => api.get<ResearchEnvelope<T>>(`/api/research/${kind}`, { symbol, ...params }, signal),
    enabled,
    staleTime: 30 * 60_000, // the server caches SEC data; tab switches reuse this result
    placeholderData: keepPreviousData,
  });
}

export const useFinancials = (symbol: string, period: "annual" | "quarterly", enabled = true) =>
  useResearch<Statements>("financials", symbol, { period }, enabled);
export const useFilings = (symbol: string, enabled = true) => useResearch<Filing[]>("filings", symbol, {}, enabled);
export const useResearchEvents = (symbol: string, enabled = true) => useResearch<Filing[]>("events", symbol, {}, enabled);
