import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { InputMeta, MetricDef } from "@/features/screener/api";

export type CoverageStatus = "available" | "estimated" | "missing" | "not_available" | "not_configured" | "planned" | "licensed";

export interface Description {
  symbol: string;
  identity: {
    symbol: string;
    name: string | null;
    exchange: string | null;
    mic: string | null;
    country: string | null;
    currency: string | null;
    kind: string | null;
    timezone: string | null;
    identity_source: string | null;
    identity_verified_at: string | null;
    identifiers: { scheme: string; value: string; source: string | null; verified_at: string | null }[];
    cik: number | null;
    sec: { name: string | null; sic: string | null; industry: string | null; tickers: string[]; exchanges: string[]; state_of_incorporation: string | null; fiscal_year_end: string | null; fetched_at: string | null } | null;
    related_listings: { symbol: string; exchange: string | null; via: string }[];
    sector: string | null;
    industry: string | null;
    last_fiscal_year_end: string | null;
    most_recent_quarter: string | null;
    classification_source: string | null;
    fetched_at: string | null;
  };
  summary:
    | { status: "available"; kind: "filing" | "provider"; text: string; source: string; url: string | null; as_of: string | null; period?: string | null; fetched_at: string | null }
    | { status: "missing" | "unavailable"; reason: string; url?: string | null };
  key_stats: {
    computed_at: string | null;
    provider: string;
    inputs: Record<string, InputMeta> | null;
    stats: (MetricDef & { value: string | null; as_of: string | null; why: string | null })[];
  };
  coverage: { domain: string; code: string | null; status: CoverageStatus; source: string | null; note: string | null; tab: string | null }[];
  metric_groups: string[];
}

export function useDescription(symbol: string) {
  return useQuery({
    queryKey: ["terminal", "description", symbol],
    queryFn: () => api.get<Description>("/api/terminal/description", { symbol }),
    staleTime: 5 * 60_000,
  });
}
