import { useQuery } from "@tanstack/react-query";
import { Panel } from "@/components/ui/Panel";
import { Pill } from "@/components/ui/Badges";
import { ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { api, errorMessage } from "@/lib/api/client";
import { DASH, formatMoney, formatPercent, formatRelative, formatSessionDate, periodLabel, periodTitle } from "@/lib/format";
import { cn } from "@/lib/cn";

type Row = { key: string; label: string; unit: "percent" | "per_share" | "times" | "days"; formula: string; values: (string | null)[]; why: (string | null)[] | null; statement?: string };
type Table = { columns: string[]; rows: Row[]; note?: string };
type Band = { n: number; min?: number; p25?: number; median?: number; p75?: number; max?: number; current?: number | null; percentile?: number | null; formula: string; why: string | null } | null;
export interface FinAnalysis {
  symbol: string;
  period: "annual" | "quarterly";
  status: string;
  reason?: string;
  source?: string;
  official?: boolean;
  currency?: string | null;
  fetched_at?: string | null;
  notes?: string[];
  per_share?: Table;
  common_size?: Table;
  margins?: Table;
  growth?: Table;
  cagr?: { spans: number[]; rows: (Row & { end: string })[]; note?: string };
  returns?: Table;
  efficiency?: Table;
  bands?: { window?: { from: string; to: string; sessions: number } | null; pe?: Band; ev_ebitda?: Band; note?: string; reason?: string; price_source?: string };
}

export function useFinancialAnalysis(symbol: string, period: "annual" | "quarterly") {
  return useQuery({
    queryKey: ["terminal", "fa", symbol, period],
    queryFn: () => api.get<FinAnalysis>("/api/terminal/financial-analysis", { symbol, period }),
    staleTime: 10 * 60_000,
  });
}

function fmt(row: Row, v: string | null, currency: string | null | undefined, signed: boolean) {
  if (v === null) return DASH;
  if (row.unit === "times") return `${Number(v).toFixed(2)}×`;
  if (row.unit === "days") return `${Math.round(Number(v))} d`;
  return row.unit === "per_share" ? formatMoney(v, currency ?? "USD") : formatPercent(v, { signed });
}

function MetricTable({ title, note, table, currency, signed = false, statement, period }: { title: string; note?: string; table?: Table; currency?: string | null; signed?: boolean; statement?: string; period: "annual" | "quarterly" }) {
  if (!table) return null;
  const all = statement ? table.rows.filter((r) => r.statement === statement) : table.rows;
  if (table.note && !all.length) return <p className="text-[13px] text-fg-3"><span className="font-medium text-fg-2">{title}:</span> {table.note}</p>;
  // Periods most measures cannot fill (e.g. the oldest year for growth, which has nothing to compare with, or a
  // quarter only the half-yearly balance sheet covers) are left out rather than shown as a column of dashes; then
  // measures with no value in any kept period are listed by name instead of filling the table with dashes.
  const withData = all.filter((r) => r.values.some((v) => v !== null));
  const cols = table.columns.map((c, i) => ({ c, i })).filter(({ i }) => withData.filter((r) => r.values[i] !== null).length * 2 >= withData.length && withData.length > 0);
  const rows = withData.filter((r) => cols.some(({ i }) => r.values[i] !== null));
  const absent = all.filter((r) => !withData.includes(r));
  const sparse = withData.filter((r) => !rows.includes(r));
  if (!all.length) return null;
  const absentNote = (absent.length > 0 || sparse.length > 0) && (
    <p className="mt-1 text-xs text-fg-3">
      {absent.length > 0 && (
        <>
          Not available from this source{rows.length ? "" : ` (${title.toLowerCase()})`}: {absent.map((r) => r.label).join(", ")}
          {absent[0].why?.find(Boolean) ? ` — ${(absent[0].why.find(Boolean) ?? "").replace(/\.$/, "")}` : ""}.{" "}
        </>
      )}
      {sparse.length > 0 && <>Only for periods not shown here: {sparse.map((r) => r.label).join(", ")}.</>}
    </p>
  );
  if (!rows.length) return <div>{absentNote}</div>;
  return (
    <div tabIndex={0} className="scroll-x scrollbar-thin overflow-x-auto">
      <table className="w-full text-[13px]" style={{ minWidth: 200 + 84 * cols.length }}>
        <caption className="py-1 text-left text-xs font-medium text-fg-2">
          {title} {note && <span className="font-normal text-fg-3">· {note}</span>}
        </caption>
        <thead>
          <tr className="border-b border-line-subtle text-xs text-fg-3">
            <th scope="col" className="py-1.5 pr-3 text-left font-medium">Measure</th>
            {cols.map(({ c }) => <th key={c} scope="col" className="num px-2 py-1.5 text-right font-medium" title={periodTitle(c, period)}>{periodLabel(c, period)}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-b border-line-subtle/60">
              <th scope="row" className="py-1.5 pr-3 text-left font-normal text-fg" title={r.formula}>
                {r.label}
                <span className="sr-only"> ({r.formula})</span>
              </th>
              {cols.map(({ i }) => {
                const v = r.values[i];
                const n = v === null ? null : Number(v);
                return (
                  <td key={i} className={cn("num px-2 py-1.5 text-right", v === null && "text-fg-3", signed && n !== null && (n >= 0 ? "text-pos" : "text-neg"))} title={v === null ? (r.why?.[i] ?? "Not reported") : undefined}>
                    {fmt(r, v, currency, signed)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {absentNote}
    </div>
  );
}

function BandBar({ label, band, unit }: { label: string; band?: Band; unit: string }) {
  if (!band) return null;
  if (!band.n || band.min === undefined || band.max === undefined) {
    return (
      <div className="text-[13px]">
        <div className="font-medium text-fg">{label}</div>
        <p className="text-xs text-fg-3">{band.why ?? "Not enough data."}</p>
      </div>
    );
  }
  const lo = band.min, hi = band.max;
  const pos = (x: number | null | undefined) => (x === null || x === undefined || hi === lo ? 50 : ((x - lo) / (hi - lo)) * 100);
  const f = (x: number | null | undefined) => (x === null || x === undefined ? DASH : `${x.toFixed(1)}${unit}`);
  return (
    <figure className="m-0 text-[13px]" aria-label={`${label}: minimum ${f(band.min)}, median ${f(band.median)}, maximum ${f(band.max)}, latest ${f(band.current)}`}>
      <figcaption className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-medium text-fg">{label}</span>
        <span className="text-xs text-fg-3">
          latest <span className="num text-fg">{f(band.current)}</span>
          {band.percentile !== null && band.percentile !== undefined && <> · higher than {band.percentile.toFixed(0)}% of days</>}
        </span>
      </figcaption>
      <div className="relative mt-2 h-6" aria-hidden>
        <div className="absolute top-1/2 h-0.5 w-full -translate-y-1/2 bg-line" />
        <div className="absolute top-1 h-4 rounded-sm bg-info-soft ring-1 ring-info/40" style={{ left: `${pos(band.p25)}%`, width: `${Math.max(pos(band.p75) - pos(band.p25), 1)}%` }} />
        <div className="absolute top-0.5 h-5 w-0.5 bg-info" style={{ left: `${pos(band.median)}%` }} />
        {band.current !== null && band.current !== undefined && <div className="absolute top-0 h-6 w-1 -translate-x-1/2 rounded-sm bg-accent" style={{ left: `${pos(band.current)}%` }} />}
      </div>
      <dl className="num mt-1 grid grid-cols-5 gap-1 text-[11px] text-fg-3">
        {(["min", "p25", "median", "p75", "max"] as const).map((k) => (
          <div key={k} className={k === "max" ? "text-right" : k === "min" ? "" : "text-center"}>
            <dt className="sr-only">{k}</dt>
            <dd>{k === "p25" ? "25%: " : k === "p75" ? "75%: " : k === "median" ? "med: " : ""}{f(band[k])}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-1 text-xs text-fg-3">{band.formula}. {band.n.toLocaleString()} days.</p>
    </figure>
  );
}

/** Terminal T2: ratios, growth, returns and valuation history for the statements above, each with its formula. */
export function FinancialAnalysis({ symbol, period }: { symbol: string; period: "annual" | "quarterly" }) {
  const q = useFinancialAnalysis(symbol, period);
  const d = q.data;
  const ccy = d?.currency;
  const b = d?.bands;
  const cagrCols = (d?.cagr?.spans ?? []).map((n, i) => ({ n, i })).filter(({ i }) => d?.cagr?.rows.some((r) => r.values[i] !== null));
  const cagrMissing = (d?.cagr?.spans ?? []).filter((_, i) => !cagrCols.some((c) => c.i === i));
  const p = d?.period ?? period;
  return (
    <>
      <Panel title="Valuation bands" titleId="vb-title" className="lg:col-span-12">
        {q.isLoading ? (
          <SkeletonRows rows={5} />
        ) : !b ? (
          <p className="text-[13px] text-fg-3">{d?.reason ?? "Not available."}</p>
        ) : b.reason && !b.pe ? (
          <p className="text-[13px] text-fg-3">{b.reason}</p>
        ) : (
          <div className="space-y-4">
            <div className="grid gap-6 md:grid-cols-2">
              <BandBar label="P/E" band={b.pe} unit="×" />
              <BandBar label="EV / EBITDA" band={b.ev_ebitda} unit="×" />
            </div>
            <p className="text-xs leading-4 text-fg-3">
              {b.window && <>Daily, {formatSessionDate(b.window.from)} – {formatSessionDate(b.window.to)}. </>}
              {b.note} {b.price_source && `Prices: ${b.price_source}.`} The box spans the middle half of days; the line is the median; the amber mark is the latest day.
            </p>
          </div>
        )}
      </Panel>
      <Panel
        title="Financial analysis"
        titleId="fa-title"
        className="lg:col-span-12"
        wrapHeader
        refreshing={q.isFetching && !q.isLoading}
      >
        {q.isLoading ? (
          <SkeletonRows rows={10} />
        ) : q.isError ? (
          <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
        ) : !d?.margins ? (
          <InlineNotice>{d?.reason ?? "No statements to analyse."}</InlineNotice>
        ) : (
          <div className="space-y-5">
            <p className="flex flex-wrap items-center gap-2 text-xs text-fg-3">
              {d.official === false && <Pill tone="warn">Unofficial</Pill>}
              <span>Source: {d.source}{d.currency ? ` · reported in ${d.currency}` : ""}</span>
            </p>
            {d.notes?.map((n) => <InlineNotice key={n}>{n}</InlineNotice>)}
            <MetricTable period={p} title="Margins" note="share of revenue" table={d.margins} />
            <MetricTable period={p} title="Growth" note={d.period === "annual" ? "against the previous year" : "against the same quarter a year earlier"} table={d.growth} signed />
            {d.cagr && d.cagr.rows.length > 0 && !d.cagr.rows.some((r) => r.values.some((v) => v !== null)) && (
              <p className="text-xs text-fg-3">Compound annual growth: {d.cagr.rows[0].why?.find(Boolean) ?? "not available"}</p>
            )}
            {d.cagr && d.cagr.rows.some((r) => r.values.some((v) => v !== null)) && (
              <div tabIndex={0} className="scroll-x scrollbar-thin overflow-x-auto">
                <table className="w-full text-[13px]" style={{ minWidth: 420 }}>
                  <caption className="py-1 text-left text-xs font-medium text-fg-2">Compound annual growth <span className="font-normal text-fg-3">· to the latest fiscal year</span></caption>
                  <thead>
                    <tr className="border-b border-line-subtle text-xs text-fg-3">
                      <th scope="col" className="py-1.5 pr-3 text-left font-medium">Measure</th>
                      {cagrCols.map(({ n }) => <th key={n} scope="col" className="px-2 py-1.5 text-right font-medium">{n} years</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {d.cagr.rows.map((r) => (
                      <tr key={r.key} className="border-b border-line-subtle/60">
                        <th scope="row" className="py-1.5 pr-3 text-left font-normal text-fg" title={r.formula}>{r.label}</th>
                        {cagrCols.map(({ i }) => {
                          const v = r.values[i];
                          return (
                            <td key={i} className={cn("num px-2 py-1.5 text-right", v === null ? "text-fg-3" : Number(v) >= 0 ? "text-pos" : "text-neg")} title={v === null ? (r.why?.[i] ?? "") : undefined}>
                              {v === null ? DASH : formatPercent(v)}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {cagrMissing.length > 0 && <p className="mt-1 text-xs text-fg-3">Not enough fiscal years in the data for {cagrMissing.join("- or ")}-year growth.</p>}
              </div>
            )}
            <MetricTable period={p} title="Returns and cash conversion" note="ending balances" table={d.returns} />
            <MetricTable period={p} title="Efficiency and working capital" note="ending balances; days on a 365-day year" table={d.efficiency} />
            <MetricTable period={p} title="Per share" note={`in ${ccy ?? "the reporting currency"}, diluted weighted-average shares`} table={d.per_share} currency={ccy} />
            <MetricTable period={p} title="Common size — income statement" note="% of revenue" table={d.common_size} statement="income" />
            <MetricTable period={p} title="Common size — balance sheet" note="% of total assets" table={d.common_size} statement="balance" />
            <MetricTable period={p} title="Common size — cash flow" note="% of revenue" table={d.common_size} statement="cashflow" />
            <p className="text-xs leading-4 text-fg-3">
              Hover a measure for its formula and a dash for the reason it is missing. {d.fetched_at ? `Statements retrieved ${formatRelative(d.fetched_at)}.` : ""}
            </p>
          </div>
        )}
      </Panel>
    </>
  );
}
