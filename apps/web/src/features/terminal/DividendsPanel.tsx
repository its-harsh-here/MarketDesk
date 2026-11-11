import { useQuery } from "@tanstack/react-query";
import { Panel } from "@/components/ui/Panel";
import { ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { api, errorMessage } from "@/lib/api/client";
import { DASH, formatMoney, formatPercent, formatSessionDate } from "@/lib/format";

interface Div {
  symbol: string;
  status: "available" | "none" | "unavailable";
  why?: string;
  last?: { ex_date: string; amount: string };
  ttm?: { total: string; payments: number; from: string; yield_pct: string | null };
  frequency?: string;
  indicated?: { total: string; per_year: number; yield_pct: string | null } | null;
  years?: { year: number; total: string; payments: number }[];
  growth_5y?: { years: number; from: number; to: number; cagr_pct: string } | null;
  increase_streak_years?: number;
  currency?: string | null;
  source?: string;
  note?: string;
}

/** Trailing dividends and yield, frequency, yearly totals and growth (DVD). */
export function DividendsPanel({ symbol, className }: { symbol: string; className?: string }) {
  const q = useQuery({
    queryKey: ["terminal", "dividends", symbol],
    queryFn: ({ signal }) => api.get<Div>("/api/terminal/dividends", { symbol }, signal),
    staleTime: 30 * 60_000,
    retry: false,
  });
  const d = q.data;
  const years = d?.years ?? [];
  const max = Math.max(0.0001, ...years.map((y) => Number(y.total)));
  const thisYear = new Date().getFullYear();
  return (
    <Panel title="Dividends" titleId="dv-title" className={className} refreshing={q.isFetching && !q.isLoading} meta={d?.source}>
      {q.isLoading ? <SkeletonRows rows={5} /> : q.isError || !d ? <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} /> : d.status !== "available" ? (
        <InlineNotice>{d.why}</InlineNotice>
      ) : (
        <div className="space-y-3 text-[13px]">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
            <div><dt className="text-xs text-fg-3">Trailing 12 months</dt><dd className="num text-base font-semibold text-fg">{formatMoney(d.ttm!.total, d.currency)} <span className="text-xs font-normal text-fg-3">{d.ttm!.payments} payment{d.ttm!.payments === 1 ? "" : "s"}</span></dd></div>
            <div><dt className="text-xs text-fg-3">Trailing yield</dt><dd className="num text-base font-semibold text-fg">{d.ttm!.yield_pct ? formatPercent(Number(d.ttm!.yield_pct), { signed: false }) : DASH}</dd></div>
            <div title="Latest payment × payments a year (a convention, not a forecast)"><dt className="text-xs text-fg-3">Indicated annual{d.indicated ? ` (last × ${d.indicated.per_year})` : ""}</dt><dd className="num text-fg">{d.indicated ? formatMoney(d.indicated.total, d.currency) : DASH}</dd></div>
            <div><dt className="text-xs text-fg-3">Indicated yield</dt><dd className="num text-fg">{d.indicated?.yield_pct ? formatPercent(Number(d.indicated.yield_pct), { signed: false }) : DASH}</dd></div>
            <div><dt className="text-xs text-fg-3">Last ex-date</dt><dd className="num text-fg">{formatSessionDate(d.last!.ex_date)} · {formatMoney(d.last!.amount, d.currency)}</dd></div>
            <div><dt className="text-xs text-fg-3">Frequency</dt><dd className="text-fg">{d.frequency}</dd></div>
            <div><dt className="text-xs text-fg-3">5-year growth (per year)</dt><dd className="num text-fg">{d.growth_5y ? `${formatPercent(Number(d.growth_5y.cagr_pct))} (${d.growth_5y.from}–${d.growth_5y.to})` : DASH}</dd></div>
            <div><dt className="text-xs text-fg-3">Consecutive yearly increases</dt><dd className="num text-fg">{d.increase_streak_years}</dd></div>
          </dl>
          {years.length > 1 && (
            <div aria-hidden>
              <div className="flex h-24 items-end gap-1">
                {years.map((y) => (
                  <div key={y.year} className="flex flex-1 flex-col items-center gap-1" title={`${y.year}: ${formatMoney(y.total, d.currency)} in ${y.payments} payment(s)${y.year === thisYear ? " (year to date)" : ""}`}>
                    <span className={y.year === thisYear ? "w-full rounded-t-sm border border-dashed border-pos/60 bg-pos/20" : "w-full rounded-t-sm bg-pos/70"} style={{ height: `${(Number(y.total) / max) * 80}px` }} />
                    <span className="num text-[10px] text-fg-3">{String(y.year).slice(2)}</span>
                  </div>
                ))}
              </div>
              <p className="text-[11px] text-fg-3">Dividends per share by calendar year; the dashed bar is the year so far.</p>
            </div>
          )}
          <p className="text-xs leading-4 text-fg-3">{d.note}</p>
        </div>
      )}
    </Panel>
  );
}
