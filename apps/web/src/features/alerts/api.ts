import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Alert, type AlertEvent } from "@/lib/api/client";
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

export function useAlertEvents(unread = false) {
  const refetchInterval = useAlertPollMs();
  return useQuery({
    queryKey: ["alert-events", unread],
    queryFn: () => api.get<AlertEvent[]>("/api/alert-events", { unread, limit: 50 }),
    refetchInterval,
  });
}

export interface AlertInput {
  symbol: string;
  direction: "ABOVE" | "BELOW";
  target_price: string;
  note?: string | null;
}

export function useAlertMutations() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["alerts"] });
    qc.invalidateQueries({ queryKey: ["alert-events"] });
    qc.invalidateQueries({ queryKey: ["briefing"] });
  };
  return {
    create: useMutation({ mutationFn: (body: AlertInput) => api.post<Alert>("/api/alerts", body), onSuccess: invalidate }),
    update: useMutation({
      mutationFn: (v: { id: number; patch: Partial<AlertInput> & { active?: boolean } }) => api.patch<Alert>(`/api/alerts/${v.id}`, v.patch),
      onSuccess: invalidate,
    }),
    rearm: useMutation({ mutationFn: (id: number) => api.post<Alert>(`/api/alerts/${id}/rearm`), onSuccess: invalidate }),
    remove: useMutation({ mutationFn: (id: number) => api.del<null>(`/api/alerts/${id}`), onSuccess: invalidate }),
    readAll: useMutation({ mutationFn: () => api.post<{ updated: number }>("/api/alert-events/read"), onSuccess: invalidate }),
  };
}
