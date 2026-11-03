import { ColorType, LineSeries, createChart, type IChartApi } from "lightweight-charts";
import { Table2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Panel } from "@/components/ui/Panel";
import { IconButton } from "@/components/ui/Button";
import { Segmented } from "@/components/ui/Segmented";
import { ErrorState, InlineNotice, Skeleton } from "@/components/ui/States";
import { errorMessage } from "@/lib/api/client";
import { formatNumber, formatSessionDate } from "@/lib/format";
import { cn } from "@/lib/cn";
import { SymbolPicker } from "@/features/search/SymbolPicker";
import { RANGES, useCompare, type Range } from "./api";

const MAX_OTHERS = 2;
// Neutral, non-semantic series colours (gain/loss colours are reserved for signs of change).
const COLORS = ["var(--chart-line)", "var(--info)", "var(--fg-2)"];

function cssColor(value: string) {
  const name = value.match(/var\((--[^)]+)\)/)?.[1];
  return name ? getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#A7B3C4" : value;
}

/**
 * Normalized comparison of up to three instruments. The server aligns the series on dates where every instrument
 * traded and rebases each to 100; this panel only draws what it returns and states the method.
 */
export function ComparePanel({ symbol, className }: { symbol: string; className?: string }) {
  const [others, setOthers] = useState<string[]>([]);
  const [range, setRange] = useState<Range>("1Y");
  const [pickerKey, setPickerKey] = useState(0); // remounting the picker clears it after each addition
  const [table, setTable] = useState(false);
  const symbols = useMemo(() => [symbol, ...others.filter((o) => o !== symbol)], [symbol, others]);
  const q = useCompare(symbols, range);
  const data = q.data;

  return (
    <Panel title="Compare" titleId="cmp-title" className={className} refreshing={q.isFetching && !q.isLoading} bodyClassName="flex flex-col gap-3 p-[var(--panel-pad)]">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-wrap items-center gap-2" aria-label="Compared instruments">
          {symbols.map((s, i) => (
            <span key={s} className="inline-flex items-center gap-1.5 rounded-[var(--radius-control)] border border-line px-2 py-1 text-[13px]">
              <span aria-hidden className="h-0.5 w-3 rounded" style={{ background: COLORS[i] }} />
              <span className="num">{s}</span>
              {i > 0 && (
                <button type="button" className="text-fg-3 hover:text-fg" aria-label={`Remove ${s} from the comparison`} onClick={() => setOthers((o) => o.filter((x) => x !== s))}>
                  <X className="size-3.5" aria-hidden />
                </button>
              )}
            </span>
          ))}
        </div>
        {others.length < MAX_OTHERS ? (
          <div className="w-full min-w-0 sm:w-72">
            <label htmlFor="cmp-add" className="mb-1 block text-xs text-fg-3">
              Add an instrument (up to {MAX_OTHERS + 1} in total)
            </label>
            <SymbolPicker
              key={pickerKey}
              id="cmp-add"
              value=""
              placeholder="Name or symbol"
              onChange={(sym) => {
                if (!sym) return;
                if (sym !== symbol && !others.includes(sym)) setOthers((o) => [...o, sym].slice(0, MAX_OTHERS));
                setPickerKey((k) => k + 1);
              }}
            />
          </div>
        ) : (
          <p className="text-xs text-fg-3">Up to three instruments can be compared; remove one to add another.</p>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Segmented label="Comparison range" value={range} onChange={setRange} options={RANGES.map((r) => ({ value: r, label: r }))} />
          <IconButton size="sm" label={table ? "Show comparison chart" : "Show comparison table"} aria-pressed={table} active={table} onClick={() => setTable((t) => !t)} disabled={!data?.complete}>
            <Table2 className="size-4" aria-hidden />
          </IconButton>
        </div>
      </div>

      {symbols.length < 2 ? (
        <p className="text-[13px] text-fg-3">Add one or two instruments to compare their price paths on a common base of 100.</p>
      ) : q.isLoading ? (
        <Skeleton className="h-[260px] w-full" />
      ) : q.isError && !data ? (
        <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
      ) : data && !data.complete ? (
        <InlineNotice tone="warn">
          A comparison needs at least two dates on which every instrument has a daily close.{" "}
          {data.instruments
            .filter((i) => i.bars === 0)
            .map((i) => `${i.symbol}: ${i.meta.message ?? "no price history"}`)
            .join(" ")}
        </InlineNotice>
      ) : data ? (
        <>
          {table ? <CompareTable dates={data.dates} series={data.series} symbols={symbols} /> : <CompareChart dates={data.dates} series={data.series} symbols={symbols} />}
          <div className="space-y-1 text-xs leading-4 text-fg-3">
            <p>
              Base 100 on {formatSessionDate(data.base_date)}. {data.method}
            </p>
            {data.instruments.some((i) => (i.excluded_dates ?? 0) > 0) && (
              <p>
                Dates left out because another instrument had no bar that day (different holidays):{" "}
                {data.instruments.map((i) => `${i.symbol} ${i.excluded_dates ?? 0}`).join(", ")}.
              </p>
            )}
            {data.currencies_differ && (
              <p className="text-warn">
                These instruments trade in different currencies ({data.instruments.map((i) => `${i.symbol} ${i.currency ?? "?"}`).join(", ")}); each line is its own-currency price path, with no currency conversion.
              </p>
            )}
          </div>
        </>
      ) : null}
    </Panel>
  );
}

function CompareChart({ dates, series, symbols }: { dates: string[]; series: Record<string, string[]>; symbols: string[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: cssColor("var(--chart-text)"), fontFamily: "JetBrains Mono, ui-monospace, monospace", fontSize: 11, attributionLogo: true },
      grid: { vertLines: { color: cssColor("var(--chart-grid)") }, horzLines: { color: cssColor("var(--chart-grid)") } },
      rightPriceScale: { borderColor: cssColor("var(--border)") },
      timeScale: { borderColor: cssColor("var(--border)") },
      localization: { priceFormatter: (v: number) => formatNumber(v, 1) },
    });
    chartRef.current = chart;
    symbols.forEach((s, i) => {
      const line = chart.addSeries(LineSeries, { color: cssColor(COLORS[i]), lineWidth: 2, priceLineVisible: false, title: s });
      line.setData(dates.map((d, k) => ({ time: d, value: Number(series[s]?.[k]) })));
    });
    chart.timeScale().fitContent();
    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [dates, series, symbols]);
  return (
    <figure className="m-0" aria-label={`Comparison of ${symbols.join(", ")}, rebased to 100`}>
      <figcaption className="sr-only">
        Rebased to 100 on {dates[0]}. Final values: {symbols.map((s) => `${s} ${series[s]?.[series[s].length - 1] ?? "unavailable"}`).join(", ")}. A table view is available.
      </figcaption>
      <div ref={ref} className="h-[260px] w-full" />
    </figure>
  );
}

function CompareTable({ dates, series, symbols }: { dates: string[]; series: Record<string, string[]>; symbols: string[] }) {
  const rows = dates.map((d, k) => ({ d, k })).reverse();
  return (
    <div className="scrollbar-thin relative max-h-[260px] overflow-auto">
      <table className="w-full text-[13px]">
        <caption className="sr-only">Comparison values rebased to 100, newest first</caption>
        <thead className="sticky top-0 bg-panel">
          <tr className="border-b border-line-subtle text-xs text-fg-3">
            <th scope="col" className="px-2 py-1.5 text-left font-medium">Date</th>
            {symbols.map((s) => (
              <th key={s} scope="col" className="num px-2 py-1.5 text-right font-medium">{s}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(({ d, k }) => (
            <tr key={d} className="border-b border-line-subtle/60">
              <td className="num px-2 py-1 text-fg-2">{formatSessionDate(d)}</td>
              {symbols.map((s) => (
                <td key={s} className={cn("num px-2 py-1 text-right")}>{series[s]?.[k] ? formatNumber(Number(series[s][k]), 2) : "—"}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
