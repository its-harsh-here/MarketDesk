import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useQuoteRefreshMs } from "@/features/workspace/api";
import {
  api,
  type AccountCurrency,
  type ImportPreview,
  type PortfolioOverview,
  type PortfolioSummary,
  type Transaction,
  type TransactionInput,
} from "@/lib/api/client";

export interface TransactionPage {
  items: Transaction[];
  total: number;
  limit: number;
  offset: number;
}

export function usePortfolioSummary(enabled = true, currency: AccountCurrency = "INR") {
  const refetchInterval = useQuoteRefreshMs();
  return useQuery({
    queryKey: ["portfolio", "summary", currency],
    queryFn: () => api.get<PortfolioSummary>("/api/portfolio/summary", { currency }),
    refetchInterval,
    placeholderData: keepPreviousData,
    enabled,
  });
}

/** Every account in its own currency plus a display-only conversion to INR at the current valuation rate. */
export function usePortfolioOverview(enabled = true) {
  const refetchInterval = useQuoteRefreshMs();
  return useQuery({
    queryKey: ["portfolio", "overview"],
    queryFn: () => api.get<PortfolioOverview>("/api/portfolio/overview"),
    refetchInterval,
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useTransactions(params: { symbol?: string; type?: string; offset?: number; currency?: AccountCurrency }) {
  return useQuery({
    queryKey: ["portfolio", "txns", params],
    queryFn: () => api.get<TransactionPage>("/api/portfolio/transactions", { limit: 100, ...params }),
    placeholderData: keepPreviousData,
  });
}

function useInvalidatePortfolio() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["portfolio"] });
  };
}

export function useTransactionMutations() {
  const invalidate = useInvalidatePortfolio();
  return {
    create: useMutation({ mutationFn: (body: TransactionInput) => api.post<Transaction>("/api/portfolio/transactions", body), onSuccess: invalidate }),
    update: useMutation({ mutationFn: (v: { id: number; body: TransactionInput }) => api.put<Transaction>(`/api/portfolio/transactions/${v.id}`, v.body), onSuccess: invalidate }),
    remove: useMutation({ mutationFn: (id: number) => api.del<null>(`/api/portfolio/transactions/${id}`), onSuccess: invalidate }),
    preview: useMutation({
      mutationFn: ({ file, mapping }: { file: File; mapping?: string }) => {
        const form = new FormData();
        form.append("file", file);
        const q = mapping ? `?mapping=${encodeURIComponent(mapping)}` : "";
        return api.upload<ImportPreview>(`/api/portfolio/import/preview${q}`, form);
      },
    }),
    commit: useMutation({
      mutationFn: (token: string) => api.post<{ imported: number; skipped_duplicates: number }>(`/api/portfolio/import/${encodeURIComponent(token)}/commit`),
      onSuccess: invalidate,
    }),
  };
}

export interface CsvMapping {
  id: string;
  name: string;
  builtin: boolean;
  columns: Record<string, string>;
  buy_words: string[];
  sell_words: string[];
  date_format: string;
  symbol_suffix: string;
  currency: string;
  combine_fills: boolean;
  note?: string;
}
export interface CsvMappings { mappings: CsvMapping[]; fields: string[]; required: string[]; date_formats: string[] }

export function useCsvMappings(enabled = true) {
  return useQuery({
    queryKey: ["portfolio", "csv-mappings"],
    queryFn: ({ signal }) => api.get<CsvMappings>("/api/portfolio/csv-mappings", undefined, signal),
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function useCsvMappingMutations() {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: ["portfolio", "csv-mappings"] });
  return {
    save: useMutation({ mutationFn: (body: Omit<CsvMapping, "id" | "builtin">) => api.post<CsvMapping>("/api/portfolio/csv-mappings", body), onSuccess: refresh }),
    remove: useMutation({ mutationFn: (id: string) => api.del<null>(`/api/portfolio/csv-mappings/${encodeURIComponent(id)}`), onSuccess: refresh }),
  };
}
