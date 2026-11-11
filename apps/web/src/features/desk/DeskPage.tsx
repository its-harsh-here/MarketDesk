import { ExternalLink, RotateCcw } from "lucide-react";
import { Field } from "@/components/ui/Form";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";
import { ChangeText } from "@/components/ui/Change";
import { FreshnessBadge } from "@/components/ui/Badges";
import { Panel } from "@/components/ui/Panel";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/States";
import { errorMessage } from "@/lib/api/client";
import { formatMoney, formatRelative, formatSessionDate } from "@/lib/format";
import { readRecents } from "@/lib/recent";
import { ChartPanel } from "@/features/market/ChartPanel";
import { useSnapshots } from "@/features/market/api";
import { SymbolPicker } from "@/features/search/SymbolPicker";
import { EarningsHistoryPanel, EventRow, useSecurityEvents } from "@/features/terminal/EventsTab";
import { useNewsStream } from "@/features/terminal/NewsTab";
import { PerformancePanel } from "@/features/terminal/PerformancePanel";

type Module = "chart" | "news" | "performance" | "events" | "earnings";
const MODULES: { value: Module; label: string }[] = [
  { value: "chart", label: "Price chart" },
  { value: "news", label: "News and filings" },
  { value: "performance", label: "Performance" },
  { value: "events", label: "Upcoming and recent events" },
  { value: "earnings", label: "Earnings history" },
];
const DEFAULT: Module[] = ["chart", "news", "performance", "events"];
const KEY = "md-desk-slots";

function readSlots(): Module[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "null");
    if (Array.isArray(v) && v.length === 4 && v.every((m) => MODULES.some((x) => x.value === m))) return v;
  } catch {
    /* per-browser layout only */
  }
  return DEFAULT;
}

function NewsModule({ symbol, className }: { symbol: string; className: string }) {
  const q = useNewsStream(symbol);
  const items = (q.data?.items ?? []).slice(0, 12);
  return (
    <Panel title="News and filings" titleId="desk-news" className={className} refreshing={q.isFetching && !q.isLoading}
      actions={<Link to={`/instrument/${encodeURIComponent(symbol)}?tab=news`} className="text-xs text-fg-2 hover:text-fg">All</Link>}>
      {q.isLoading ? <SkeletonRows rows={8} /> : q.isError ? <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} /> : !items.length ? (
        <EmptyState title="Nothing in the stream">{q.data?.notes[0] ?? "No headlines or filings from the available sources."}</EmptyState>
      ) : (
        <ul className="divide-y divide-line-subtle text-[13px]" aria-label={`Latest news and filings for ${symbol}`}>
          {items.map((it, i) => (
            <li key={`${it.url ?? it.headline}${i}`} className="py-1.5">
              {it.url ? (
                <a href={it.url} target="_blank" rel="noopener noreferrer" className="text-fg hover:text-accent-text">
                  {it.headline} <ExternalLink className="inline size-3 opacity-60" aria-hidden />
                </a>
              ) : <span className="text-fg">{it.headline}</span>}
              <div className="text-xs text-fg-3">
                {it.publisher ?? "unknown publisher"} · {it.at ? (it.precision === "date" ? formatSessionDate(it.at) : formatRelative(it.at)) : "undated"}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function EventsModule({ symbol, className }: { symbol: string; className: string }) {
  const q = useSecurityEvents(symbol);
  const d = q.data;
  const rows = d ? [...d.upcoming.slice(0, 4), ...d.past.slice(0, 8)] : [];
  return (
    <Panel title="Events" titleId="desk-events" className={className} refreshing={q.isFetching && !q.isLoading}
      actions={<Link to={`/instrument/${encodeURIComponent(symbol)}?tab=events`} className="text-xs text-fg-2 hover:text-fg">All</Link>}>
      {q.isLoading ? <SkeletonRows rows={6} /> : q.isError || !d ? <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} /> : !rows.length ? (
        <EmptyState title="No dated events">{d.notes[0] ?? "The available sources report no events."}</EmptyState>
      ) : (
        <ul className="divide-y divide-line-subtle">{rows.map((e, i) => <EventRow key={`${e.date}${e.kind}${i}`} e={e} today={d.as_of} />)}</ul>
      )}
    </Panel>
  );
}

/** Terminal T9: one symbol drives four panels; each slot's module is chosen here and remembered in this browser. */
export function DeskPage() {
  const [params, setParams] = useSearchParams();
  const fallback = useMemo(() => readRecents()[0]?.symbol ?? "", []);
  const symbol = params.get("s") ?? fallback;
  const [slots, setSlots] = useState<Module[]>(readSlots);
  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(slots));
    } catch {
      /* per-browser layout only */
    }
  }, [slots]);
  const snap = useSnapshots(symbol ? [symbol] : []).data?.[0];
  const currency = snap?.instrument.currency ?? null;
  const setSymbol = (s: string) => setParams((p) => { const n = new URLSearchParams(p); if (s) n.set("s", s); else n.delete("s"); return n; }, { replace: true });

  const render = (m: Module, i: number): ReactNode => {
    const cls = "min-h-[22rem]";
    if (!symbol) return null;
    switch (m) {
      case "chart":
        return <ChartPanel key={`${symbol}-${i}`} symbol={symbol} currency={currency} title={`${symbol} price`} height={300} className={cls} />;
      case "news":
        return <NewsModule symbol={symbol} className={cls} />;
      case "performance":
        return <PerformancePanel symbol={symbol} currency={currency} className={cls} />;
      case "events":
        return <EventsModule symbol={symbol} className={cls} />;
      case "earnings":
        return <EarningsHistoryPanel symbol={symbol} className={cls} />;
    }
  };

  return (
    <div className="space-y-4 p-4 md:p-6">
      <section aria-label="Desk symbol and layout" className="flex flex-wrap items-end gap-3">
        <Field label="Linked symbol (drives every panel)" className="w-72">
          {({ id }) => <SymbolPicker id={id} value={symbol} onChange={(s) => setSymbol(s)} placeholder="Search name or symbol" />}
        </Field>
        {snap?.quote && (
          <div className="flex items-baseline gap-3">
            <span className="num text-xl font-semibold text-fg">{formatMoney(snap.quote.last_price, currency)}</span>
            <ChangeText value={snap.quote.change} percent={snap.quote.change_percent} currency={currency} />
            <FreshnessBadge meta={snap.meta} />
            <Link to={`/instrument/${encodeURIComponent(symbol)}`} className="text-xs text-info underline decoration-info/40 underline-offset-2">Open instrument</Link>
          </div>
        )}
        <button type="button" className="ml-auto inline-flex h-9 items-center gap-1.5 rounded-[var(--radius-control)] border border-line-subtle px-3 text-xs text-fg-2 hover:text-fg"
          onClick={() => setSlots(DEFAULT)}>
          <RotateCcw className="size-3.5" aria-hidden /> Default layout
        </button>
      </section>
      {!symbol ? (
        <EmptyState title="Pick a symbol">Choose a listing above; every panel below follows it. Recently viewed instruments are offered first next time.</EmptyState>
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 xl:gap-5">
          {slots.map((m, i) => (
            <div key={i} className="flex min-w-0 flex-col gap-1.5">
              <label className="flex items-center gap-2 text-xs text-fg-3">
                <span>Panel {i + 1}</span>
                <select aria-label={`Panel ${i + 1} shows`} value={m} onChange={(e) => setSlots((cur) => cur.map((x, j) => (j === i ? (e.target.value as Module) : x)))}
                  className="h-7 rounded-[var(--radius-control)] border border-line bg-panel px-1.5 text-xs text-fg">
                  {MODULES.map((x) => <option key={x.value} value={x.value} disabled={x.value !== m && slots.includes(x.value)}>{x.label}{x.value !== m && slots.includes(x.value) ? " (in use)" : ""}</option>)}
                </select>
              </label>
              {render(m, i)}
            </div>
          ))}
        </div>
      )}
      <p className="text-xs text-fg-3">The layout is remembered in this browser. Every panel reads the same sources as the instrument page.</p>
    </div>
  );
}
