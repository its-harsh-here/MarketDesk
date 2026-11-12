import { Sparkles, Trash, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useDialogs } from "@/app/dialogs";
import { Button, IconButton } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Textarea } from "@/components/ui/Form";
import { Pill } from "@/components/ui/Badges";
import { Segmented } from "@/components/ui/Segmented";
import { ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { errorMessage } from "@/lib/api/client";
import { formatRelative } from "@/lib/format";
import { useQueryClient } from "@tanstack/react-query";
import { cn } from "@/lib/cn";
import { useSession } from "@/features/settings/api";
import { SymbolPicker } from "@/features/search/SymbolPicker";
import { useAiAnswer, useAiAnswers, useAiMutations, useAiStatus, type AiKind } from "./api";
import { AnswerView } from "./AnswerView";

const TASKS: { value: AiKind; label: string; hint: string }[] = [
  { value: "results", label: "Latest results", hint: "Summarise the latest reported results from the filings and statements." },
  { value: "catalysts", label: "Catalysts", hint: "Possible catalysts and risks visible in the evidence, each marked confirmed, scheduled or possible." },
  { value: "compare", label: "Compare", hint: "Side by side with one or two other listings, using each company's latest fiscal year." },
  { value: "brief", label: "Bull · base · bear", hint: "Three cases, each with its explicit assumptions and the cited facts for and against them. No price targets." },
  { value: "ask", label: "Ask", hint: "Your own question, answered only from the evidence MarketDesk retrieves." },
  { value: "challenge", label: "Challenge my thesis", hint: "The strongest evidence-based case against your journal thesis: where the evidence disagrees, the assumptions it depends on, and what would show it wrong. Your note is examined, never treated as instructions." },
];
export function AiDialog() {
  const { state, close } = useDialogs();
  const isOpen = state.kind === "ai";
  const symbol = state.kind === "ai" ? state.symbol : "";
  const prefill = state.kind === "ai" ? state.question : undefined;
  const presetTask = state.kind === "ai" ? state.task : undefined;
  const journalId = state.kind === "ai" ? state.journalId : undefined;
  const { data: session } = useSession();
  const status = useAiStatus(isOpen);
  const previous = useAiAnswers(symbol, isOpen);
  const m = useAiMutations();
  const [kind, setKind] = useState<AiKind>("results");
  const [question, setQuestion] = useState("");
  const [peers, setPeers] = useState<string[]>([]);
  const [peerInput, setPeerInput] = useState("");
  const [current, setCurrent] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const answer = useAiAnswer(current);
  const qc = useQueryClient();
  const finished = answer.data && answer.data.status !== "running" ? answer.data.id : null;
  useEffect(() => {
    // the job finished in the background: refresh today's budget and the saved-answer list
    if (finished !== null) qc.invalidateQueries({ predicate: (q) => q.queryKey[0] === "ai" && q.queryKey[1] !== "answer" });
  }, [finished, qc]);
  useEffect(() => {
    if (isOpen) {
      setCurrent(null);
      setError(null);
      setPeers([]);
      setQuestion(prefill ?? "");
      if (prefill) setKind("ask");
      else if (presetTask) setKind(presetTask);
      else setKind((k) => (k === "challenge" ? "results" : k));
    }
  }, [isOpen, symbol, prefill, presetTask]);
  const st = status.data;
  const readOnly = Boolean(session?.read_only);
  const task = TASKS.find((t) => t.value === kind)!;
  const canRun = st?.enabled && !readOnly && !(kind === "ask" && !question.trim()) && !(kind === "compare" && peers.length === 0);
  const run = async () => {
    setError(null);
    try {
      const a = await m.ask.mutateAsync({ kind, symbols: kind === "compare" ? [symbol, ...peers] : [symbol], question: kind === "ask" ? question : "", ...(kind === "challenge" && journalId ? { journal_id: journalId } : {}) });
      setCurrent(a.id);
    } catch (err) {
      setError(errorMessage(err));
    }
  };
  const budget = useMemo(() => {
    if (!st) return "";
    const b = st.budget;
    const spend = b.tokens_limit
      ? `${b.tokens_used.toLocaleString()} of ${b.tokens_limit.toLocaleString()} tokens`
      : `$${Number(b.spent_usd).toFixed(3)} spent${Number(b.reserved_usd) ? `, $${Number(b.reserved_usd).toFixed(3)} in progress` : ""} of $${Number(b.limit_usd).toFixed(2)}`;
    return `Today: ${spend} · ${b.requests_used} of ${b.requests_limit} answers`;
  }, [st]);

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(o) => !o && close()}
      title={`Research ${symbol}`}
      description={`MarketDesk retrieves and computes the evidence; the AI analyst writes a cited answer from it. Every point is checked against the sources, and figures never come from the model.`}
      size="xl"
      footer={<Button variant="ghost" onClick={close}>Close</Button>}
    >
      {status.isLoading ? (
        <SkeletonRows rows={3} />
      ) : status.isError ? (
        <ErrorState message={errorMessage(status.error)} onRetry={() => status.refetch()} />
      ) : !st?.enabled ? (
        <InlineNotice tone="info">AI research is unavailable: {st?.reason} Everything else in MarketDesk works without it.</InlineNotice>
      ) : (
        <div className="space-y-4">
          <div className="space-y-3">
            <Segmented<AiKind> label="Research task" value={kind} onChange={setKind} options={TASKS.filter((t) => t.value !== "challenge" || journalId).map((t) => ({ value: t.value, label: t.label }))} />
            <p className="text-xs text-fg-3">{task.hint}</p>
            {kind === "ask" && (
              <Field label="Your question" hint={`${question.length}/500`}>
                {({ id, describedBy }) => <Textarea id={id} rows={2} maxLength={500} aria-describedby={describedBy} value={question} onChange={(e) => setQuestion(e.target.value)} />}
              </Field>
            )}
            {kind === "compare" && (
              <div className="space-y-2">
                <Field label="Compare with (up to two)">
                  {({ id }) => (
                    <SymbolPicker
                      id={id}
                      value={peerInput}
                      onChange={(s) => {
                        if (s && s !== symbol && !peers.includes(s) && peers.length < 2) setPeers([...peers, s]);
                        setPeerInput("");
                      }}
                    />
                  )}
                </Field>
                {peers.length > 0 && (
                  <ul className="flex flex-wrap gap-1.5" aria-label="Compared listings">
                    {peers.map((p) => (
                      <li key={p}>
                        <Pill className="gap-1">
                          <span className="num">{p}</span>
                          <button type="button" aria-label={`Remove ${p}`} onClick={() => setPeers(peers.filter((x) => x !== p))}><X className="size-3" aria-hidden /></button>
                        </Pill>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            {error && <InlineNotice tone="neg"><span role="alert">{error}</span></InlineNotice>}
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs text-fg-3">{budget} · {st.tools.length ? "read-only filing lookups, " : "one call, "}no web search</span>
              <Button variant="primary" icon={<Sparkles className="size-4" aria-hidden />} disabled={!canRun} loading={m.ask.isPending || answer.data?.status === "running"} onClick={run} title={readOnly ? "Read-only demo" : undefined}>
                Run
              </Button>
            </div>
          </div>
          {current !== null && (
            <div className="border-t border-line-subtle pt-4">
              {answer.isLoading ? <SkeletonRows rows={3} /> : answer.isError ? <ErrorState message={errorMessage(answer.error)} onRetry={() => answer.refetch()} /> : answer.data && <AnswerView a={answer.data} providerLabel={st.provider_label} />}
            </div>
          )}
          {previous.data && previous.data.length > 0 && (
            <div className="border-t border-line-subtle pt-3">
              <h4 className="text-xs font-semibold tracking-wide text-fg-3 uppercase">Saved answers for {symbol}</h4>
              <ul className="mt-1.5 divide-y divide-line-subtle">
                {previous.data.map((p) => (
                  <li key={p.id} className="flex items-center gap-2 py-1.5 text-[13px]">
                    <button type="button" className={cn("min-w-0 flex-1 truncate text-left hover:text-accent-text", p.id === current ? "text-accent-text" : "text-fg-2")} onClick={() => setCurrent(p.id)}>
                      {TASKS.find((t) => t.value === p.kind)?.label} · {p.headline ?? p.error ?? p.status}
                    </button>
                    <span className="shrink-0 text-xs text-fg-3">{formatRelative(p.created_at)}{p.flag_count ? ` · ${p.flag_count} flagged` : ""}</span>
                    {!readOnly && p.status !== "running" && (
                      <IconButton size="sm" label={`Delete saved answer ${p.id}`} onClick={() => m.remove.mutate(p.id, { onSuccess: () => p.id === current && setCurrent(null) })}>
                        <Trash className="size-3.5" aria-hidden />
                      </IconButton>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Dialog>
  );
}
