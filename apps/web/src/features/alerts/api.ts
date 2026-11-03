import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Alert, type AlertEvent } from "@/lib/api/client";

export function useAlerts() {
  return useQuery({ queryKey: ["alerts"], queryFn: () => api.get<Alert[]>("/api/alerts"), refetchInterval: 10_000 });
}

export function useAlertEvents(unread = false) {
  return useQuery({
    queryKey: ["alert-events", unread],
    queryFn: () => api.get<AlertEvent[]>("/api/alert-events", { unread, limit: 50 }),
    refetchInterval: 10_000,
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
