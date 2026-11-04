import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Alert, type InboxCounts, type InboxItem, type StoredBriefing } from "@/lib/api/client";
import { useStatus } from "@/features/settings/api";

/**
 * New alert events can only appear when the worker samples prices, so poll at the worker's interval
 * (bounded to 10–60 s) instead of a fixed short interval. Polling pauses while the tab is hidden.
 */
export function alertPollMs(workerPollSeconds: number | undefined): number {
  const seconds = workerPollSeconds && workerPollSeconds > 0 ? workerPollSeconds : 60;
  return Math.min(60, Math.max(10, seconds)) * 1000;
}

function useAlertPollMs() {
  const { data } = useStatus();
  return alertPollMs(data?.worker?.poll_seconds);
}

export function useAlerts() {
  const refetchInterval = useAlertPollMs();
  return useQuery({ queryKey: ["alerts"], queryFn: () => api.get<Alert[]>("/api/alerts"), refetchInterval });
}

export type RuleName = "PRICE" | "CROSS" | "VOLUME" | "VOLATILITY" | "FILING" | "EARNINGS";

export interface AlertInput {
  symbol: string;
  rule: RuleName;
  direction: "ABOVE" | "BELOW";
  target_price?: string | null;
  params?: { lookback?: number; forms?: string[]; days_before?: number } | null;
  cooldown_minutes?: number | null;
  quiet_start?: string | null;
  quiet_end?: string | null;
  note?: string | null;
}

export type AlertPatch = Partial<Omit<AlertInput, "symbol" | "rule" | "params">> & { active?: boolean };

export interface InboxFilters {
  type?: "alert" | "briefing";
  market?: "IN" | "US";
  unread?: boolean;
}

export function useInbox(filters: InboxFilters = {}, limit = 50) {
  const refetchInterval = useAlertPollMs();
  return useQuery({
    queryKey: ["inbox", filters, limit],
    queryFn: () => api.get<InboxItem[]>("/api/inbox", { ...filters, limit }),
    refetchInterval,
    placeholderData: (prev) => prev,
  });
}

export function useInboxCounts() {
  const refetchInterval = useAlertPollMs();
  return useQuery({ queryKey: ["inbox", "counts"], queryFn: () => api.get<InboxCounts>("/api/inbox/counts"), refetchInterval });
}

export function useAlertMutations() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["alerts"] });
    qc.invalidateQueries({ queryKey: ["alert-events"] });
    qc.invalidateQueries({ queryKey: ["inbox"] });
    qc.invalidateQueries({ queryKey: ["briefing"] });
  };
  return {
    create: useMutation({ mutationFn: (body: AlertInput) => api.post<Alert>("/api/alerts", body), onSuccess: invalidate }),
    update: useMutation({
      mutationFn: (v: { id: number; patch: AlertPatch }) => api.patch<Alert>(`/api/alerts/${v.id}`, v.patch),
      onSuccess: invalidate,
    }),
    rearm: useMutation({ mutationFn: (id: number) => api.post<Alert>(`/api/alerts/${id}/rearm`), onSuccess: invalidate }),
    remove: useMutation({ mutationFn: (id: number) => api.del<null>(`/api/alerts/${id}`), onSuccess: invalidate }),
    /** Mark one inbox item, or (no argument) everything delivered, as read. */
    read: useMutation({
      mutationFn: (item?: { type: InboxItem["type"]; id: number }) => api.post<{ updated: number }>("/api/inbox/read", item ?? {}),
      onSuccess: invalidate,
    }),
  };
}

/** Fixture harness only: write the end-of-session briefing for the current sample session. */
export function useSampleBriefing() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<StoredBriefing>("/api/fixture/briefing"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["inbox"] }),
  });
}
