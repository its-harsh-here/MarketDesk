import { useQuery } from "@tanstack/react-query";
import { Panel } from "@/components/ui/Panel";
import { ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { api, errorMessage } from "@/lib/api/client";
import { cn } from "@/lib/cn";
import { DASH, formatMoney, formatPercent, formatSessionDate } from "@/lib/format";

interface Row {
  code: string;
  label: string;
  start?: string;
  return_pct: string | null;
  annualized_pct?: string | null;
  benchmark_pct: string | null;
  benchmark_annualized_pct?: string | null;
  relative_pct: string | null;
  why: string | null;
}
interface Perf {
  symbol: string;
  status: string;
  reason?: string;
  as_of?: string;
  benchmark?: { symbol: string; name: string | null; as_of: string | null; why: string | null };
  rows?: Row[];
  range_52w?: { high: string; high_date: string; low: string; low_date: string; from_high_pct: string; from_low_pct: string } | null;
  note?: string;
}

const pctCell = (v: string | null | undefined) => {
  if (v === null || v === undefined) return <span className="text-fg-3">{DASH}</span>;
  const n = Number(v);
  return <span className={cn("num", n > 0 ? "text-pos" : n < 0 ? "text-neg" : "text-fg-2")}>{formatPercent(n)}</span>;
};

/** Price return over standard periods next to the market benchmark, with a bar for each, and the 52-week range. */
export function PerformancePanel({ symbol, currency, className }: { symbol: string; currency: string | null; className?: string }) {
  const q = useQuery({
    queryKey: ["terminal", "performance", symbol],
    queryFn: ({ signal }) => api.get<Perf>("/api/terminal/performance", { symbol }, signal),
    staleTime: 10 * 60_000,
    retry: false,
  });
  const d = q.data;
  const max = Math.max(1, ...(d?.rows ?? []).flatMap((r) => [Math.abs(Number(r.return_pct ?? 0)), Math.abs(Number(r.benchmark_pct ?? 0))]));
  const r52 = d?.range_52w;
  return (
    <Panel title="Performance overview" titleId="perf-title" className={className} refreshing={q.isFetching && !q.isLoading} wrapHeader
      meta={d?.benchmark ? `vs ${d.benchmark.name ?? d.benchmark.symbol} · to ${formatSessionDate(d.as_of)}` : undefined}>
      {q.isLoading ? <SkeletonRows rows={8} /> : q.isError || !d ? <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} /> : d.status === "missing" ? (
        <InlineNotice>{d.reason}</InlineNotice>
      ) : (
        <div className="space-y-4">
          <table className="w-full text-[13px]" aria-label={`Price return of ${symbol} and its benchmark by period`}>
            <thead>
              <tr className="border-b border-line-subtle text-xs text-fg-3">
                <th scope="col" className="py-1.5 text-left font-medium">Period</th>
                <th scope="col" className="px-2 py-1.5 text-right font-medium">{symbol}</th>
                <th scope="col" className="px-2 py-1.5 text-right font-medium">Benchmark</th>
                <th scope="col" className="w-[38%] py-1.5 font-medium max-sm:hidden"><span className="sr-only">Bars</span></th>
              </tr>
            </thead>
            <tbody>
              {d.rows!.map((r) => (
                <tr key={r.code} className="border-b border-line-subtle/60" title={r.why ?? (r.start ? `From the close of ${formatSessionDate(r.start)}` : undefined)}>
                  <th scope="row" className="py-1.5 text-left font-normal text-fg-2">
                    {r.label}
                    {r.annualized_pct && <span className="block text-[11px] text-fg-3">per year {formatPercent(Number(r.annualized_pct))}</span>}
                  </th>
                  <td className="px-2 text-right">{pctCell(r.return_pct)}</td>
                  <td className="px-2 text-right">{pctCell(r.benchmark_pct)}</td>
                  <td className="py-1.5 max-sm:hidden" aria-hidden>
                    {[r.return_pct, r.benchmark_pct].map((v, i) => {
                      const n = Number(v ?? 0);
                      const w = (Math.abs(n) / max) * 50;
                      return (
                        <div key={i} className="relative my-0.5 h-1.5 rounded-full bg-elevated">
                          <span className="absolute inset-y-0 left-1/2 w-px bg-line" />
                          {v !== null && (
                            <span className={cn("absolute inset-y-0 rounded-full transition-all duration-700", i === 0 ? (n >= 0 ? "bg-pos" : "bg-neg") : "bg-fg-3/60")}
                              style={n >= 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }} />
                          )}
                        </div>
                      );
                    })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {r52 && (
            <div>
              <div className="mb-1 flex justify-between text-xs text-fg-3">
                <span>52-week low {formatMoney(r52.low, currency)} · {formatSessionDate(r52.low_date)}</span>
                <span>high {formatMoney(r52.high, currency)} · {formatSessionDate(r52.high_date)}</span>
              </div>
              <div className="relative h-2 rounded-full bg-gradient-to-r from-neg/40 via-elevated to-pos/40" role="img"
                aria-label={`${formatPercent(Number(r52.from_high_pct))} from the 52-week high, ${formatPercent(Number(r52.from_low_pct))} above the low`}>
                {(() => {
                  const lo = Number(r52.low), hi = Number(r52.high);
                  const last = lo * (1 + Number(r52.from_low_pct) / 100);
                  const pos = hi > lo ? ((last - lo) / (hi - lo)) * 100 : 50;
                  return <span className="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-panel bg-accent shadow-[0_0_10px_var(--glow)] transition-all duration-700" style={{ left: `${pos}%` }} />;
                })()}
              </div>
              <p className="mt-1 text-xs text-fg-3">
                <span className="num">{formatPercent(Number(r52.from_high_pct))}</span> from the high · <span className="num">{formatPercent(Number(r52.from_low_pct))}</span> above the low (daily closes)
              </p>
            </div>
          )}
          {d.benchmark?.why && <p className="text-xs text-warn">Benchmark: {d.benchmark.why}</p>}
          <p className="text-xs leading-4 text-fg-3">{d.note}</p>
        </div>
      )}
    </Panel>
  );
}
