import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export type AiKind = "ask" | "results" | "catalysts" | "compare";
export type AiStatus = {
  enabled: boolean;
  reason: string | null;
  model: string;
  tools: string[];
  web_search: boolean;
  budget: {
    day: string;
    limit_usd: string;
    spent_usd: string;
    reserved_usd: string;
    requests_used: number;
    requests_limit: number;
    max_output_tokens: number;
    max_tool_calls: number;
  };
};
export type AiPoint = {
  text: string;
  kind: "fact" | "calculation" | "interpretation";
  sources: string[];
  certainty: "confirmed" | "scheduled" | "possible" | null;
  checks: string[];
};
export type AiSource = {
  id: string;
  kind: string;
  symbol: string | null;
  title: string;
  url: string | null;
  as_of: string | null;
  fetched_at: string;
  status: string | null;
  data: unknown;
};
export type AiAnswerSummary = {
  id: number;
  created_at: string;
  finished_at: string | null;
  kind: AiKind;
  symbols: string[];
  question: string;
  status: "running" | "done" | "reused" | "refused" | "failed";
  model: string | null;
  headline: string | null;
  flag_count: number;
  cost_usd: string | null;
  data_cutoff: string | null;
  reused_from: number | null;
  error: string | null;
};
export type AiAnswer = AiAnswerSummary & {
  steps: { at: string; text: string }[];
  output: { headline: string; sections: { title: string; points: AiPoint[] }[]; uncertainties: string[]; gaps: string[] } | null;
  sources: AiSource[];
  flags: { section: number; point: number; issue: string }[];
  usage: { input_tokens: number; output_tokens: number; cached_tokens: number; reasoning_tokens: number; calls: number; tool_calls: number; cost_usd: number; cost_source: string } | null;
};

export function useAiStatus(enabled = true) {
  return useQuery({ queryKey: ["ai", "status"], queryFn: () => api.get<AiStatus>("/api/ai/status"), enabled, staleTime: 15_000 });
}

export function useAiAnswers(symbol: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["ai", "answers", symbol],
    queryFn: () => api.get<AiAnswerSummary[]>("/api/ai/answers", { symbol, limit: 10 }),
    enabled,
  });
}

/** One answer; polls while it is running (the server works in the background). */
export function useAiAnswer(id: number | null) {
  return useQuery({
    queryKey: ["ai", "answer", id],
    queryFn: () => api.get<AiAnswer>(`/api/ai/answers/${id}`),
    enabled: id !== null,
    refetchInterval: (q) => (q.state.data?.status === "running" ? 1200 : false),
  });
}

export function useAiMutations() {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: ["ai"] });
  return {
    ask: useMutation({
      mutationFn: (body: { kind: AiKind; symbols: string[]; question: string }) => api.post<AiAnswerSummary>("/api/ai/answers", body),
      onSuccess: refresh,
    }),
    remove: useMutation({ mutationFn: (id: number) => api.del<null>(`/api/ai/answers/${id}`), onSuccess: refresh }),
  };
}
