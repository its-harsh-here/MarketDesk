import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";
import { Panel } from "@/components/ui/Panel";
import { Pill } from "@/components/ui/Badges";
import { Field, Select } from "@/components/ui/Form";
import { ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { api, errorMessage } from "@/lib/api/client";
import { DASH, formatCompact, formatLargeMoney, formatNumber, formatPercent, formatRelative, formatSessionDate } from "@/lib/format";
import { cn } from "@/lib/cn";
import { SymbolPicker } from "@/features/search/SymbolPicker";
import { useWatchlists } from "@/features/watchlists/api";

type Sens = { beta: string | number | null; correlation: number | null; r2: number | null; n: number; method: string; why: string | null };
type Episode = { peak: string; trough: string; depth: number; recovered: string | null; days_to_trough: number; days_to_recover: number | null };
interface Risk {
  symbol: string;
  status?: string;
  reason?: string;
  benchmark: { symbol: string; name?: string | null; timezone?: string | null; same_market?: boolean };
  prices?: { source: string; adjustment: string; to: string };
  sensitivity?: Record<"1Y" | "3Y", Sens> | { why: string };
  volatility?: Record<"1Y" | "3Y", { value: number | null; n: number; why: string | null }>;
  drawdowns?: { current?: number; high?: { date: string; close: number }; windows?: Record<string, { max: number | null; peak?: string; trough?: string; recovered?: string | null; why?: string }>; episodes?: Episode[]; why?: string };
  liquidity?: { adv_20: string | null; adv_60: string | null; value_20: string | null; median_range_pct: number | null; sessions: number };
  relative?: { why?: string; universe?: { label: string; members: number; with_snapshot: number }; rows: { key: string; label: string; unit: string; value: string | null; n: number; mean?: string; median?: string; z?: string | null; percentile?: string; why: string | null }[]; note: string };
  peer_valuation?: { source: string; rows: { symbol: string; n?: number; min?: number; median?: number; max?: number; current?: number | null; percentile?: number | null; why?: string | null }[] };
  short_interest?: { status: string; reason?: string | null; source: string; fetched_at?: string | null; rows?: { settlement_date: string; short_position: number; change_pct: number; avg_daily_volume: number; days_to_cover: number; revised: boolean; split: boolean }[]; note?: string };
}

function useRisk(symbol: string, benchmark: string | null, universe: string) {
  return useQuery({
    queryKey: ["terminal", "risk", symbol, benchmark, universe],
    queryFn: () => api.get<Risk>("/api/terminal/risk", { symbol, universe, ...(benchmark ? { benchmark } : {}) }),
    staleTime: 10 * 60_000,
    retry: false,
  });
}

const pct = (x: number | null | undefined, signed = false) => (x === null || x === undefined ? DASH : formatPercent(x * 100, { signed }));
const num = (x: string | number | null | undefined, d = 2) => (x === null || x === undefined ? DASH : formatNumber(Number(x), d));

/** Terminal T6: how the security moves with its benchmark, how deep its falls have been, how easily it trades,
 * where it sits within your universe, its peers' valuation history and (US, when configured) short interest. */
export function RiskTab({ symbol, currency }: { symbol: string; currency: string | null }) {
  const [params, setParams] = useSearchParams();
  const bench = params.get("bench");
  const universe = params.get("uni") ?? "watchlists";
  const q = useRisk(symbol, bench, universe);
  const { data: lists } = useWatchlists();
  const d = q.data;
  const set = (k: string, v: string | null) => setParams((p) => { const n = new URLSearchParams(p); if (v) n.set(k, v); else n.delete(k); return n; }, { replace: true });

  if (q.isLoading) return <Panel title="Risk and relative value" titleId="rk-title" className="lg:col-span-12"><SkeletonRows rows={10} /></Panel>;
  if (q.isError || !d) return <Panel title="Risk and relative value" titleId="rk-title" className="lg:col-span-12"><ErrorState message={errorMessage(q.error)} onRetry={() => (bench ? set("bench", null) : q.refetch())} /></Panel>;
  if (d.status === "missing") return <Panel title="Risk and relative value" titleId="rk-title" className="lg:col-span-12"><InlineNotice>{d.reason}</InlineNotice></Panel>;
  const sens = d.sensitivity && "1Y" in d.sensitivity ? d.sensitivity : null;
  const few = (d.relative?.universe?.with_snapshot ?? 0) < 5;
  const dd = d.drawdowns;
  return (
    <>
      <Panel title="Benchmark sensitivity" titleId="sens-title" className="lg:col-span-6" refreshing={q.isFetching}>
        <div className="mb-3 flex flex-wrap items-end gap-3">
          <Field label="Benchmark" className="w-64">
            {({ id }) => <SymbolPicker id={id} value={bench ?? ""} placeholder={d.benchmark.symbol} onChange={(s) => set("bench", s || null)} />}
          </Field>
          {bench && <button type="button" className="h-9 text-xs text-info underline decoration-info/40 underline-offset-2 hover:decoration-info" onClick={() => set("bench", null)}>Use the default</button>}
        </div>
        {!sens ? (
          <p className="text-[13px] text-fg-3">{(d.sensitivity as { why?: string } | undefined)?.why}</p>
        ) : (
          <table className="w-full text-[13px]">
            <caption className="sr-only">Beta, correlation and R squared against {d.benchmark.symbol}</caption>
            <thead><tr className="border-b border-line-subtle text-xs text-fg-3"><th scope="col" className="py-1.5 text-left font-medium">Window</th><th scope="col" className="py-1.5 text-right font-medium">Beta</th><th scope="col" className="py-1.5 text-right font-medium">Correlation</th><th scope="col" className="py-1.5 text-right font-medium">R²</th><th scope="col" className="py-1.5 text-right font-medium">Returns</th></tr></thead>
            <tbody>
              {(["1Y", "3Y"] as const).map((w) => {
                const s = sens[w];
                return (
                  <tr key={w} className="border-b border-line-subtle/60">
                    <th scope="row" className="py-1.5 text-left font-normal">{w}</th>
                    {s.beta === null ? <td colSpan={4} className="py-1.5 text-right text-xs text-fg-3">{s.why}</td> : (
                      <>
                        <td className="num py-1.5 text-right">{num(s.beta)}</td>
                        <td className="num py-1.5 text-right">{num(s.correlation)}</td>
                        <td className="num py-1.5 text-right">{num(s.r2)}</td>
                        <td className="num py-1.5 text-right">{s.n} {s.method}</td>
                      </>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <p className="mt-3 text-xs leading-4 text-fg-3">
          Against <span className="num">{d.benchmark.symbol}</span>{d.benchmark.name ? ` (${d.benchmark.name})` : ""}: {d.benchmark.same_market ? "daily returns (same trading time zone)" : "weekly returns (different time zones, so days do not line up)"}. Beta = covariance ÷ benchmark variance. {d.prices?.source} to {formatSessionDate(d.prices?.to)}; dividends not included.
        </p>
      </Panel>

      <Panel title="Volatility and drawdowns" titleId="dd-title" className="lg:col-span-6">
        {!dd || dd.why ? <p className="text-[13px] text-fg-3">{dd?.why}</p> : (
          <>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-[13px]">
              {(["1Y", "3Y"] as const).map((w) => <div key={w} className="flex justify-between gap-2"><dt className="text-fg-2">Volatility {w}</dt><dd className="num" title={d.volatility?.[w].why ?? "Annualized standard deviation of daily returns"}>{d.volatility?.[w].value === null ? DASH : pct(d.volatility?.[w].value)}</dd></div>)}
              <div className="flex justify-between gap-2"><dt className="text-fg-2">From high</dt><dd className="num text-neg">{pct(dd.current)}</dd></div>
              {Object.entries(dd.windows ?? {}).map(([w, x]) => <div key={w} className="flex justify-between gap-2"><dt className="text-fg-2">Max drawdown {w}</dt><dd className="num" title={x.why ?? (x.peak ? `${formatSessionDate(x.peak)} → ${formatSessionDate(x.trough)}` : "")}>{x.max === null ? DASH : pct(x.max)}</dd></div>)}
            </dl>
            {dd.episodes && dd.episodes.length > 0 && (
              <table className="mt-3 w-full text-[13px]">
                <caption className="py-1 text-left text-xs font-medium text-fg-2">Deepest declines <span className="font-normal text-fg-3">· from a high to the first close back at it</span></caption>
                <thead><tr className="border-b border-line-subtle text-xs text-fg-3"><th scope="col" className="py-1 text-left font-medium">High</th><th scope="col" className="py-1 text-left font-medium">Low</th><th scope="col" className="py-1 text-right font-medium">Decline</th><th scope="col" className="py-1 text-right font-medium">Recovered</th></tr></thead>
                <tbody>
                  {dd.episodes.map((e) => (
                    <tr key={e.peak} className="border-b border-line-subtle/60">
                      <td className="num py-1">{formatSessionDate(e.peak)}</td>
                      <td className="num py-1">{formatSessionDate(e.trough)} <span className="text-xs text-fg-3">({e.days_to_trough} d)</span></td>
                      <td className="num py-1 text-right text-neg">{pct(e.depth)}</td>
                      <td className="num py-1 text-right">{e.recovered ? <>{formatSessionDate(e.recovered)} <span className="text-xs text-fg-3">({e.days_to_recover} d)</span></> : <Pill tone="warn">not yet</Pill>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p className="mt-2 text-xs text-fg-3">Daily closes from the provider's split-adjusted history; highest close {num(dd.high?.close)} on {formatSessionDate(dd.high?.date)}.</p>
          </>
        )}
      </Panel>

      <Panel title="Liquidity" titleId="lq-title" className="lg:col-span-4">
        <dl className="text-[13px]">
          <div className="flex justify-between gap-2 py-1"><dt className="text-fg-2">Avg volume (20 sessions)</dt><dd className="num">{d.liquidity?.adv_20 ? formatCompact(d.liquidity.adv_20) : DASH}</dd></div>
          <div className="flex justify-between gap-2 py-1"><dt className="text-fg-2">Avg volume (60 sessions)</dt><dd className="num">{d.liquidity?.adv_60 ? formatCompact(d.liquidity.adv_60) : DASH}</dd></div>
          <div className="flex justify-between gap-2 py-1"><dt className="text-fg-2">Avg traded value (20)</dt><dd className="num">{d.liquidity?.value_20 ? formatLargeMoney(d.liquidity.value_20, currency) : DASH}</dd></div>
          <div className="flex justify-between gap-2 py-1"><dt className="text-fg-2">Median daily range</dt><dd className="num">{d.liquidity?.median_range_pct === null || d.liquidity?.median_range_pct === undefined ? DASH : `${d.liquidity.median_range_pct.toFixed(2)}%`}</dd></div>
        </dl>
        <p className="mt-2 text-xs leading-4 text-fg-3">Daily range = (high − low) ÷ close, median of the last {d.liquidity?.sessions ?? 60} sessions. No bid-ask spread is shown: MarketDesk has no quotes to measure one, and estimates from daily prices are unreliable for liquid stocks.</p>
      </Panel>

      <Panel title="Within your universe" titleId="rel-title" className="lg:col-span-8">
        <div className="mb-3 flex flex-wrap items-end gap-3">
          <Field label="Universe" className="w-60">
            {({ id }) => (
              <Select id={id} value={universe} onChange={(e) => set("uni", e.target.value === "watchlists" ? null : e.target.value)}>
                <option value="watchlists">All watchlists</option>
                <option value="holdings">Holdings</option>
                {lists?.map((l) => <option key={l.id} value={`watchlist:${l.id}`}>{l.name}</option>)}
              </Select>
            )}
          </Field>
          <span className="pb-2 text-xs text-fg-3">{d.relative?.universe?.members ?? 0} members · {d.relative?.universe?.with_snapshot ?? 0} with data</span>
        </div>
        {few && (
          <InlineNotice className="mb-3">
            z-scores and percentiles need at least 5 members with data; {d.relative?.universe?.label ?? "this universe"} has {d.relative?.universe?.with_snapshot ?? 0}. Add comparable instruments to a watchlist and load their data on the <Link to="/screener" className="text-info underline decoration-info/40 underline-offset-2 hover:decoration-info">Screener</Link>.
          </InlineNotice>
        )}
        <div tabIndex={0} className="scroll-x scrollbar-thin overflow-x-auto">
          <table className="w-full text-[13px]" style={{ minWidth: few ? 0 : 520 }}>
            <caption className="sr-only">Where {symbol} sits within {d.relative?.universe?.label}</caption>
            <thead><tr className="border-b border-line-subtle text-xs text-fg-3"><th scope="col" className="py-1.5 text-left font-medium">Metric</th><th scope="col" className="py-1.5 text-right font-medium">{symbol}</th>{!few && <><th scope="col" className="py-1.5 text-right font-medium">Median</th><th scope="col" className="py-1.5 text-right font-medium">z-score</th><th scope="col" className="py-1.5 text-right font-medium">At or above</th></>}</tr></thead>
            <tbody>
              {(d.relative?.rows ?? []).map((r) => (
                <tr key={r.key} className="border-b border-line-subtle/60">
                  <th scope="row" className="py-1.5 text-left font-normal">{r.label}</th>
                  <td className="num py-1.5 text-right">{r.value === null ? DASH : num(r.value)}</td>
                  {few ? null : r.why ? <td colSpan={3} className="py-1.5 text-right text-xs text-fg-3">{r.why}</td> : (
                    <>
                      <td className="num py-1.5 text-right">{num(r.median)}</td>
                      <td className={cn("num py-1.5 text-right", r.z !== null && r.z !== undefined && Math.abs(Number(r.z)) >= 2 && "font-semibold text-fg")}>{r.z === null || r.z === undefined ? DASH : num(r.z)}</td>
                      <td className="num py-1.5 text-right">{r.percentile ? `${Number(r.percentile).toFixed(0)}% of ${r.n}` : DASH}</td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {d.relative?.why && <p className="text-[13px] text-warn">{d.relative.why}</p>}
        <p className="mt-2 text-xs leading-4 text-fg-3">z = (value − universe mean) ÷ standard deviation; "at or above" is the share of members whose value is at or below this security's. {d.relative?.note} <Link to="/screener" className="text-info underline decoration-info/40 underline-offset-2 hover:decoration-info">Open the screener</Link></p>
      </Panel>

      <Panel title="Peer P/E history" titleId="ppe-title" className="lg:col-span-6">
        {!d.peer_valuation?.rows?.length ? <p className="text-[13px] text-fg-3">{(d.peer_valuation as { why?: string } | undefined)?.why ?? "No peers: choose some on the Peers tab."}</p> : (
          <table className="w-full text-[13px]">
            <caption className="sr-only">Five-year P/E range of {symbol} and its peers</caption>
            <thead><tr className="border-b border-line-subtle text-xs text-fg-3"><th scope="col" className="py-1.5 text-left font-medium">Instrument</th><th scope="col" className="py-1.5 text-right font-medium">Min</th><th scope="col" className="py-1.5 text-right font-medium">Median</th><th scope="col" className="py-1.5 text-right font-medium">Max</th><th scope="col" className="py-1.5 text-right font-medium">Latest</th></tr></thead>
            <tbody>
              {d.peer_valuation!.rows.map((r) => (
                <tr key={r.symbol} className="border-b border-line-subtle/60">
                  <th scope="row" className="py-1.5 text-left font-normal"><Link to={`/instrument/${encodeURIComponent(r.symbol)}?tab=risk`} className="num text-info underline decoration-info/40 underline-offset-2 hover:decoration-info">{r.symbol}</Link></th>
                  {!r.n ? <td colSpan={4} className="py-1.5 text-right text-xs text-fg-3">{r.why}</td> : (
                    <>
                      <td className="num py-1.5 text-right">{num(r.min, 1)}×</td>
                      <td className="num py-1.5 text-right">{num(r.median, 1)}×</td>
                      <td className="num py-1.5 text-right">{num(r.max, 1)}×</td>
                      <td className="num py-1.5 text-right">{r.current === null || r.current === undefined ? DASH : `${num(r.current, 1)}×`}{r.percentile !== null && r.percentile !== undefined && <span className="text-xs text-fg-3"> ({r.percentile.toFixed(0)}th)</span>}</td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="mt-2 text-xs text-fg-3">Daily P/E over five years from filed annual EPS (point in time by filing date); {d.peer_valuation?.source === "saved" ? "your saved peers" : "suggested peers"}.</p>
      </Panel>

      <Panel title="Short interest" titleId="si-title" className="lg:col-span-6">
        {!d.short_interest?.rows?.length ? (
          <p className="text-[13px] text-fg-3">{d.short_interest?.reason}</p>
        ) : (
          <>
            <div tabIndex={0} className="scroll-x scrollbar-thin overflow-x-auto">
              <table className="w-full text-[13px]" style={{ minWidth: 440 }}>
                <caption className="sr-only">Short interest by settlement date</caption>
                <thead><tr className="border-b border-line-subtle text-xs text-fg-3"><th scope="col" className="py-1.5 text-left font-medium">Settlement</th><th scope="col" className="py-1.5 text-right font-medium">Short position</th><th scope="col" className="py-1.5 text-right font-medium">Change</th><th scope="col" className="py-1.5 text-right font-medium">Days to cover</th></tr></thead>
                <tbody>
                  {d.short_interest.rows.map((r) => (
                    <tr key={r.settlement_date} className="border-b border-line-subtle/60">
                      <td className="num py-1.5">{formatSessionDate(r.settlement_date)}{r.revised && <Pill className="ml-1">revised</Pill>}</td>
                      <td className="num py-1.5 text-right">{formatCompact(r.short_position)}</td>
                      <td className={cn("num py-1.5 text-right", r.change_pct >= 0 ? "text-neg" : "text-pos")}>{formatPercent(r.change_pct)}</td>
                      <td className="num py-1.5 text-right">{num(r.days_to_cover)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-xs leading-4 text-fg-3">{d.short_interest.note} Source: FINRA (owner of the data){d.short_interest.fetched_at ? `, retrieved ${formatRelative(d.short_interest.fetched_at)}` : ""}. For personal use.</p>
          </>
        )}
      </Panel>
    </>
  );
}
