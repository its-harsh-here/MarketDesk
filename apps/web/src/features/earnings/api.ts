import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export interface NextDate {
  date: string;
  window: [string, string] | null;
  basis: "estimated" | "deadline";
  explanation: string;
  period_end?: string;
  period?: string;
}

export interface Calendar {
  symbol: string;
  name: string | null;
  past: { date: string; kind: string; url: string | null }[];
  next: NextDate | null;
  source: string | null;
  note: string | null;
}

export interface Fv {
  value: string;
  end: string;
  start?: string | null;
  form?: string;
  filed?: string;
  accession?: string;
  restated?: boolean;
  source_url?: string | null;
  prior?: { value: string; filed: string; accession: string; form: string }[];
}

export interface ChangeRow {
  mode: "qoq" | "yoy" | "fy";
  latest_end: string;
  prior_end: string | null;
  key: string;
  label: string;
  latest: Fv | null;
  prior: Fv | null;
  change_pct: string | null;
  latest_pct?: string | null;
  prior_pct?: string | null;
  change_pp?: string | null;
}

export interface EarningsSummary {
  symbol: string;
  calendar: Calendar;
  changes: { available: boolean; reason?: string; source?: string; currency?: string | null; qoq: ChangeRow[]; yoy: ChangeRow[]; fy: ChangeRow[]; note?: string };
}

export interface FilingChanges {
  available: boolean;
  reason?: string;
  section?: string;
  new?: { form: string; filing_date: string; report_date: string | null; url: string };
  old?: { form: string; filing_date: string; report_date: string | null; url: string };
  counts?: { old: number; new: number; added: number; removed: number; reworded: number };
  added?: string[];
  removed?: string[];
  reworded?: { before: string; after: string; similarity: number }[];
  method?: string;
}

export interface Guidance {
  available: boolean;
  reason?: string;
  timeline?: { filing_date: string; url: string | null; quotes: string[]; error?: string }[];
  method?: string;
}

const enc = encodeURIComponent;

export function useEarnings(symbol: string, enabled = true) {
  return useQuery({ queryKey: ["earnings", symbol], queryFn: () => api.get<EarningsSummary>(`/api/earnings/${enc(symbol)}`), staleTime: 5 * 60_000, enabled });
}

export function useFilingChanges(symbol: string, form: string, enabled: boolean) {
  return useQuery({
    queryKey: ["earnings", symbol, "changes", form],
    queryFn: () => api.get<FilingChanges>(`/api/earnings/${enc(symbol)}/filing-changes`, { form }),
    enabled,
    staleTime: 30 * 60_000,
    retry: false,
  });
}

export function useGuidance(symbol: string, enabled: boolean) {
  return useQuery({ queryKey: ["earnings", symbol, "guidance"], queryFn: () => api.get<Guidance>(`/api/earnings/${enc(symbol)}/guidance`), enabled, staleTime: 30 * 60_000, retry: false });
}

export function useEarningsCalendar() {
  return useQuery({
    queryKey: ["earnings", "calendar"],
    queryFn: () => api.get<{ rows: Calendar[]; truncated: number; universe: string; note: string }>("/api/earnings/calendar"),
    staleTime: 10 * 60_000,
  });
}
