import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type JournalCompare, type JournalDetail, type JournalEntry, type JournalPage, type JournalReview } from "@/lib/api/client";

export const DECISIONS = ["WATCH", "BUY", "ADD", "HOLD", "TRIM", "SELL", "AVOID"] as const;
export const OUTCOMES = [
  { value: "intact", label: "Thesis intact" },
  { value: "weakened", label: "Weakened" },
  { value: "invalidated", label: "Invalidated" },
  { value: "closed", label: "Closed" },
] as const;

export interface JournalFilters {
  symbol?: string;
  tag?: string;
  q?: string;
  due?: boolean;
}

export function useJournalDetail(id: number | null) {
  return useQuery({
    queryKey: ["journal", "detail", id],
    queryFn: () => api.get<JournalDetail>(`/api/journal/${id}`),
    enabled: id !== null,
  });
}

/** A stored version's evidence beside today's (fetched for comparison only). */
export function useJournalCompare(id: number | null, version: number) {
  return useQuery({
    queryKey: ["journal", "compare", id, version],
    queryFn: () => api.get<JournalCompare>(`/api/journal/${id}/compare`, { version }),
    enabled: id !== null,
  });
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
  decision: (typeof DECISIONS)[number] | null;
  conviction: number | null;
  horizon: string | null;
  change_note: string | null;
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
    review: useMutation({
      mutationFn: (v: { id: number; outcome: string; notes: string; next_review_date: string | null }) =>
        api.post<JournalReview>(`/api/journal/${v.id}/reviews`, { outcome: v.outcome, notes: v.notes, next_review_date: v.next_review_date }),
      onSuccess: invalidate,
    }),
  };
}
