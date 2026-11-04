import { useState } from "react";
import { Link } from "react-router";
import { ArrowDown, ArrowUp, Minus } from "lucide-react";
import { Panel } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { EmptyState, ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { errorMessage } from "@/lib/api/client";
import { DASH, formatInstant, formatLargeMoney, formatPercent, toNumber } from "@/lib/format";
import { useHeatmap, type UniverseSpec } from "./api";
import { DatasetBar } from "./ScreenerPage";

const METRICS = [
  { value: "change_1d_pct", label: "1D" },
  { value: "return_1m_pct", label: "1M" },
  { value: "return_3m_pct", label: "3M" },
  { value: "return_1y_pct", label: "1Y" },
] as const;
type HeatMetric = (typeof METRICS)[number]["value"];

/** Tile background: green for gains, red for losses, stronger with magnitude (capped), neutral when missing. */
function tileStyle(v: string | null, metric: HeatMetric): React.CSSProperties {
  const n = toNumber(v);
  if (n === null) return {};
  const cap = metric === "change_1d_pct" ? 3 : metric === "return_1y_pct" ? 40 : 15;
  const pct = Math.round(12 + Math.min(1, Math.abs(n) / cap) * 38);
  const color = n > 0 ? "var(--positive)" : n < 0 ? "var(--negative)" : "var(--line)";
  return { background: `color-mix(in oklab, ${color} ${pct}%, var(--panel))` };
}

/** The tile colour already shows direction; the value keeps full contrast with a sign, arrow and word. */
function TileValue({ value }: { value: string }) {
  const n = toNumber(value) ?? 0;
  const Icon = n > 0 ? ArrowUp : n < 0 ? ArrowDown : Minus;
  return (
    <span className="num inline-flex items-center gap-1 font-semibold text-fg">
      <Icon aria-hidden className="size-4" strokeWidth={2.4} />
      <span className="sr-only">{n > 0 ? "up" : n < 0 ? "down" : "unchanged"} </span>
      {formatPercent(value)}
    </span>
  );
}

export function HeatmapView({ universe }: { universe: UniverseSpec }) {
  const [metric, setMetric] = useState<HeatMetric>("change_1d_pct");
  const [weighting, setWeighting] = useState<"equal" | "market_cap">("equal");
  const q = useHeatmap(universe, metric, weighting);
  const h = q.data;
  const label = METRICS.find((m) => m.value === metric)?.label;
  return (
    <Panel title="Sector heatmap" titleId="heat-title" className="lg:col-span-12" refreshing={q.isFetching && !q.isLoading} wrapHeader
      meta={h ? `${h.universe.label} · ${h.weighting === "market_cap" ? "market-cap weighted" : "equal weighted"}` : undefined}
      actions={
        <div className="flex flex-wrap gap-2">
          <Segmented label="Change period" value={metric} onChange={setMetric} options={METRICS.map((m) => ({ value: m.value, label: m.label }))} />
          <Segmented label="Weighting" value={weighting} onChange={setWeighting} options={[{ value: "equal", label: "Equal" }, { value: "market_cap", label: "Market cap" }]} />
        </div>
      }
    >
      {q.isLoading ? (
        <SkeletonRows rows={6} />
      ) : q.isError && !h ? (
        <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
      ) : h ? (
        <div className="space-y-3">
          <DatasetBar universe={universe} info={h.universe} dataset={h.dataset} />
          {h.notes.map((n) => <InlineNotice key={n} tone="warn">{n}</InlineNotice>)}
          {h.dataset.members === 0 ? (
            <EmptyState title="This universe has no members" actions={<Link to="/watchlists" className="text-[13px] text-accent-text hover:underline">Add symbols to a watchlist</Link>} />
          ) : h.dataset.loaded === 0 ? (
            <EmptyState title="No data loaded for this universe yet">Use “Load data” to fetch each member’s prices and fundamentals first.</EmptyState>
          ) : (
            <>
              <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6" aria-label={`Sectors by ${label} change`}>
                {h.sectors.map((s) => (
                  <li key={s.sector} className="min-h-24 rounded-[var(--radius-control)] border border-line-subtle p-2.5" style={tileStyle(s.value, metric)}>
                    <p className="truncate text-[13px] font-medium text-fg" title={s.sector}>{s.sector}</p>
                    <p className="mt-1 text-lg">
                      {s.value === null ? <span className="num text-fg-3">{DASH}</span> : <TileValue value={s.value} />}
                    </p>
                    <p className="mt-0.5 text-xs text-fg-2">
                      {s.used} of {s.members} with a value
                      {h.weighting === "market_cap" && s.weight_total_inr ? ` · ${formatLargeMoney(s.weight_total_inr, "INR")}` : ""}
                    </p>
                  </li>
                ))}
              </ul>
              <p className="text-xs leading-4 text-fg-3">
                {h.method} Members are those of the chosen universe only{h.universe.excluded.length ? `; ${h.universe.excluded.length} indices or currencies are left out` : ""}.
                {h.fx?.rate ? ` USD/INR ${Number(h.fx.rate).toFixed(4)} (${h.fx.status}${h.fx.market_time ? `, ${formatInstant(h.fx.market_time)}` : ""}) converts USD market caps for weighting only.` : ""}
              </p>
              <details className="text-[13px]">
                <summary className="cursor-pointer text-xs text-fg-2 hover:text-fg">Table of members</summary>
                <div className="scrollbar-thin mt-2 overflow-x-auto">
                  <table className="w-full text-[13px]">
                    <caption className="sr-only">Members by sector with their {label} change</caption>
                    <thead>
                      <tr className="border-b border-line-subtle text-xs text-fg-3">
                        <th scope="col" className="py-1.5 pr-3 text-left font-medium">Sector</th>
                        <th scope="col" className="py-1.5 pr-3 text-left font-medium">Instrument</th>
                        <th scope="col" className="py-1.5 pr-3 text-right font-medium">{label} change</th>
                        {h.weighting === "market_cap" && <th scope="col" className="py-1.5 text-right font-medium">Market cap (INR)</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {h.sectors.flatMap((s) =>
                        s.items.map((it) => (
                          <tr key={`${s.sector}-${it.symbol}`} className="border-b border-line-subtle/60">
                            <td className="py-1.5 pr-3 text-fg-2">{s.sector}</td>
                            <td className="py-1.5 pr-3">
                              <Link to={`/instrument/${encodeURIComponent(it.symbol)}`} className="num hover:text-accent-text">{it.symbol}</Link>
                              <span className="ml-2 text-xs text-fg-3">{it.name}</span>
                            </td>
                            <td className="num py-1.5 pr-3 text-right" title={it.value === null ? it.why ?? undefined : undefined}>
                              {it.value === null ? <span className="text-fg-3">{DASH}<span className="sr-only">: {it.why}</span></span> : formatPercent(it.value)}
                            </td>
                            {h.weighting === "market_cap" && <td className="num py-1.5 text-right">{formatLargeMoney(it.market_cap_inr, "INR")}</td>}
                          </tr>
                        )),
                      )}
                    </tbody>
                  </table>
                </div>
              </details>
            </>
          )}
        </div>
      ) : null}
    </Panel>
  );
}
