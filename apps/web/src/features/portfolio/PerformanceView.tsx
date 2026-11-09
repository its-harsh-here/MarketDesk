import { AreaSeries, ColorType, LineSeries, createChart } from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import { ChangeText } from "@/components/ui/Change";
import { Select } from "@/components/ui/Form";
import { Metric } from "@/components/ui/Metric";
import { Panel } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { EmptyState, ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { errorMessage } from "@/lib/api/client";
import { DASH, formatLargeMoney, formatMoney, formatNumber, formatPercent, formatSessionDate } from "@/lib/format";
import { cn } from "@/lib/cn";
import { useBenchmarks } from "@/features/market/api";
import { StressPanel } from "./StressPanel";
import { useCorrelations, useExposure, usePerformance, type Bucket, type Performance, type PerfAccount } from "./riskApi";

function cssColor(value: string) {
  const name = value.match(/var\((--[^)]+)\)/)?.[1];
  return name ? getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#A7B3C4" : value;
}

const pct = (v: string | null | undefined, signed = true) => (v === null || v === undefined ? DASH : formatPercent(v, { signed }));
/** Whole amounts below one crore (or one million in other currencies); compact above. */
const amount = (v: string, ccy: string) => (Math.abs(Number(v)) >= (ccy === "INR" ? 1e7 : 1e6) ? formatLargeMoney(v, ccy) : formatMoney(v, ccy, 0));

export function PerformanceView({ account }: { account: PerfAccount }) {
  const [benchmark, setBenchmark] = useState<string | null>(null);
  const q = usePerformance(account, benchmark);
  const benches = useBenchmarks();
  const p = q.data;
  const options = useMemo(() => {
    const set = new Set<string>((benches.data ?? []).map((b) => b.instrument.symbol));
    if (p?.benchmark?.symbol) set.add(p.benchmark.symbol);
    if (account === "USD") set.add("^GSPC");
    return [...set].filter((s) => !(s === "^GSPC" && (benches.data ?? []).some((b) => b.instrument.symbol.startsWith("SX:"))));
  }, [benches.data, p?.benchmark?.symbol, account]);

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-12 lg:gap-5">
      <Panel title="Performance" titleId="perf-title" className="lg:col-span-12" refreshing={q.isFetching && !q.isLoading} wrapHeader
        meta={p?.available ? `${formatSessionDate(p.start)} – ${formatSessionDate(p.end)} · ${p.currency} · ${p.observations} daily returns` : undefined}
        actions={
          options.length > 0 && p?.available ? (
            <label className="flex items-center gap-2 text-xs text-fg-3">
              Benchmark
              <Select className="h-8 w-36" value={benchmark ?? p.benchmark?.symbol ?? ""} onChange={(e) => setBenchmark(e.target.value)}>
                {options.map((s) => <option key={s} value={s}>{s}</option>)}
              </Select>
            </label>
          ) : undefined
        }
      >
        {q.isLoading ? (
          <SkeletonRows rows={6} />
        ) : q.isError ? (
          <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
        ) : !p?.available ? (
          <EmptyState title="No performance yet">{p?.reason}</EmptyState>
        ) : (
          <PerformanceBody p={p} />
        )}
      </Panel>
      <ExposurePanel account={account} />
      <CorrelationPanel account={account} benchmark={benchmark} />
      <StressPanel account={account} />
    </div>
  );
}

function PerformanceBody({ p }: { p: Performance }) {
  const m = p.metrics;
  const b = p.benchmark;
  const [table, setTable] = useState(false);
  return (
    <div className="space-y-4">
      {p.warnings.map((w) => <InlineNotice key={w} tone="warn">{w}</InlineNotice>)}
      {p.missing_history.length > 0 && <InlineNotice tone="warn">No price history for {p.missing_history.join(", ")}; days holding them are left out.</InlineNotice>}
      <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3 xl:grid-cols-6">
        <Metric label="Time-weighted return" value={<ChangeText percent={m.twr_pct} showAmount={false} />}
          caption={m.twr_annualized_pct ? `${pct(m.twr_annualized_pct)} a year` : "Not annualized (under a year)"}
          title="Your investment decisions, with the timing and size of deposits removed" />
        <Metric label="Money-weighted return" value={<ChangeText percent={m.mwr_annualized_pct ?? m.mwr_period_pct} showAmount={false} />}
          caption={m.mwr_annualized_pct ? "XIRR, a year" : "XIRR over the period"} title="Your actual experience, including when you added or withdrew money" />
        <Metric label="Volatility" value={pct(m.volatility_pct, false)} caption={m.volatility_pct ? "Annualized, daily returns" : "Needs 60 daily returns"} />
        <Metric label="Max drawdown" value={pct(m.max_drawdown.depth_pct)}
          caption={m.max_drawdown.peak ? `${formatSessionDate(m.max_drawdown.peak)} → ${formatSessionDate(m.max_drawdown.trough)} · ${m.max_drawdown.recovered ? `recovered ${formatSessionDate(m.max_drawdown.recovered)}` : "not yet recovered"}` : undefined} />
        <Metric label={b ? `Benchmark ${b.symbol}` : "Benchmark"} value={b ? <ChangeText percent={b.total_pct} showAmount={false} /> : DASH}
          caption={b?.excess_pct ? `Difference ${pct(b.excess_pct)} (time-weighted − benchmark)` : undefined} />
        <Metric label="Beta · correlation" value={b?.beta ? `${b.beta} · ${b.correlation}` : DASH}
          caption={b?.beta ? `${b.n} paired daily returns` : b?.beta_note ?? undefined} />
      </div>
      <p className="text-xs text-fg-3">
        Value {formatMoney(m.end_value, p.currency)} on {formatSessionDate(p.end)} · {m.flows_count} deposit/withdrawal flow{m.flows_count === 1 ? "" : "s"} netting {formatMoney(m.net_flows, p.currency)}
        {m.best_day && m.worst_day ? ` · best day ${pct(m.best_day.pct)} (${formatSessionDate(m.best_day.day)}), worst ${pct(m.worst_day.pct)} (${formatSessionDate(m.worst_day.day)})` : ""}
        {p.skipped.count ? ` · ${p.skipped.count} day(s) left out (${p.skipped.examples[0]})` : ""}
      </p>
      {b?.currency_note && <p className="text-xs text-warn">{b.currency_note}</p>}
      <div className="flex justify-end">
        <Segmented label="Chart or table" value={table ? "table" : "chart"} onChange={(v) => setTable(v === "table")} options={[{ value: "chart", label: "Chart" }, { value: "table", label: "Table" }]} />
      </div>
      {table ? <SeriesTable p={p} /> : <PerformanceCharts p={p} />}
      <details className="text-xs text-fg-3">
        <summary className="cursor-pointer text-fg-2 hover:text-fg">How these are calculated</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {[...p.policies, ...p.notes].map((x) => <li key={x}>{x}</li>)}
        </ul>
      </details>
    </div>
  );
}

function PerformanceCharts({ p }: { p: Performance }) {
  const top = useRef<HTMLDivElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!top.current || !bottom.current) return;
    const opts = {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: cssColor("var(--chart-text)"), fontFamily: "JetBrains Mono, ui-monospace, monospace", fontSize: 11, attributionLogo: true },
      grid: { vertLines: { color: cssColor("var(--chart-grid)") }, horzLines: { color: cssColor("var(--chart-grid)") } },
      rightPriceScale: { borderColor: cssColor("var(--border)") },
      timeScale: { borderColor: cssColor("var(--border)") },
    } as const;
    const c1 = createChart(top.current, { ...opts, localization: { priceFormatter: (v: number) => formatNumber(v, 1) } });
    const port = c1.addSeries(LineSeries, { color: cssColor("var(--chart-line)"), lineWidth: 2, priceLineVisible: false, title: "Portfolio" });
    port.setData(p.series.dates.map((d, i) => ({ time: d, value: p.series.index[i] })));
    if (p.benchmark) {
      const bl = c1.addSeries(LineSeries, { color: cssColor("var(--info)"), lineWidth: 1, priceLineVisible: false, title: p.benchmark.symbol });
      bl.setData(p.series.dates.flatMap((d, i) => (p.series.benchmark[i] === null ? [] : [{ time: d, value: p.series.benchmark[i] as number }])));
    }
    c1.timeScale().fitContent();
    const c2 = createChart(bottom.current, { ...opts, localization: { priceFormatter: (v: number) => `${formatNumber(v, 1)}%` } });
    const area = c2.addSeries(AreaSeries, {
      lineColor: cssColor("var(--negative)"),
      topColor: "rgba(255,113,133,0.05)",
      bottomColor: "rgba(255,113,133,0.30)",
      lineWidth: 1,
      priceLineVisible: false,
      invertFilledArea: true,
    });
    area.setData(p.series.dates.map((d, i) => ({ time: d, value: p.series.underwater[i] })));
    c2.timeScale().fitContent();
    // keep the two time scales in step
    const sync = (from: typeof c1, to: typeof c2) => from.timeScale().subscribeVisibleLogicalRangeChange((r) => r && to.timeScale().setVisibleLogicalRange(r));
    sync(c1, c2);
    sync(c2, c1);
    return () => {
      c1.remove();
      c2.remove();
    };
  }, [p]);
  const last = p.series.index[p.series.index.length - 1];
  const lastB = p.series.benchmark[p.series.benchmark.length - 1];
  return (
    <div className="space-y-2">
      <figure className="m-0" aria-label="Portfolio time-weighted index and benchmark, rebased to 100">
        <figcaption className="text-xs text-fg-3">
          Growth of 100 (time-weighted) · portfolio {formatNumber(last, 1)}{p.benchmark && lastB !== null ? ` · ${p.benchmark.symbol} ${formatNumber(lastB, 1)}` : ""}
          <span className="sr-only"> on {p.end}. The table view lists every day.</span>
        </figcaption>
        <div ref={top} className="h-[260px] w-full" />
      </figure>
      <figure className="m-0" aria-label="Drawdown from the previous peak, in percent">
        <figcaption className="text-xs text-fg-3">Drawdown from the previous peak (%) · now {pct(p.metrics.current_drawdown_pct)}</figcaption>
        <div ref={bottom} className="h-[120px] w-full" />
      </figure>
    </div>
  );
}

function SeriesTable({ p }: { p: Performance }) {
  const rows = p.series.dates.map((_, i) => i).reverse();
  return (
    <div tabIndex={0} className="scroll-x scrollbar-thin relative max-h-[380px] overflow-auto">
      <table className="w-full text-[13px]">
        <caption className="sr-only">Daily portfolio value, time-weighted index, benchmark and drawdown, newest first</caption>
        <thead className="sticky top-0 bg-panel">
          <tr className="border-b border-line-subtle text-xs text-fg-3">
            <th scope="col" className="px-2 py-1.5 text-left font-medium">Date</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">Value ({p.currency})</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">Index</th>
            {p.benchmark && <th scope="col" className="px-2 py-1.5 text-right font-medium">{p.benchmark.symbol}</th>}
            <th scope="col" className="px-2 py-1.5 text-right font-medium">Drawdown</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((i) => (
            <tr key={p.series.dates[i]} className="border-b border-line-subtle/60">
              <td className="num px-2 py-1 text-fg-2">{formatSessionDate(p.series.dates[i])}</td>
              <td className="num px-2 py-1 text-right">{formatMoney(p.series.value[i], p.currency)}</td>
              <td className="num px-2 py-1 text-right">{formatNumber(p.series.index[i], 2)}</td>
              {p.benchmark && <td className="num px-2 py-1 text-right">{p.series.benchmark[i] === null ? DASH : formatNumber(p.series.benchmark[i] as number, 2)}</td>}
              <td className="num px-2 py-1 text-right">{formatPercent(p.series.underwater[i])}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const DIMENSIONS = [
  { value: "by_holding", label: "Holding" },
  { value: "by_sector", label: "Sector" },
  { value: "by_country", label: "Market" },
  { value: "by_currency", label: "Currency" },
] as const;
type Dim = (typeof DIMENSIONS)[number]["value"];

function ExposurePanel({ account }: { account: PerfAccount }) {
  const q = useExposure(account);
  const [dim, setDim] = useState<Dim>("by_holding");
  const x = q.data;
  const rows: Bucket[] = x?.available ? x[dim] : [];
  return (
    <Panel title="Exposure and concentration" titleId="exp-title" className="lg:col-span-6" wrapHeader
      actions={<Segmented label="Group exposure by" value={dim} onChange={setDim} options={DIMENSIONS.map((d) => ({ value: d.value, label: d.label }))} />}>
      {q.isLoading ? (
        <SkeletonRows rows={5} />
      ) : q.isError ? (
        <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
      ) : !x?.available ? (
        <EmptyState title="No exposure yet">{x?.reason}</EmptyState>
      ) : (
        <div className="space-y-3">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-[13px] sm:grid-cols-4">
            <div><dt className="text-xs text-fg-3">Largest holding</dt><dd className="num">{pct(x.concentration.largest_pct, false)}</dd></div>
            <div><dt className="text-xs text-fg-3">Top five</dt><dd className="num">{pct(x.concentration.top5_pct, false)}</dd></div>
            <div title={x.concentration.formula}><dt className="text-xs text-fg-3">Effective holdings</dt><dd className="num">{x.concentration.effective_holdings ?? DASH}</dd></div>
            <div><dt className="text-xs text-fg-3">Cash</dt><dd className="num">{pct(x.cash_pct, false)}</dd></div>
          </dl>
          <table className="w-full text-[13px]">
            <caption className="sr-only">Exposure by {DIMENSIONS.find((d) => d.value === dim)?.label.toLowerCase()}, share of invested value</caption>
            <thead>
              <tr className="border-b border-line-subtle text-xs text-fg-3">
                <th scope="col" className="py-1.5 text-left font-medium">{DIMENSIONS.find((d) => d.value === dim)?.label}</th>
                <th scope="col" className="py-1.5 text-right font-medium">Value ({x.currency})</th>
                <th scope="col" className="w-2/5 py-1.5 pl-3 text-left font-medium">Share of invested</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.name} className="border-b border-line-subtle/60">
                  <td className="num py-1.5 pr-2">{r.name}</td>
                  <td className="num py-1.5 text-right">{amount(r.value, x.currency)}</td>
                  <td className="py-1.5 pl-3">
                    <div className="flex items-center gap-2">
                      <div className="h-2 flex-1 rounded-full bg-line-subtle" aria-hidden>
                        <div className="h-2 rounded-full bg-accent" style={{ width: `${Math.min(100, Number(r.pct_of_invested ?? 0))}%` }} />
                      </div>
                      <span className="num w-14 text-right text-xs">{pct(r.pct_of_invested, false)}</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {x.unpriced.length > 0 && <p className="text-xs text-warn">Not included (no usable mark): {x.unpriced.join(", ")}.</p>}
          <p className="text-xs leading-4 text-fg-3">{x.note} {x.concentration.formula}</p>
        </div>
      )}
    </Panel>
  );
}

function corrStyle(r: string | null): React.CSSProperties {
  if (r === null) return {};
  const v = Number(r);
  const pctMix = Math.round(Math.abs(v) * 45);
  return { background: `color-mix(in oklab, ${v >= 0 ? "var(--info)" : "var(--accent)"} ${pctMix}%, var(--panel))` };
}

function CorrelationPanel({ account, benchmark }: { account: PerfAccount; benchmark: string | null }) {
  const q = useCorrelations(account, benchmark);
  const c = q.data;
  return (
    <Panel title="Correlation" titleId="corr-title" className="lg:col-span-6" meta={c?.available ? c.window : undefined}>
      {q.isLoading ? (
        <SkeletonRows rows={5} />
      ) : q.isError ? (
        <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
      ) : !c?.available ? (
        <EmptyState title="No correlations yet">{c?.reason}</EmptyState>
      ) : (
        <div className="space-y-3">
          <div tabIndex={0} className="scroll-x scrollbar-thin relative overflow-x-auto">
            <table className="text-[12px]">
              <caption className="sr-only">Pairwise correlation of returns; each cell lists r, the number of aligned returns and the method</caption>
              <thead>
                <tr>
                  <th scope="col" className="sr-only">Instrument</th>
                  {c.symbols.map((s) => <th key={s} scope="col" className="num max-w-20 truncate px-1.5 py-1 text-right font-medium text-fg-3" title={s}>{s}</th>)}
                </tr>
              </thead>
              <tbody>
                {c.symbols.map((a, i) => (
                  <tr key={a}>
                    <th scope="row" className="num max-w-28 truncate py-1 pr-2 text-left font-medium text-fg-2" title={a}>{a}{a === c.benchmark ? " (benchmark)" : ""}</th>
                    {c.matrix[i].map((cell, j) => (
                      <td key={c.symbols[j]} className={cn("num min-w-14 px-1.5 py-1 text-right", cell.r === null && "text-fg-3")} style={i === j ? undefined : corrStyle(cell.r)}
                        title={cell.method === "same" ? undefined : `${cell.method} returns, n = ${cell.n}${cell.why ? ` · ${cell.why}` : ""}`}>
                        {i === j ? <span className="text-fg-3">1</span> : cell.r ?? DASH}
                        {i !== j && <span className="sr-only"> ({cell.method}, {cell.n} returns{cell.why ? `; ${cell.why}` : ""})</span>}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {c.missing.length > 0 && <p className="text-xs text-warn">No one-year history for {c.missing.join(", ")}.</p>}
          {c.truncated > 0 && <p className="text-xs text-fg-3">Showing the first 12 holdings; {c.truncated} more not shown.</p>}
          <p className="text-xs leading-4 text-fg-3">{c.method} Hover a cell for the method and sample size.</p>
        </div>
      )}
    </Panel>
  );
}
