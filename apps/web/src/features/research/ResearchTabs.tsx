import { ExternalLink } from "lucide-react";
import { useState } from "react";
import { FinancialAnalysis } from "@/features/terminal/FinancialAnalysis";
import { Panel } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { EmptyState, ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { errorMessage } from "@/lib/api/client";
import { formatLargeMoney, formatMoney, formatPercent, formatRatio, formatRelative, formatSessionDate, formatCompact } from "@/lib/format";
import { cn } from "@/lib/cn";
import { useActions } from "@/features/market/api";
import { useFilings, useFinancials, useResearchEvents, type FactValue, type ResearchEnvelope, type StatementLine } from "./api";

const DASH = "—";
const STATEMENTS: { key: StatementLine["statement"]; title: string; note: string }[] = [
  { key: "income", title: "Income statement", note: "Durations (period start to end)" },
  { key: "balance", title: "Balance sheet", note: "Instants (as of the period end)" },
  { key: "cashflow", title: "Cash flow", note: "Durations (period start to end)" },
];

/** Shared status line for any research dataset: what it is, where it came from, and when it was checked. */
function DatasetStatus<T>({ env }: { env: ResearchEnvelope<T> }) {
  if (env.status === "not_configured") {
    return (
      <InlineNotice tone="info">
        SEC data is not configured on this server. {env.reason} Set <code className="num">SEC_USER_AGENT</code> in the
        hosting environment (README → Render reference); no API key is needed.
      </InlineNotice>
    );
  }
  if (env.status === "not_applicable" || env.status === "missing") {
    return <InlineNotice tone="info">{env.reason}</InlineNotice>;
  }
  if (env.status === "unavailable") {
    return <InlineNotice tone="warn">SEC data is unavailable right now. {env.reason}</InlineNotice>;
  }
  const check = env.checks?.sec_submissions;
  return (
    <p className="text-xs text-fg-3">
      Source: {env.source}
      {env.cik ? <> · CIK <span className="num">{env.cik}</span></> : null}
      {env.fetched_at ? ` · fetched ${formatRelative(env.fetched_at)}` : ""}
      {check?.last_checked_at ? ` · filings last checked ${formatRelative(check.last_checked_at)}` : ""}
      {env.status === "stale" && <span className="text-warn"> · stale: showing the last successful result. {env.reason}</span>}
    </p>
  );
}

function cell(v: FactValue | undefined, line: StatementLine) {
  if (!v) return <span className="text-fg-3">{DASH}</span>;
  const amount = line.key === "eps_diluted" ? formatMoney(v.value, v.unit.split("/")[0]) : v.unit === "shares" ? `${formatCompact(v.value)} sh` : formatLargeMoney(v.value, v.unit);
  const period = v.start ? `${formatSessionDate(v.start)} – ${formatSessionDate(v.end)}` : `as of ${formatSessionDate(v.end)}`;
  const prior = v.prior.length ? ` Earlier filings: ${v.prior.map((p) => `${p.value} (${p.form} filed ${p.filed})`).join("; ")}.` : "";
  const title = `${v.taxonomy}:${v.tag} · ${v.unit} · ${period} · ${v.form} filed ${v.filed} · accession ${v.accession}.${prior}`;
  return (
    <a href={v.source_url} target="_blank" rel="noopener noreferrer" title={title} aria-label={`${line.label} ${amount}, ${title}`} className="num inline-flex items-center gap-1 hover:text-accent-text">
      {amount}
      {v.restated && (
        <span className="rounded border border-warn/50 px-0.5 text-[10px] text-warn" aria-hidden>
          R
        </span>
      )}
    </a>
  );
}

export function FinancialsTab({ symbol }: { symbol: string }) {
  const [period, setPeriod] = useState<"annual" | "quarterly">("annual");
  const q = useFinancials(symbol, period, true, period === "annual" ? 10 : 12); // ten years / twelve quarters where filed
  const env = q.data;
  const st = env?.data;
  return (
    <>
    <Panel title="Financial statements" titleId="fin-title" className="lg:col-span-12" refreshing={q.isFetching && !q.isLoading} wrapHeader
      meta={st ? `${st.taxonomy === "ifrs-full" ? "IFRS" : "US GAAP"} · reported in ${st.currency ?? "?"} · ${st.template === "financial" ? "financial-company template" : "industrial template"}` : undefined}
      actions={<Segmented label="Statement period" value={period} onChange={setPeriod} options={[{ value: "annual", label: "Annual" }, { value: "quarterly", label: "Quarterly" }]} />}
    >
      {q.isLoading ? (
        <SkeletonRows rows={8} />
      ) : q.isError && !env ? (
        <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
      ) : env ? (
        <div className="space-y-4">
          <DatasetStatus env={env} />
          {st && (
            <>
              {st.coverage_note && <InlineNotice tone="warn">{st.coverage_note}</InlineNotice>}
              {STATEMENTS.map((group) => {
                const lines = st.lines.filter((l) => l.statement === group.key);
                return (
                  <div key={group.key} className="scrollbar-thin relative overflow-x-auto">
                    <table className="w-full text-[13px]" style={{ minWidth: 120 + 88 * st.period_ends.length + 64 }}>
                      <caption className="py-1 text-left text-xs font-medium text-fg-2">
                        {group.title} <span className="font-normal text-fg-3">· {group.note}</span>
                      </caption>
                      <thead>
                        <tr className="border-b border-line-subtle text-xs text-fg-3">
                          <th scope="col" className="py-1.5 pr-3 text-left font-medium">Line</th>
                          {st.period_ends.map((e) => (
                            <th key={e} scope="col" className="num px-2 py-1.5 text-right font-medium">{formatSessionDate(e)}</th>
                          ))}
                          <th scope="col" className="px-2 py-1.5 text-right font-medium" title="Latest versus the previous column of the same period type">Change</th>
                        </tr>
                      </thead>
                      <tbody>
                        {lines.map((line) => {
                          const byEnd = new Map(line.values.map((v) => [v.end, v]));
                          const [a, b] = [byEnd.get(st.period_ends[0]), byEnd.get(st.period_ends[1])];
                          const change = a && b && Number(b.value) !== 0 && line.key !== "eps_diluted" ? ((Number(a.value) - Number(b.value)) / Math.abs(Number(b.value))) * 100 : null;
                          return (
                            <tr key={line.key} className="border-b border-line-subtle/60">
                              <th scope="row" className="py-1.5 pr-3 text-left font-normal text-fg-2" title={line.status !== "available" ? line.reason : undefined}>
                                {line.label}
                                {line.status !== "available" && (
                                  <span className="block text-xs text-fg-3">
                                    {line.status === "not_applicable" ? "Not applicable" : "Not reported"}
                                    <span className="max-sm:sr-only">: {line.reason}</span>
                                  </span>
                                )}
                              </th>
                              {st.period_ends.map((e) => (
                                <td key={e} className="px-2 py-1.5 text-right">{line.status === "not_applicable" ? <span className="text-fg-3">n/a</span> : cell(byEnd.get(e), line)}</td>
                              ))}
                              <td className={cn("num px-2 py-1.5 text-right", change === null ? "text-fg-3" : change > 0 ? "text-pos" : change < 0 ? "text-neg" : "")}>
                                {change === null ? DASH : formatPercent(change)}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                );
              })}
              <div>
                <h3 className="mb-1.5 text-xs font-medium text-fg-2">Ratios (computed here from the values above)</h3>
                <dl className="grid gap-x-6 gap-y-2 text-[13px] sm:grid-cols-2 lg:grid-cols-3">
                  {st.ratios.map((r) => (
                    <div key={r.key} className="min-w-0 border-b border-line-subtle/60 pb-1.5">
                      <dt className="flex justify-between gap-2 text-fg-2">
                        <span>{r.key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())}</span>
                        <span className="num text-fg">
                          {r.value === null ? DASH : r.unit === "ratio" ? formatPercent(Number(r.value) * 100, { signed: false }) : r.unit === "multiple" ? formatRatio(r.value) : formatLargeMoney(r.value, r.unit)}
                        </span>
                      </dt>
                      <dd className="text-xs text-fg-3">
                        {r.formula}
                        {r.price_date ? ` · price of ${formatSessionDate(r.price_date)}` : ""}
                        {r.value === null ? " · not computed: an input is missing or in another currency" : ""}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
              <p className="text-xs text-fg-3 sm:hidden">Tables scroll sideways for earlier periods.</p>
              <p className="text-xs text-fg-3">
                Each value links to its SEC filing; hover or focus it for the tag, unit, period, form and accession. R marks a value restated in a later filing.
                Year-to-date figures are excluded and a missing fourth quarter is not derived. <a className="underline" href={st.facts_url} target="_blank" rel="noopener noreferrer">SEC company facts (JSON)</a>
              </p>
            </>
          )}
        </div>
      ) : null}
    </Panel>
    <FinancialAnalysis symbol={symbol} period={period} />
    </>
  );
}

function FilingList({ rows, showEvent }: { rows: ReturnType<typeof useFilings>["data"] extends infer E ? E extends { data: infer D } ? D : never : never; showEvent?: boolean }) {
  if (!rows?.length) return <EmptyState title="No filings listed">SEC lists no matching recent filings for this registrant.</EmptyState>;
  return (
    <ul className="divide-y divide-line-subtle text-[13px]">
      {rows.map((f) => (
        <li key={f.accession + (f.event ?? "")} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2">
          <span className="num w-28 shrink-0 whitespace-nowrap text-fg-2">{formatSessionDate(f.filing_date)}</span>
          <span className="num w-16 shrink-0 font-semibold text-fg">{f.form}</span>
          <span className="min-w-0 flex-1 text-fg-2">
            {showEvent ? f.event : f.description}
            {f.report_date ? <span className="text-fg-3"> · period {formatSessionDate(f.report_date)}</span> : null}
            {f.items.length ? <span className="text-fg-3"> · items {f.items.join(", ")}</span> : null}
            {showEvent && f.certainty && <span className="ml-1 rounded border border-line px-1 text-[11px] text-fg-3">{f.certainty}</span>}
          </span>
          <span className="flex gap-3 text-xs">
            {f.document_url && (
              <a className="inline-flex items-center gap-1 text-fg-2 hover:text-fg" href={f.document_url} target="_blank" rel="noopener noreferrer">
                Document <ExternalLink className="size-3" aria-hidden />
              </a>
            )}
            <a className="inline-flex items-center gap-1 text-fg-2 hover:text-fg" href={f.index_url} target="_blank" rel="noopener noreferrer">
              Filing index <ExternalLink className="size-3" aria-hidden />
            </a>
          </span>
        </li>
      ))}
    </ul>
  );
}

export function FilingsTab({ symbol }: { symbol: string }) {
  const q = useFilings(symbol);
  return (
    <Panel title="Filings" titleId="filings-title" className="lg:col-span-12" refreshing={q.isFetching && !q.isLoading}>
      {q.isLoading ? <SkeletonRows rows={8} /> : q.isError && !q.data ? <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} /> : q.data ? (
        <div className="space-y-3">
          <DatasetStatus env={q.data} />
          {q.data.data && <FilingList rows={q.data.data} />}
        </div>
      ) : null}
    </Panel>
  );
}

export function EventsTab({ symbol }: { symbol: string }) {
  const q = useResearchEvents(symbol);
  const actions = useActions(symbol);
  return (
    <>
      <Panel title="Filing events" titleId="events-title" className="lg:col-span-8" refreshing={q.isFetching && !q.isLoading}>
        {q.isLoading ? <SkeletonRows rows={6} /> : q.isError && !q.data ? <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} /> : q.data ? (
          <div className="space-y-3">
            <DatasetStatus env={q.data} />
            {q.data.data && <FilingList rows={q.data.data} showEvent />}
            <p className="text-xs text-fg-3">
              Confirmed events only, from SEC filings: results announcements (8-K Item 2.02) and periodic reports. Estimated earnings dates are not shown because no verified
              source is configured.
            </p>
          </div>
        ) : null}
      </Panel>
      <Panel title="Corporate actions" titleId="ev-ca-title" className="lg:col-span-4">
        {actions.isLoading ? <SkeletonRows rows={4} /> : actions.data?.actions?.length ? (
          <ul className="divide-y divide-line-subtle text-[13px]">
            {actions.data.actions.slice(0, 12).map((a, i) => (
              <li key={i} className="flex justify-between gap-2 py-1.5">
                <span className="num text-fg-2">{formatSessionDate(a.date)}</span>
                <span className="text-fg">{a.description}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-fg-3">{actions.data?.meta.message ?? "No corporate actions reported by the price provider."}</p>
        )}
        <p className="mt-2 text-xs text-fg-3">Source: price provider (Yahoo). Confirmed past actions only.</p>
      </Panel>
    </>
  );
}
