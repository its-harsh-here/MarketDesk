import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type ImportPreview, type PortfolioSummary, type Transaction, type TransactionInput } from "@/lib/api/client";

export interface TransactionPage {
  items: Transaction[];
  total: number;
  limit: number;
  offset: number;
}

export function usePortfolioSummary(enabled = true) {
  return useQuery({
    queryKey: ["portfolio", "summary"],
    queryFn: () => api.get<PortfolioSummary>("/api/portfolio/summary"),
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useTransactions(params: { symbol?: string; type?: string; offset?: number }) {
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
      mutationFn: (file: File) => {
        const form = new FormData();
        form.append("file", file);
        return api.upload<ImportPreview>("/api/portfolio/import/preview", form);
      },
    }),
    commit: useMutation({
      mutationFn: (token: string) => api.post<{ imported: number; skipped_duplicates: number }>(`/api/portfolio/import/${encodeURIComponent(token)}/commit`),
      onSuccess: invalidate,
    }),
    sample: useMutation({ mutationFn: () => api.post<{ created: number }>("/api/workspace/sample-portfolio"), onSuccess: invalidate }),
  };
}
