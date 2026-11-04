import { Bell, ExternalLink, Sparkles } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { useDialogs } from "@/app/dialogs";
import { Pill } from "@/components/ui/Badges";
import { Button } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/States";
import { errorMessage } from "@/lib/api/client";
import { DASH, formatLargeMoney, formatPercent, formatSessionDate } from "@/lib/format";
import { cn } from "@/lib/cn";
import { useSession } from "@/features/settings/api";
import { useEarnings, useEarningsCalendar, useFilingChanges, useGuidance, type Calendar, type ChangeRow } from "./api";

export function NextDateText({ c }: { c: Calendar }) {
  if (!c.next) return <span className="text-fg-3">{c.note ?? DASH}</span>;
  return (
    <span>
      <span className="num font-medium">{formatSessionDate(c.next.date)}</span>{" "}
      <Pill tone={c.next.basis === "deadline" ? "warn" : "info"} className="py-0">{c.next.basis === "deadline" ? "deadline" : "estimate"}</Pill>
    </span>
  );
}

export function EarningsTab({ symbol }: { symbol: string }) {
  const q = useEarnings(symbol);
  const { open } = useDialogs();
  const { data: session } = useSession();
  const d = q.data;
  return (
    <>
      <Panel title="Results calendar" titleId="cal-title" className="lg:col-span-4 lg:self-start" meta={d?.calendar.source ?? undefined}>
        {q.isLoading ? (
          <SkeletonRows rows={4} />
        ) : q.isError ? (
          <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
        ) : d ? (
          <div className="space-y-3 text-[13px]">
            <div>
              <p className="text-xs text-fg-3">Next results</p>
              <p className="mt-0.5 text-base"><NextDateText c={d.calendar} /></p>
              {d.calendar.next?.window && (
                <p className="num text-xs text-fg-2">Window {formatSessionDate(d.calendar.next.window[0])} – {formatSessionDate(d.calendar.next.window[1])}</p>
              )}
              {d.calendar.next?.period_end && <p className="text-xs text-fg-2">For the {d.calendar.next.period} ending {formatSessionDate(d.calendar.next.period_end)}</p>}
              {d.calendar.next && <p className="mt-1 text-xs leading-4 text-fg-3">{d.calendar.next.explanation}</p>}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" icon={<Bell className="size-4" aria-hidden />} disabled={session?.read_only || !d.calendar.next}
                title={!d.calendar.next ? "No next date to remind about" : undefined}
                onClick={() => open({ kind: "alert", symbol })}>Remind me</Button>
              <Button size="sm" variant="ghost" icon={<Sparkles className="size-4" aria-hidden />} onClick={() => open({ kind: "ai", symbol, task: "brief" })}>
                Bull · base · bear brief
              </Button>
            </div>
            <p className="text-xs text-fg-3">“Remind me” opens a new alert: choose “Results reminder” and the number of days.</p>
            {d.calendar.past.length > 0 && (
              <div>
                <p className="text-xs text-fg-3">Reported</p>
                <ul className="mt-1 space-y-1">
                  {d.calendar.past.map((p) => (
                    <li key={p.date + p.kind} className="flex items-center justify-between gap-2">
                      <span className="num">{formatSessionDate(p.date)}</span>
                      {p.url ? (
                        <a href={p.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-fg-2 hover:text-accent-text">
                          {p.kind} <ExternalLink className="size-3" aria-hidden />
                        </a>
                      ) : (
                        <span className="text-xs text-fg-3">{p.kind}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <p className="text-xs leading-4 text-fg-3">No consensus estimates are used, so no “surprise” is computed: changes below are against the company's own earlier periods.</p>
          </div>
        ) : null}
      </Panel>
      <ChangesPanel data={d?.changes} loading={q.isLoading} />
      <FilingChangesPanel symbol={symbol} />
      <GuidancePanel symbol={symbol} />
    </>
  );
}

function ChangesPanel({ data, loading }: { data?: NonNullable<ReturnType<typeof useEarnings>["data"]>["changes"]; loading: boolean }) {
  const [mode, setMode] = useState<"yoy" | "qoq" | "fy">("yoy");
  const rows: ChangeRow[] = data ? data[mode] : [];
  const avail = data ? { qoq: data.qoq.length > 0, yoy: data.yoy.length > 0, fy: data.fy.length > 0 } : { qoq: false, yoy: false, fy: false };
  const effective = avail[mode] ? mode : avail.fy ? "fy" : mode;
  const shown = data ? data[effective] : rows;
  const ccy = data?.currency ?? "";
  const first = shown[0];
  return (
    <Panel title="Reported changes" titleId="chg-title" className="lg:col-span-8" meta={data?.source} wrapHeader
      actions={
        <Segmented label="Comparison" value={effective} onChange={setMode}
          options={[
            { value: "yoy", label: "vs year ago", disabled: !avail.yoy, title: avail.yoy ? undefined : "Needs SEC quarterly data" },
            { value: "qoq", label: "vs prior quarter", disabled: !avail.qoq, title: avail.qoq ? undefined : "Needs SEC quarterly data" },
            { value: "fy", label: "Fiscal year", disabled: !avail.fy },
          ]} />
      }
    >
      {loading ? (
        <SkeletonRows rows={6} />
      ) : !data?.available ? (
        <EmptyState title="No reported figures">{data?.reason}</EmptyState>
      ) : !shown.length ? (
        <EmptyState title="Not enough periods to compare" />
      ) : (
        <div className="space-y-2">
          <div className="scrollbar-thin relative overflow-x-auto">
            <table className="w-full min-w-[520px] text-[13px]">
              <caption className="sr-only">Reported figures for {first.latest_end} compared with {first.prior_end ?? "no comparable period"}</caption>
              <thead>
                <tr className="border-b border-line-subtle text-xs text-fg-3">
                  <th scope="col" className="py-1.5 text-left font-medium">Line</th>
                  <th scope="col" className="py-1.5 text-right font-medium">{formatSessionDate(first.latest_end)}</th>
                  <th scope="col" className="py-1.5 text-right font-medium">{first.prior_end ? formatSessionDate(first.prior_end) : "No comparable period"}</th>
                  <th scope="col" className="py-1.5 text-right font-medium">Change</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.key} className="border-b border-line-subtle/60">
                    <th scope="row" className="py-1.5 text-left font-normal text-fg-2">{r.label}</th>
                    {r.latest_pct !== undefined ? (
                      <>
                        <td className="num py-1.5 text-right">{r.latest_pct ? formatPercent(r.latest_pct, { signed: false }) : DASH}</td>
                        <td className="num py-1.5 text-right">{r.prior_pct ? formatPercent(r.prior_pct, { signed: false }) : DASH}</td>
                        <td className={cn("num py-1.5 text-right", Number(r.change_pp) > 0 ? "text-pos" : Number(r.change_pp) < 0 ? "text-neg" : "")}>
                          {r.change_pp ? `${Number(r.change_pp) > 0 ? "+" : ""}${r.change_pp} pp` : DASH}
                        </td>
                      </>
                    ) : (
                      <>
                        <td className="num py-1.5 text-right"><Value v={r.latest} ccy={ccy} /></td>
                        <td className="num py-1.5 text-right"><Value v={r.prior} ccy={ccy} /></td>
                        <td className={cn("num py-1.5 text-right", Number(r.change_pct) > 0 ? "text-pos" : Number(r.change_pct) < 0 ? "text-neg" : "")}>
                          {r.change_pct ? formatPercent(r.change_pct) : DASH}
                        </td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs leading-4 text-fg-3">{data.note} R marks a value restated in a later filing; hover a value for its filing.</p>
        </div>
      )}
    </Panel>
  );
}

function Value({ v, ccy }: { v: ChangeRow["latest"]; ccy: string }) {
  if (!v) return <span className="text-fg-3">{DASH}</span>;
  const text = ccy ? formatLargeMoney(v.value, ccy) : formatLargeMoney(v.value, "");
  const title = v.accession ? `${v.form ?? ""} filed ${v.filed ?? ""} · accession ${v.accession}${v.prior?.length ? ` · earlier: ${v.prior.map((p) => `${p.value} (${p.form} ${p.filed})`).join("; ")}` : ""}` : undefined;
  const body = (
    <>
      {text}
      {v.restated && <span className="ml-1 rounded border border-warn/50 px-0.5 text-[10px] text-warn">R</span>}
    </>
  );
  return v.source_url ? <a href={v.source_url} target="_blank" rel="noopener noreferrer" title={title} className="hover:text-accent-text">{body}</a> : <span title={title}>{body}</span>;
}

function FilingChangesPanel({ symbol }: { symbol: string }) {
  const [form, setForm] = useState<"10-K" | "10-Q">("10-K");
  const [go, setGo] = useState(false);
  const q = useFilingChanges(symbol, form, go);
  const d = q.data;
  return (
    <Panel title="What changed in the risk factors" titleId="fc-title" className="lg:col-span-12" wrapHeader
      actions={
        <div className="flex items-center gap-2">
          <Segmented label="Form" value={form} onChange={(f) => setForm(f)} options={[{ value: "10-K", label: "Annual (10-K)" }, { value: "10-Q", label: "Quarterly (10-Q)" }]} />
          {!go && <Button size="sm" onClick={() => setGo(true)}>Compare latest two</Button>}
        </div>
      }
    >
      {!go ? (
        <p className="text-[13px] text-fg-2">Compares Item 1A of the latest two filings of the chosen form and quotes the paragraphs that were added, removed or reworded (US registrants; reading two filings takes a few seconds).</p>
      ) : q.isLoading ? (
        <SkeletonRows rows={5} />
      ) : q.isError ? (
        <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
      ) : !d?.available ? (
        <EmptyState title="No comparison">{d?.reason}</EmptyState>
      ) : (
        <div className="space-y-3 text-[13px]">
          <p className="text-fg-2">
            <a href={d.new!.url} target="_blank" rel="noopener noreferrer" className="hover:text-accent-text">{d.new!.form} filed {formatSessionDate(d.new!.filing_date)}</a> vs{" "}
            <a href={d.old!.url} target="_blank" rel="noopener noreferrer" className="hover:text-accent-text">{d.old!.form} filed {formatSessionDate(d.old!.filing_date)}</a>:{" "}
            <span className="num">{d.counts!.added}</span> added, <span className="num">{d.counts!.removed}</span> removed, <span className="num">{d.counts!.reworded}</span> reworded
            (of <span className="num">{d.counts!.new}</span> paragraphs now).
          </p>
          <Quotes title="Added" items={d.added ?? []} tone="pos" />
          <Quotes title="Removed" items={d.removed ?? []} tone="neg" />
          {d.reworded && d.reworded.length > 0 && (
            <details>
              <summary className="cursor-pointer text-xs font-medium text-fg-2">Reworded ({d.reworded.length})</summary>
              <ul className="mt-2 space-y-3">
                {d.reworded.map((r, i) => (
                  <li key={i} className="grid gap-2 md:grid-cols-2">
                    <blockquote className="border-l-2 border-neg/50 pl-3 text-fg-2">{r.before}</blockquote>
                    <blockquote className="border-l-2 border-pos/50 pl-3">{r.after}</blockquote>
                  </li>
                ))}
              </ul>
            </details>
          )}
          <p className="text-xs leading-4 text-fg-3">{d.method}</p>
        </div>
      )}
    </Panel>
  );
}

function Quotes({ title, items, tone }: { title: string; items: string[]; tone: "pos" | "neg" }) {
  if (!items.length) return null;
  return (
    <details open={tone === "pos"}>
      <summary className="cursor-pointer text-xs font-medium text-fg-2">{title} ({items.length})</summary>
      <ul className="mt-2 space-y-2">
        {items.map((t, i) => (
          <li key={i}><blockquote className={cn("border-l-2 pl-3", tone === "pos" ? "border-pos/50" : "border-neg/50 text-fg-2")}>{t}</blockquote></li>
        ))}
      </ul>
    </details>
  );
}

function GuidancePanel({ symbol }: { symbol: string }) {
  const [go, setGo] = useState(false);
  const q = useGuidance(symbol, go);
  const d = q.data;
  return (
    <Panel title="Guidance in results releases" titleId="gd-title" className="lg:col-span-12" actions={!go ? <Button size="sm" onClick={() => setGo(true)}>Load quotes</Button> : undefined}>
      {!go ? (
        <p className="text-[13px] text-fg-2">Quotes sentences about guidance or outlook (with a figure) from the latest results releases (US registrants), newest first.</p>
      ) : q.isLoading ? (
        <SkeletonRows rows={4} />
      ) : q.isError ? (
        <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
      ) : !d?.available ? (
        <EmptyState title="No guidance quotes">{d?.reason}</EmptyState>
      ) : (
        <div className="space-y-3 text-[13px]">
          <ol className="space-y-3">
            {d.timeline!.map((t) => (
              <li key={t.filing_date}>
                <p className="text-xs text-fg-3">
                  {t.url ? <a href={t.url} target="_blank" rel="noopener noreferrer" className="hover:text-accent-text">Release filed {formatSessionDate(t.filing_date)}</a> : `Release filed ${formatSessionDate(t.filing_date)}`}
                  {t.error ? ` · ${t.error}` : t.quotes.length ? "" : " · no guidance sentences found"}
                </p>
                <ul className="mt-1 space-y-1">
                  {t.quotes.map((s, i) => <li key={i}><blockquote className="border-l-2 border-info/50 pl-3">{s}</blockquote></li>)}
                </ul>
              </li>
            ))}
          </ol>
          <p className="text-xs leading-4 text-fg-3">{d.method}</p>
        </div>
      )}
    </Panel>
  );
}

/** Upcoming results across the owner's universes (Alerts page). */
export function UpcomingResultsPanel({ className }: { className?: string }) {
  const q = useEarningsCalendar();
  const rows = (q.data?.rows ?? []).filter((r) => r.next).slice(0, 12);
  return (
    <Panel title="Upcoming results" titleId="up-title" className={className} meta={q.data?.universe}>
      {q.isLoading ? (
        <SkeletonRows rows={4} />
      ) : q.isError ? (
        <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
      ) : !rows.length ? (
        <EmptyState title="No dates yet">Add listings to a watchlist; dates appear for US registrants (SEC history) and Indian listings (SEBI deadlines).</EmptyState>
      ) : (
        <div className="space-y-2">
          <ul className="divide-y divide-line-subtle">
            {rows.map((r) => (
              <li key={r.symbol} className="flex items-center justify-between gap-3 py-1.5 text-[13px]">
                <Link to={`/instrument/${encodeURIComponent(r.symbol)}?tab=earnings`} className="num min-w-0 truncate hover:text-accent-text">{r.symbol}</Link>
                <NextDateText c={r} />
              </li>
            ))}
          </ul>
          <p className="text-xs leading-4 text-fg-3">{q.data?.note}</p>
        </div>
      )}
    </Panel>
  );
}
