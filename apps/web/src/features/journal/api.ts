import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type JournalEntry, type JournalPage } from "@/lib/api/client";

export interface JournalFilters {
  symbol?: string;
  tag?: string;
  q?: string;
}

export function useJournal(filters: JournalFilters, limit = 100) {
  return useQuery({
    queryKey: ["journal", filters, limit],
    queryFn: () => api.get<JournalPage>("/api/journal", { ...filters, limit }),
    placeholderData: keepPreviousData,
  });
}

export interface JournalInput {
  symbol: string;
  entry_date: string;
  title: string;
  thesis: string;
  risks: string;
  invalidation: string;
  tags: string[];
  review_date: string | null;
}

export function useJournalMutations() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["journal"] });
    qc.invalidateQueries({ queryKey: ["briefing"] });
  };
  return {
    create: useMutation({ mutationFn: (body: JournalInput) => api.post<JournalEntry>("/api/journal", body), onSuccess: invalidate }),
    update: useMutation({ mutationFn: (v: { id: number; body: JournalInput }) => api.put<JournalEntry>(`/api/journal/${v.id}`, v.body), onSuccess: invalidate }),
    remove: useMutation({ mutationFn: (id: number) => api.del<null>(`/api/journal/${id}`), onSuccess: invalidate }),
  };
}
