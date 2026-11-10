import * as DM from "@radix-ui/react-dropdown-menu";
import { Check, ChartCandlestick, ChartColumn, ChartLine, Download, RotateCcw, Sigma, Table2 } from "lucide-react";
import { useId, useMemo, useState, type ReactNode } from "react";
import { Panel } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { IconButton } from "@/components/ui/Button";
import { ErrorState, EmptyState, InlineNotice, Skeleton } from "@/components/ui/States";
import { FreshnessBadge } from "@/components/ui/Badges";
import { errorMessage } from "@/lib/api/client";
import { formatMoney, formatNumber, formatSessionDate, formatVolume } from "@/lib/format";
import { useMediaQuery } from "@/lib/hooks";
import { INDICATORS, type IndicatorKey } from "@/lib/indicators";
import { RANGES, useHistory, type Range } from "./api";
import { PriceChart, cleanBars, summarizeBars, type ChartKind } from "./PriceChart";

/** Daily bars as CSV (session, OHLC, volume). Cells are numbers or ISO dates only, so no formula can be injected. */
function downloadBars(symbol: string, range: string, bars: { time: string; open: number | null; high: number | null; low: number | null; close: number; volume: number | null }[]) {
  const rows = [["session", "open", "high", "low", "close", "volume"], ...bars.map((b) => [b.time, b.open ?? "", b.high ?? "", b.low ?? "", b.close, b.volume ?? ""])];
  const blob = new Blob([rows.map((r) => r.join(",")).join("\n") + "\n"], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${symbol.replace(/[^A-Za-z0-9.^-]/g, "_")}_${range}_daily.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

export function ChartPanel({
  symbol,
  currency,
  title,
  headerExtra,
  height = 360,
  className,
  defaultRange = "6M",
}: {
  symbol: string;
  currency: string | null | undefined;
  title: ReactNode;
  headerExtra?: ReactNode;
  height?: number;
  className?: string;
  defaultRange?: Range;
}) {
  const [range, setRange] = useState<Range>(defaultRange);
  const [kind, setKind] = useState<ChartKind>("line");
  const [volume, setVolume] = useState(true);
  const [table, setTable] = useState(false);
  const [reset, setReset] = useState(0);
  const [indicators, setIndicators] = useState<IndicatorKey[]>(() => {
    try {
      return JSON.parse(localStorage.getItem("md-indicators") ?? "[]").filter((k: string) => INDICATORS.some((i) => i.key === k));
    } catch {
      return [];
    }
  });
  const toggleIndicator = (k: IndicatorKey) =>
    setIndicators((cur) => {
      const next = cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k];
      try {
        localStorage.setItem("md-indicators", JSON.stringify(next));
      } catch {
        /* per-browser convenience only */
      }
      return next;
    });
  const titleId = useId();
  const phone = useMediaQuery("(max-width: 639px)");
  const chartHeight = phone ? Math.min(height, 280) : height;
  const q = useHistory(symbol, range);
  const supported = (q.data?.supported_ranges ?? RANGES) as Range[];
  const clean = useMemo(() => cleanBars(q.data?.bars ?? []), [q.data]);
  const summary = useMemo(() => summarizeBars(clean.bars, currency), [clean.bars, currency]);
  const hasVolume = clean.bars.some((b) => b.volume !== null);

  return (
    <Panel
      title={title}
      titleId={titleId}
      className={className}
      refreshing={q.isFetching && !q.isLoading}
      wrapHeader
      meta={
        q.data ? (
          <span className="inline-flex items-center gap-2">
            <FreshnessBadge meta={q.data.meta} />
            {clean.bars.length > 0 && (
              <span className="max-sm:hidden">
                {formatSessionDate(clean.bars[0].time)} – {formatSessionDate(clean.bars[clean.bars.length - 1].time)} · daily
              </span>
            )}
          </span>
        ) : null
      }
      actions={headerExtra}
      bodyClassName="flex flex-col p-0"
    >
      <div className="flex flex-wrap items-center gap-2 border-b border-line-subtle px-[var(--panel-pad)] py-2">
        <Segmented
          label="Chart range"
          value={range}
          onChange={setRange}
          options={RANGES.map((r) => ({ value: r, label: r, disabled: !supported.includes(r), title: supported.includes(r) ? undefined : "Not supported by the provider" }))}
        />
        <Segmented
          label="Chart type"
          value={kind}
          onChange={setKind}
          options={[
            { value: "line", label: <><ChartLine className="size-3.5" aria-hidden /><span>Line</span></> },
            {
              value: "candle",
              label: <><ChartCandlestick className="size-3.5" aria-hidden /><span>Candles</span></>,
              disabled: clean.bars.length > 0 && clean.candleGaps === clean.bars.length,
              title: clean.candleGaps === clean.bars.length && clean.bars.length > 0 ? "Open/high/low not available" : undefined,
            },
          ]}
        />
        <div className="ml-auto flex items-center gap-1">
          <DM.Root>
            <DM.Trigger asChild>
              <button type="button" disabled={table} className="md-btn inline-flex h-8 items-center gap-1.5 rounded-[var(--radius-control)] border border-line-subtle px-2.5 text-xs text-fg-2 hover:text-fg disabled:opacity-40">
                <Sigma className="size-3.5" aria-hidden />
                Indicators{indicators.length ? <span className="num rounded-full bg-accent-soft px-1.5 text-accent-text">{indicators.length}</span> : null}
              </button>
            </DM.Trigger>
            <DM.Portal>
              <DM.Content align="end" sideOffset={6} className="anim-pop z-50 w-72 rounded-[var(--radius-control)] border border-line bg-elevated p-1">
                {INDICATORS.map((ind) => (
                  <DM.CheckboxItem key={ind.key} checked={indicators.includes(ind.key)} onSelect={(e) => { e.preventDefault(); toggleIndicator(ind.key); }}
                    className="flex cursor-pointer items-start gap-2 rounded-md px-2.5 py-1.5 text-[13px] text-fg-2 outline-none data-[highlighted]:bg-hover data-[highlighted]:text-fg">
                    <span className="mt-0.5 flex size-4 shrink-0 items-center justify-center rounded border border-line">
                      <DM.ItemIndicator><Check className="size-3 text-accent-text" aria-hidden /></DM.ItemIndicator>
                    </span>
                    <span>
                      <span className="block text-fg">{ind.label}</span>
                      <span className="block text-xs text-fg-3">{ind.help}</span>
                    </span>
                  </DM.CheckboxItem>
                ))}
                {indicators.length > 0 && (
                  <DM.Item onSelect={() => { setIndicators([]); try { localStorage.setItem("md-indicators", "[]"); } catch { /* ignore */ } }}
                    className="mt-1 cursor-pointer rounded-md border-t border-line-subtle px-2.5 py-1.5 text-xs text-fg-3 outline-none data-[highlighted]:bg-hover">
                    Clear indicators
                  </DM.Item>
                )}
              </DM.Content>
            </DM.Portal>
          </DM.Root>
          {table && (
            <IconButton size="sm" label="Download these prices as CSV" disabled={!clean.bars.length} onClick={() => downloadBars(symbol, range, clean.bars)}>
              <Download className="size-4" aria-hidden />
            </IconButton>
          )}
          <IconButton
            size="sm"
            label={volume ? "Hide volume" : "Show volume"}
            aria-pressed={volume}
            active={volume && hasVolume}
            disabled={!hasVolume}
            title={hasVolume ? undefined : "Volume is not reported for this instrument"}
            onClick={() => setVolume((v) => !v)}
          >
            <ChartColumn className="size-4" aria-hidden />
          </IconButton>
          <IconButton size="sm" label="Reset zoom" onClick={() => setReset((n) => n + 1)} disabled={table || !clean.bars.length}>
            <RotateCcw className="size-4" aria-hidden />
          </IconButton>
          <IconButton size="sm" label={table ? "Show chart" : "Show data table"} aria-pressed={table} active={table} onClick={() => setTable((t) => !t)}>
            <Table2 className="size-4" aria-hidden />
          </IconButton>
        </div>
      </div>
      <figure aria-labelledby={titleId} aria-describedby={`${titleId}-sum`} className="m-0 flex min-h-0 flex-1 flex-col">
        <figcaption id={`${titleId}-sum`} className="sr-only">
          {summary} {q.data?.adjustment}
        </figcaption>
        {q.isLoading ? (
          <div className="p-[var(--panel-pad)]" style={{ height: chartHeight }}>
            <Skeleton className="h-full w-full" />
          </div>
        ) : q.isError ? (
          <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
        ) : !clean.bars.length ? (
          <EmptyState title="No price history" className="py-16">
            {q.data?.meta.message ?? "The provider returned no daily bars for this range."}
          </EmptyState>
        ) : table ? (
          <div className="scrollbar-thin relative overflow-auto" style={{ height: chartHeight }}>
            <table className="w-full text-[13px]">
              <caption className="sr-only">Daily prices for {symbol}</caption>
              <thead className="sticky top-0 bg-panel">
                <tr className="border-b border-line-subtle text-xs text-fg-3">
                  {["Session", "Open", "High", "Low", "Close", "Volume"].map((h, i) => (
                    <th key={h} scope="col" className={i === 0 ? "px-4 py-2 text-left font-medium" : "px-3 py-2 text-right font-medium"}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...clean.bars].reverse().map((b) => (
                  <tr key={b.time} className="border-b border-line-subtle">
                    <td className="num px-4 py-1.5 text-fg-2">{formatSessionDate(b.time)}</td>
                    <td className="num px-3 text-right">{formatNumber(b.open)}</td>
                    <td className="num px-3 text-right">{formatNumber(b.high)}</td>
                    <td className="num px-3 text-right">{formatNumber(b.low)}</td>
                    <td className="num px-3 text-right text-fg">{formatMoney(b.close, currency)}</td>
                    <td className="num px-3 pr-4 text-right text-fg-2">{formatVolume(b.volume)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <PriceChart bars={clean.bars} kind={kind} showVolume={volume && hasVolume} currency={currency} height={chartHeight + indicators.filter((k) => k === "rsi" || k === "macd").length * Math.round(chartHeight * 0.25)} resetSignal={reset} indicators={indicators} className="mx-1 my-2 flex-1" />
        )}
      </figure>
      {(q.data?.adjustment || clean.dropped > 0 || q.data?.meta.status === "stale") && (
        <div className="space-y-2 border-t border-line-subtle px-[var(--panel-pad)] py-2 text-xs text-fg-3">
          {q.data?.meta.status === "stale" && <InlineNotice tone="warn">{q.data.meta.message}</InlineNotice>}
          <p>
            {q.data?.adjustment}
            {clean.dropped > 0 && ` ${clean.dropped} invalid or duplicate bar(s) were excluded.`}
            {kind === "candle" && clean.candleGaps > 0 && ` ${clean.candleGaps} session(s) lack open/high/low and are not drawn as candles.`}
          </p>
        </div>
      )}
    </Panel>
  );
}
