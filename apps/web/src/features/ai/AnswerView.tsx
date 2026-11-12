import { AlertTriangle, ExternalLink } from "lucide-react";
import { useState } from "react";
import { Pill } from "@/components/ui/Badges";
import { InlineNotice } from "@/components/ui/States";
import { formatInstant, formatSessionDate } from "@/lib/format";
import { cn } from "@/lib/cn";
import { usePrefs } from "@/features/settings/api";
import type { AiAnswer, AiSource } from "./api";

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

export function AnswerView({ a, providerLabel }: { a: AiAnswer; providerLabel: string }) {
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
        <p className="text-xs font-medium text-accent-text">Model output · {providerLabel} · interpretation of the sources listed · not investment advice</p>
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

