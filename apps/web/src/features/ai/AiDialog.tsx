import { AlertTriangle, ExternalLink, Sparkles, Trash, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useDialogs } from "@/app/dialogs";
import { Button, IconButton } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Textarea } from "@/components/ui/Form";
import { Pill } from "@/components/ui/Badges";
import { Segmented } from "@/components/ui/Segmented";
import { ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { errorMessage } from "@/lib/api/client";
import { formatInstant, formatRelative, formatSessionDate } from "@/lib/format";
import { useQueryClient } from "@tanstack/react-query";
import { cn } from "@/lib/cn";
import { usePrefs, useSession } from "@/features/settings/api";
import { SymbolPicker } from "@/features/search/SymbolPicker";
import { useAiAnswer, useAiAnswers, useAiMutations, useAiStatus, type AiAnswer, type AiKind, type AiSource } from "./api";

const TASKS: { value: AiKind; label: string; hint: string }[] = [
  { value: "results", label: "Latest results", hint: "Summarise the latest reported results from the filings and statements." },
  { value: "catalysts", label: "Catalysts", hint: "Possible catalysts and risks visible in the evidence, each marked confirmed, scheduled or possible." },
  { value: "compare", label: "Compare", hint: "Side by side with one or two other listings, using each company's latest fiscal year." },
  { value: "ask", label: "Ask", hint: "Your own question, answered only from the evidence MarketDesk retrieves." },
];
const KIND_LABEL = { fact: "Fact", calculation: "Calculation", interpretation: "Interpretation" } as const;
const KIND_TONE = { fact: "info", calculation: "neutral", interpretation: "accent" } as const;

function SourceDetail({ s, tz }: { s: AiSource; tz?: string }) {
  return (
    <li id={`src-${s.id}`} className="rounded-[var(--radius-control)] border border-line-subtle px-3 py-2 text-xs">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="num font-semibold text-fg">{s.id}</span>
        <span className="text-fg-2">{s.title}</span>
      </div>
      <p className="mt-0.5 text-fg-3">
        {s.as_of ? `As of ${s.as_of.length > 10 ? formatInstant(s.as_of, tz) : formatSessionDate(s.as_of)}` : "No as-of date"} · fetched {formatInstant(s.fetched_at, tz)}
        {s.status ? ` · ${s.status}` : ""}
        {s.url && (
          <>
            {" · "}
            <a className="inline-flex items-center gap-0.5 text-accent-text hover:underline" href={s.url} target="_blank" rel="noopener noreferrer">
              source <ExternalLink className="size-3" aria-hidden />
            </a>
          </>
        )}
      </p>
    </li>
  );
}

function AnswerView({ a, providerLabel }: { a: AiAnswer; providerLabel: string }) {
  const { data: prefs } = usePrefs();
  const tz = prefs?.display_timezone;
  const [showSources, setShowSources] = useState(false);
  const o = a.output;
  if (a.status === "running") {
    return (
      <div className="space-y-2" aria-live="polite">
        <p className="text-[13px] font-medium text-fg">Working…</p>
        <ol className="space-y-1 text-xs text-fg-2">
          {a.steps.map((s, i) => <li key={i}>{s.text}</li>)}
        </ol>
      </div>
    );
  }
  if (a.status === "failed" || a.status === "refused") {
    return <InlineNotice tone={a.status === "refused" ? "warn" : "neg"}><span role="alert">{a.error}</span></InlineNotice>;
  }
  if (!o) return null;
  return (
    <article className="space-y-4" aria-label="AI answer">
      <div>
        <p className="text-xs font-medium text-accent-text">Model output · {a.model} via {providerLabel} · interpretation of the sources listed · not investment advice</p>
        <h3 className="mt-1 text-[15px] font-semibold text-fg">{o.headline}</h3>
      </div>
      {a.flags.length > 0 && (
        <InlineNotice tone="warn">
          {a.flags.length} automated check{a.flags.length > 1 ? "s" : ""} flagged points below (marked <AlertTriangle className="inline size-3.5" aria-label="flagged" />). Treat those points as unsupported until you verify them.
        </InlineNotice>
      )}
      {o.sections.map((sec, si) => (
        <section key={si}>
          <h4 className="text-xs font-semibold tracking-wide text-fg-3 uppercase">{sec.title}</h4>
          <ul className="mt-1.5 space-y-2">
            {sec.points.map((p, pi) => (
              <li key={pi} className={cn("text-[13px] leading-5", p.checks.length ? "text-fg-2" : "text-fg")}>
                <span className="mr-1.5 inline-flex gap-1 align-middle">
                  <Pill tone={KIND_TONE[p.kind]} className="py-0 text-[11px]">{KIND_LABEL[p.kind]}</Pill>
                  {p.certainty && <Pill className="py-0 text-[11px]">{p.certainty}</Pill>}
                </span>
                {p.text}{" "}
                {p.sources.map((sid) => (
                  <a key={sid} href={`#src-${sid}`} onClick={() => setShowSources(true)} className="num mr-1 text-xs text-accent-text hover:underline" aria-label={`Source ${sid}`}>
                    [{sid}]
                  </a>
                ))}
                {p.checks.length > 0 && (
                  <span className="mt-0.5 flex items-center gap-1 text-xs text-warn">
                    <AlertTriangle className="size-3.5 shrink-0" aria-hidden /> {p.checks.join("; ")}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
      {(o.uncertainties.length > 0 || o.gaps.length > 0) && (
        <div className="grid gap-3 sm:grid-cols-2">
          {o.uncertainties.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold tracking-wide text-fg-3 uppercase">Uncertainties</h4>
              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[13px] text-fg-2">{o.uncertainties.map((u, i) => <li key={i}>{u}</li>)}</ul>
            </div>
          )}
          {o.gaps.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold tracking-wide text-fg-3 uppercase">Not in the evidence</h4>
              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[13px] text-fg-2">{o.gaps.map((g, i) => <li key={i}>{g}</li>)}</ul>
            </div>
          )}
        </div>
      )}
      <div>
        <button type="button" aria-expanded={showSources} className="text-xs text-accent-text hover:underline" onClick={() => setShowSources((x) => !x)}>
          {showSources ? "Hide" : "Show"} the {a.sources.length} sources MarketDesk retrieved
        </button>
        {showSources && <ul className="mt-2 space-y-1.5">{a.sources.map((s) => <SourceDetail key={s.id} s={s} tz={tz} />)}</ul>}
      </div>
      <p className="text-xs leading-4 text-fg-3">
        {a.status === "reused" ? `Reused answer #${a.reused_from} (same request, unchanged evidence; no new cost). ` : ""}
        Generated {formatInstant(a.finished_at ?? a.created_at, tz)} · data cutoff {formatInstant(a.data_cutoff, tz)}
        {a.usage ? ` · ${a.usage.input_tokens.toLocaleString()} input / ${a.usage.output_tokens.toLocaleString()} output tokens · ${a.usage.tool_calls} lookup(s)` : ""}
        {a.cost_usd !== null && Number(a.cost_usd) > 0 ? ` · cost $${Number(a.cost_usd).toFixed(4)}` : ""}. Figures come from the sources; the model wrote the wording and interpretation.
      </p>
    </article>
  );
}

export function AiDialog() {
  const { state, close } = useDialogs();
  const isOpen = state.kind === "ai";
  const symbol = state.kind === "ai" ? state.symbol : "";
  const prefill = state.kind === "ai" ? state.question : undefined;
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
    }
  }, [isOpen, symbol, prefill]);
  const st = status.data;
  const readOnly = Boolean(session?.read_only);
  const task = TASKS.find((t) => t.value === kind)!;
  const canRun = st?.enabled && !readOnly && !(kind === "ask" && !question.trim()) && !(kind === "compare" && peers.length === 0);
  const run = async () => {
    setError(null);
    try {
      const a = await m.ask.mutateAsync({ kind, symbols: kind === "compare" ? [symbol, ...peers] : [symbol], question: kind === "ask" ? question : "" });
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
      description={`MarketDesk retrieves and computes the evidence; ${st ? `${st.model} (${st.provider_label})` : "the model"} writes a cited answer from it. Every point is checked against the sources, and figures never come from the model.`}
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
            <Segmented<AiKind> label="Research task" value={kind} onChange={setKind} options={TASKS.map((t) => ({ value: t.value, label: t.label }))} />
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
              <span className="text-xs text-fg-3">{budget} · {st.model} · {st.tools.length ? "read-only filing lookups, " : "one call, "}no web search</span>
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
