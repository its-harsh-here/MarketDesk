import { ExternalLink } from "lucide-react";
import { useState } from "react";
import { FinancialAnalysis } from "@/features/terminal/FinancialAnalysis";
import { Panel } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { EmptyState, ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { errorMessage } from "@/lib/api/client";
import { formatLargeMoney, formatMoney, formatPercent, formatRatio, formatRelative, formatSessionDate, formatCompact, periodLabel, periodTitle } from "@/lib/format";
import { cn } from "@/lib/cn";
import { useFilings, useFinancials, type FactValue, type ResearchEnvelope, type StatementLine, type Statements } from "./api";

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
        SEC filings are not configured on this server.
      </InlineNotice>
    );
  }
  if (env.status === "not_applicable" || env.status === "missing") {
    return <InlineNotice tone="info">{env.reason}</InlineNotice>;
  }
  if (env.status === "unavailable") {
    return <InlineNotice tone="warn">This data is unavailable right now. {env.reason}</InlineNotice>;
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

function cell(v: FactValue | undefined, line: StatementLine, period: "annual" | "quarterly") {
  if (!v) return <span className="text-fg-3" title="Not reported for this period">{DASH}</span>;
  const amount = line.key === "eps_diluted" ? formatMoney(v.value, v.unit.split("/")[0]) : v.unit === "shares" ? `${formatCompact(v.value)} sh` : formatLargeMoney(v.value, v.unit);
  if (!v.source_url) {
    const ccy = v.unit === "statement currency" ? "; reporting currency not stated by the source" : "";
    return <span className="num" title={`${periodTitle(v.end, period)} · provider statements (unofficial)${ccy}`}>{amount}</span>;
  }
  const span = v.start ? `${formatSessionDate(v.start)} – ${formatSessionDate(v.end)}` : `as of ${formatSessionDate(v.end)}`;
  const prior = v.prior.length ? ` Earlier filings: ${v.prior.map((p) => `${p.value} (${p.form} filed ${p.filed})`).join("; ")}.` : "";
  const title = `${v.taxonomy}:${v.tag} · ${v.unit} · ${span} · ${v.form} filed ${v.filed} · accession ${v.accession}.${prior}`;
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

/**
 * One statement as a table with no empty spots: only lines with figures become rows (the others are named below
 * with the reason), and only periods most of those lines report become columns. A single unreported figure in a
 * kept period still shows a dash, with the reason on hover — it is never filled in.
 */
function StatementTable({ st, group }: { st: Statements; group: (typeof STATEMENTS)[number] }) {
  const lines = st.lines.filter((l) => l.statement === group.key);
  const shown = lines.filter((l) => l.status === "available" && l.values.length > 0);
  const absent = lines.filter((l) => !shown.includes(l));
  const cols = st.period_ends.filter((e) => shown.filter((l) => l.values.some((v) => v.end === e)).length * 2 >= shown.length);
  const missingNote = absent.length > 0 && (
    <p className="mt-1 text-xs text-fg-3">
      {absent.some((l) => l.status === "not_applicable") && <>Not applicable to banks and insurers: {absent.filter((l) => l.status === "not_applicable").map((l) => l.label).join(", ")}. </>}
      {absent.some((l) => l.status !== "not_applicable") && <>Not reported by the source{shown.length ? "" : ` (${group.title.toLowerCase()})`}: {absent.filter((l) => l.status !== "not_applicable").map((l) => l.label).join(", ")}.</>}
    </p>
  );
  if (!shown.length || !cols.length) return <div>{missingNote}</div>;
  return (
    <div tabIndex={0} className="scroll-x scrollbar-thin relative overflow-x-auto">
      <table className="w-full text-[13px]" style={{ minWidth: 160 + 88 * cols.length + 64 }}>
        <caption className="py-1 text-left text-xs font-medium text-fg-2">
          {group.title} <span className="font-normal text-fg-3">· {group.note}</span>
        </caption>
        <thead>
          <tr className="border-b border-line-subtle text-xs text-fg-3">
            <th scope="col" className="py-1.5 pr-3 text-left font-medium">Line</th>
            {cols.map((e) => (
              <th key={e} scope="col" className="num px-2 py-1.5 text-right font-medium" title={periodTitle(e, st.period)}>{periodLabel(e, st.period)}</th>
            ))}
            <th scope="col" className="px-2 py-1.5 text-right font-medium" title={`Latest column versus the one before it (${st.period === "annual" ? "previous fiscal year" : "previous quarter shown"})`}>Change</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((line) => {
            const byEnd = new Map(line.values.map((v) => [v.end, v]));
            const [a, b] = [byEnd.get(cols[0]), byEnd.get(cols[1])];
            const change = a && b && Number(b.value) !== 0 ? ((Number(a.value) - Number(b.value)) / Math.abs(Number(b.value))) * 100 : null;
            return (
              <tr key={line.key} className="border-b border-line-subtle/60">
                <th scope="row" className="py-1.5 pr-3 text-left font-normal text-fg-2">{line.label}</th>
                {cols.map((e) => (
                  <td key={e} className="px-2 py-1.5 text-right">{cell(byEnd.get(e), line, st.period)}</td>
                ))}
                <td className={cn("num px-2 py-1.5 text-right", change === null ? "text-fg-3" : change > 0 ? "text-pos" : change < 0 ? "text-neg" : "")} title={change === null ? "Needs both of the two latest columns" : undefined}>
                  {change === null ? DASH : formatPercent(change)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {missingNote}
    </div>
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
      meta={st ? (st.origin === "provider" ? `Reported statements · unofficial · ${st.currency ? `in ${st.currency}` : "reporting currency not stated"}` : `${st.taxonomy === "ifrs-full" ? "IFRS" : "US GAAP"} · reported in ${st.currency ?? "?"} · ${st.template === "financial" ? "financial-company template" : "industrial template"}`) : undefined}
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
              {STATEMENTS.map((group) => <StatementTable key={group.key} st={st} group={group} />)}
              <div>
                <h3 className="mb-1.5 text-xs font-medium text-fg-2">Ratios (computed here from the values above)</h3>
                <dl className="grid gap-x-6 gap-y-2 text-[13px] sm:grid-cols-2 lg:grid-cols-3">
                  {st.ratios.filter((r) => r.value !== null).map((r) => (
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
                      </dd>
                    </div>
                  ))}
                </dl>
                {st.ratios.some((r) => r.value === null) && (
                  <p className="mt-1 text-xs text-fg-3">
                    Not computed (an input is missing or in another currency): {st.ratios.filter((r) => r.value === null).map((r) => r.key.replace(/_/g, " ")).join(", ")}.
                  </p>
                )}
              </div>
              <p className="text-xs text-fg-3 sm:hidden">Tables scroll sideways for earlier periods.</p>
              {st.origin === "provider" ? (
                <p className="text-xs text-fg-3">
                  Unofficial figures from the market-data provider's statement tables (this listing is outside SEC coverage), as published, without filing links.
                  Columns are fiscal years or quarters by their end month; hover a header for the exact period end. Missing periods are never derived.
                </p>
              ) : (
                <p className="text-xs text-fg-3">
                  Each value links to its SEC filing; hover or focus it for the tag, unit, period, form and accession. R marks a value restated in a later filing.
                  Year-to-date figures are excluded and a missing fourth quarter is not derived. {st.facts_url && <a className="underline" href={st.facts_url} target="_blank" rel="noopener noreferrer">SEC company facts (JSON)</a>}
                </p>
              )}
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
