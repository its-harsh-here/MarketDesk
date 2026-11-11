import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { Pill } from "@/components/ui/Badges";
import { Panel } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { EmptyState, ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { api, errorMessage } from "@/lib/api/client";
import { cn } from "@/lib/cn";
import { DASH, formatLargeMoney, formatMoney, formatPercent, formatRelative, formatSessionDate } from "@/lib/format";
import { useWatchlists } from "@/features/watchlists/api";

/* ------------------------------------------------------------------ types (GET /api/terminal/events*) */
export type EventKind = "results" | "dividend" | "split" | "report" | "proxy" | "meeting" | "buyback";
export type EventStatus = "confirmed" | "estimated" | "deadline" | "mention";
export interface SecurityEvent {
  date: string;
  kind: EventKind;
  label: string;
  status: EventStatus;
  source: string;
  symbol?: string;
  url?: string | null;
  value?: string;
  detail?: string | null;
  quote?: string | null;
  window?: [string, string] | null;
  period?: string | null;
}
interface Consensus { status: "licensed"; reason: string }
export interface SecurityEvents {
  symbol: string;
  as_of: string;
  past: SecurityEvent[];
  upcoming: SecurityEvent[];
  sources: string[];
  notes: string[];
  consensus: Consensus;
}
export interface UniverseEvents {
  universe: { label: string; members: number; scanned: number };
  window: { from: string; to: string; ahead_days: number; back_days: number };
  past: SecurityEvent[];
  upcoming: SecurityEvent[];
  failed: string[];
  note: string;
}
interface HistoryFigure {
  value: string;
  unit: string | null;
  filed: string | null;
  form: string | null;
  accession: string | null;
  url: string | null;
  restated: boolean;
  yoy_pct: string | null;
}
export interface EarningsHistory {
  symbol: string;
  status: string;
  reason?: string;
  period?: "annual" | "quarterly";
  official?: boolean;
  currency?: string | null;
  source?: string;
  fetched_at?: string | null;
  rows?: ({ period_end: string; start: string | null } & Partial<Record<"revenue" | "net_income" | "eps_diluted", HistoryFigure | null>>)[];
  notes?: string[];
  consensus: Consensus;
}

export function useSecurityEvents(symbol: string) {
  return useQuery({
    queryKey: ["terminal", "events", symbol],
    queryFn: ({ signal }) => api.get<SecurityEvents>("/api/terminal/events", { symbol }, signal),
    staleTime: 30 * 60_000,
    retry: false,
  });
}
export function useUniverseEvents(universe: string, ahead: number, back: number) {
  return useQuery({
    queryKey: ["terminal", "events", "universe", universe, ahead, back],
    queryFn: ({ signal }) => api.get<UniverseEvents>("/api/terminal/events/universe", { universe, ahead: String(ahead), back: String(back) }, signal),
    staleTime: 30 * 60_000,
    retry: false,
  });
}
export function useEarningsHistory(symbol: string) {
  return useQuery({
    queryKey: ["terminal", "earnings-history", symbol],
    queryFn: ({ signal }) => api.get<EarningsHistory>("/api/terminal/earnings-history", { symbol }, signal),
    staleTime: 30 * 60_000,
    retry: false,
  });
}

/* ------------------------------------------------------------------ presentation */
export const KIND_LABEL: Record<EventKind, string> = {
  results: "Results",
  dividend: "Dividend",
  split: "Split",
  report: "Report",
  proxy: "Proxy",
  meeting: "Meeting",
  buyback: "Buyback",
};
const KIND_TONE: Record<EventKind, "neutral" | "info" | "warn" | "pos" | "neg" | "accent"> = {
  results: "accent",
  dividend: "pos",
  split: "info",
  report: "neutral",
  proxy: "neutral",
  meeting: "info",
  buyback: "warn",
};
const STATUS_TONE: Record<EventStatus, "neutral" | "info" | "warn"> = { confirmed: "neutral", estimated: "info", deadline: "warn", mention: "warn" };
const STATUS_TITLE: Record<EventStatus, string> = {
  confirmed: "A dated filing or provider record",
  estimated: "Estimated from the cadence of past filings; not an announced date",
  deadline: "Regulatory deadline, not an announced date",
  mention: "Quoted mention in a filing; the amount is not verified here",
};

function daysFrom(iso: string, today: string): number {
  return Math.round((Date.parse(iso) - Date.parse(today)) / 86_400_000);
}

/** One dated event. `compact` (universe calendar) leaves out the per-row explanation and source line, which the panel states once. */
export function EventRow({ e, today, showSymbol, compact }: { e: SecurityEvent; today: string; showSymbol?: boolean; compact?: boolean }) {
  const days = daysFrom(e.date, today);
  const when = days === 0 ? "today" : days > 0 ? `in ${days} d` : `${-days} d ago`;
  return (
    <li className="py-2 text-[13px]">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="num w-24 shrink-0 whitespace-nowrap text-fg-2">{formatSessionDate(e.date)}</span>
        <span className="num w-[4.75rem] shrink-0 whitespace-nowrap text-xs text-fg-3">{when}</span>
        <Pill tone={KIND_TONE[e.kind]} className="py-0">{KIND_LABEL[e.kind]}</Pill>
        {showSymbol && e.symbol && (
          <Link to={`/instrument/${encodeURIComponent(e.symbol)}?tab=events`} className="num font-medium text-fg hover:text-accent-text">{e.symbol}</Link>
        )}
        <span className="min-w-0 flex-[1_1_14rem] text-fg">{e.label}</span>
        {e.status !== "confirmed" && (
          <span title={STATUS_TITLE[e.status]}><Pill tone={STATUS_TONE[e.status]} className="py-0">{e.status}</Pill></span>
        )}
        {e.url && (
          <a className="inline-flex items-center gap-1 text-xs text-fg-2 hover:text-fg" href={e.url} target="_blank" rel="noopener noreferrer">
            Source <ExternalLink className="size-3" aria-hidden />
          </a>
        )}
      </div>
      {(e.window || e.period || (e.detail && !compact)) && (
        <p className="mt-0.5 pl-24 text-xs leading-4 text-fg-3 max-sm:pl-0">
          {e.window ? <span className="num">Window {formatSessionDate(e.window[0])} – {formatSessionDate(e.window[1])}. </span> : null}
          {e.period ? <span>Period {formatSessionDate(e.period)}. </span> : null}
          {compact ? null : e.detail}
        </p>
      )}
      {e.quote && (
        <details className="mt-1 pl-24 text-xs max-sm:pl-0">
          <summary className="cursor-pointer text-fg-3 hover:text-fg-2">Quoted from the filing</summary>
          <blockquote className="mt-1 border-l-2 border-info/50 pl-3 leading-4 text-fg-2">{e.quote}</blockquote>
        </details>
      )}
      {!compact && <p className="pl-24 text-[11px] text-fg-3 max-sm:pl-0">Source: {e.source}</p>}
    </li>
  );
}

function KindFilter({ counts, hidden, onToggle }: { counts: Partial<Record<EventKind, number>>; hidden: Set<EventKind>; onToggle: (k: EventKind | null) => void }) {
  const kinds = (Object.keys(KIND_LABEL) as EventKind[]).filter((k) => counts[k]);
  if (kinds.length < 2) return null;
  return (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label="Show event kinds">
      {kinds.map((k) => {
        const on = !hidden.has(k);
        return (
          <button key={k} type="button" aria-pressed={on} onClick={() => onToggle(k)}
            className={cn("rounded-full border px-2.5 py-0.5 text-xs transition-colors", on ? "border-line bg-panel-2 text-fg" : "border-line-subtle text-fg-3 line-through hover:text-fg-2")}>
            {KIND_LABEL[k]} <span className="num text-fg-3">{counts[k]}</span>
          </button>
        );
      })}
      {hidden.size > 0 && (
        <button type="button" className="text-xs text-info underline decoration-info/40 underline-offset-2" onClick={() => onToggle(null)}>Show all</button>
      )}
    </div>
  );
}

/** Kind chips: every kind starts shown; a click hides that kind, "Show all" clears the hidden set. */
function useKindFilter(events: SecurityEvent[]) {
  const [hidden, setHidden] = useState<Set<EventKind>>(new Set());
  const counts = useMemo(() => {
    const c: Partial<Record<EventKind, number>> = {};
    for (const e of events) c[e.kind] = (c[e.kind] ?? 0) + 1;
    return c;
  }, [events]);
  const toggle = (k: EventKind | null) =>
    setHidden((prev) => {
      if (k === null) return new Set();
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  const filtered = hidden.size === 0 ? events : events.filter((e) => !hidden.has(e.kind));
  return { hidden, counts, toggle, filtered };
}

const PAGE = 30;

/** Terminal T4: one security's dated events (past and upcoming), each with its status, source and link. */
export function EventsTab({ symbol }: { symbol: string }) {
  const q = useSecurityEvents(symbol);
  const d = q.data;
  const all = useMemo(() => [...(d?.upcoming ?? []), ...(d?.past ?? [])], [d]);
  const { hidden, counts, toggle, filtered } = useKindFilter(all);
  const [shown, setShown] = useState(PAGE); // long dividend histories run to a hundred rows or more
  const today = d?.as_of ?? new Date().toISOString().slice(0, 10);
  const upcoming = filtered.filter((e) => e.date >= today);
  const past = filtered.filter((e) => e.date < today);
  if (q.isLoading) return <Panel title="Events" titleId="ev-title" className="lg:col-span-12"><SkeletonRows rows={8} /></Panel>;
  if (q.isError || !d) return <Panel title="Events" titleId="ev-title" className="lg:col-span-12"><ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} /></Panel>;
  return (
    <>
      <Panel title="Upcoming" titleId="ev-up-title" className="lg:col-span-4 lg:self-start" refreshing={q.isFetching} meta={`as of ${formatSessionDate(d.as_of)}`}>
        {upcoming.length ? (
          <ul className="divide-y divide-line-subtle">{upcoming.map((e, i) => <EventRow key={`${e.date}${e.kind}${i}`} e={e} today={today} />)}</ul>
        ) : d.upcoming.length ? (
          <p className="text-[13px] text-fg-3">No upcoming events of the selected kinds.</p>
        ) : (
          <EmptyState title="Nothing dated ahead">
            {d.notes.find((n) => /SEC|SEBI|neither|Indian/.test(n)) ?? "No upcoming date from the sources available for this listing."}
          </EmptyState>
        )}
        <div className="mt-3 space-y-1.5 border-t border-line-subtle pt-3 text-xs text-fg-3">
          <p>
            <span className="font-medium text-fg-2">Consensus estimates and surprises:</span> not shown. {d.consensus.reason}
          </p>
          <p>
            Status marks: <span className="text-fg-2">estimated</span> dates come from past filing cadence, <span className="text-fg-2">deadline</span> is the regulator's latest
            permitted date, <span className="text-fg-2">mention</span> is a quoted sentence. Everything else is a dated filing or provider record.
          </p>
        </div>
      </Panel>
      <Panel title="Past events" titleId="ev-past-title" className="lg:col-span-8" refreshing={q.isFetching} wrapHeader
        meta={`${d.past.length} event${d.past.length === 1 ? "" : "s"}`}
        actions={<KindFilter counts={counts} hidden={hidden} onToggle={toggle} />}>
        {past.length ? (
          <>
            <ul className="divide-y divide-line-subtle">{past.slice(0, shown).map((e, i) => <EventRow key={`${e.date}${e.kind}${i}`} e={e} today={today} />)}</ul>
            {past.length > shown && (
              <button type="button" className="mt-2 text-xs text-info underline decoration-info/40 underline-offset-2 hover:decoration-info" onClick={() => setShown((n) => n + PAGE)}>
                Show {Math.min(PAGE, past.length - shown)} more ({past.length - shown} earlier of {past.length})
              </button>
            )}
          </>
        ) : all.length ? (
          <p className="text-[13px] text-fg-3">No past events of the selected kinds.</p>
        ) : (
          <EmptyState title="No dated events">The sources available for this listing report no past results, dividends, splits or filings.</EmptyState>
        )}
        <div className="mt-3 space-y-1 border-t border-line-subtle pt-3 text-xs text-fg-3">
          {d.sources.length > 0 && <p>Sources: {d.sources.join(" · ")}.</p>}
          {d.notes.map((n, i) => <p key={i}>{n}</p>)}
          <p>
            Dividend and split dates are the provider's action dates (ex-dates as reported). Meetings are quoted from proxy notices; buybacks are mentions in results
            releases, not verified amounts.
          </p>
        </div>
      </Panel>
    </>
  );
}

/* ------------------------------------------------------------------ earnings history (Earnings tab) */
function figure(f: HistoryFigure | null | undefined, kind: "revenue" | "net_income" | "eps_diluted", ccy: string | null | undefined) {
  if (!f) return <span className="text-fg-3">{DASH}</span>;
  const unit = f.unit && f.unit !== "statement currency" ? f.unit.split("/")[0] : ccy ?? null;
  const text = kind === "eps_diluted" ? formatMoney(f.value, unit) : formatLargeMoney(f.value, unit);
  const title = [f.form && `${f.form}${f.filed ? ` filed ${f.filed}` : ""}`, f.accession && `accession ${f.accession}`, f.unit].filter(Boolean).join(" · ");
  const inner = (
    <>
      {text}
      {f.restated && <span className="rounded border border-warn/50 px-0.5 text-[10px] text-warn" aria-hidden>R</span>}
    </>
  );
  return f.url ? (
    <a href={f.url} target="_blank" rel="noopener noreferrer" title={title} className="num inline-flex items-center gap-1 hover:text-accent-text">{inner}</a>
  ) : (
    <span className="num inline-flex items-center gap-1" title={title || undefined}>{inner}</span>
  );
}

function yoyCell(f: HistoryFigure | null | undefined) {
  if (!f || f.yoy_pct === null) return <span className="text-fg-3">{DASH}</span>;
  const v = Number(f.yoy_pct);
  return <span className={cn("num", v > 0 ? "text-pos" : v < 0 ? "text-neg" : "")}>{formatPercent(v)}</span>;
}

/** Revenue and net income per period as paired bars (oldest left). Decorative twin of the table below it. */
function HistoryBars({ rows, currency }: { rows: NonNullable<EarningsHistory["rows"]>; currency: string | null | undefined }) {
  const data = [...rows].reverse().map((r) => ({ end: r.period_end, rev: r.revenue ? Number(r.revenue.value) : null, ni: r.net_income ? Number(r.net_income.value) : null }));
  const max = Math.max(1, ...data.flatMap((d) => [Math.abs(d.rev ?? 0), Math.abs(d.ni ?? 0)]));
  const hasNeg = data.some((d) => (d.ni ?? 0) < 0 || (d.rev ?? 0) < 0);
  const H = 120;
  const base = hasNeg ? H * 0.7 : H;
  const scale = (v: number) => (Math.abs(v) / max) * (hasNeg ? H * 0.7 : H);
  return (
    <figure className="m-0" aria-hidden>
      <div className="flex items-end gap-2 overflow-x-auto pb-1" style={{ height: H + 22 }}>
        {data.map((d, i) => (
          <div key={d.end} className="flex min-w-9 flex-1 flex-col items-center" title={`${formatSessionDate(d.end)} · revenue ${formatLargeMoney(d.rev, currency)} · net income ${formatLargeMoney(d.ni, currency)}`}>
            <div className="relative flex w-full items-end justify-center gap-0.5" style={{ height: H }}>
              {[d.rev, d.ni].map((v, j) => (
                <span key={j} className={cn("w-1/3 rounded-t-sm transition-all duration-700", j === 0 ? "bg-info/70" : v !== null && v < 0 ? "bg-neg/80" : "bg-pos/80")}
                  style={v === null ? { height: 0 } : v >= 0 ? { height: scale(v), marginBottom: H - base, animationDelay: `${i * 40}ms` } : { height: scale(v), marginBottom: H - base - scale(v), borderRadius: "0 0 2px 2px" }} />
              ))}
            </div>
            <span className="num mt-1 text-[10px] text-fg-3">{d.end.slice(2, 7)}</span>
          </div>
        ))}
      </div>
      <figcaption className="mt-1 flex gap-4 text-xs text-fg-3">
        <span><span className="mr-1 inline-block size-2 rounded-sm bg-info/70" />Revenue</span>
        <span><span className="mr-1 inline-block size-2 rounded-sm bg-pos/80" />Net income (red when a loss)</span>
      </figcaption>
    </figure>
  );
}

/** Reported revenue, net income and diluted EPS by period with the change on a year earlier. No estimates. */
export function EarningsHistoryPanel({ symbol, className }: { symbol: string; className?: string }) {
  const q = useEarningsHistory(symbol);
  const d = q.data;
  const rows = d?.rows ?? [];
  const hasEps = rows.some((r) => r.eps_diluted);
  return (
    <Panel title="Earnings history" titleId="eh-title" className={className} refreshing={q.isFetching && !q.isLoading} wrapHeader
      meta={d?.source ? `${d.period === "quarterly" ? "Quarterly" : "Annual"} · ${d.official ? "official filings" : "unofficial provider data"}` : undefined}>
      {q.isLoading ? (
        <SkeletonRows rows={6} />
      ) : q.isError || !d ? (
        <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
      ) : !rows.length ? (
        <InlineNotice>{d.reason ?? "No reported figures for this listing."}</InlineNotice>
      ) : (
        <div className="space-y-2">
          {rows.length >= 2 && <HistoryBars rows={rows} currency={d.currency} />}
          <div tabIndex={0} className="scroll-x scrollbar-thin relative overflow-x-auto">
            <table className="w-full min-w-[34rem] text-[13px]" aria-label={`Reported figures for ${symbol} by period`}>
              <thead>
                <tr className="border-b border-line-subtle text-xs text-fg-3">
                  <th scope="col" className="py-1.5 pr-3 text-left font-medium">Period end</th>
                  <th scope="col" className="px-2 py-1.5 text-right font-medium">Revenue</th>
                  <th scope="col" className="px-2 py-1.5 text-right font-medium" title="Change on the same period a year earlier">YoY</th>
                  <th scope="col" className="px-2 py-1.5 text-right font-medium">Net income</th>
                  <th scope="col" className="px-2 py-1.5 text-right font-medium" title="Change on the same period a year earlier">YoY</th>
                  {hasEps && <th scope="col" className="px-2 py-1.5 text-right font-medium">Diluted EPS</th>}
                  {hasEps && <th scope="col" className="px-2 py-1.5 text-right font-medium" title="Change on the same period a year earlier">YoY</th>}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.period_end} className="border-b border-line-subtle/60">
                    <th scope="row" className="num py-1.5 pr-3 text-left font-normal text-fg-2" title={r.start ? `${formatSessionDate(r.start)} – ${formatSessionDate(r.period_end)}` : undefined}>
                      {formatSessionDate(r.period_end)}
                    </th>
                    <td className="px-2 py-1.5 text-right">{figure(r.revenue, "revenue", d.currency)}</td>
                    <td className="px-2 py-1.5 text-right">{yoyCell(r.revenue)}</td>
                    <td className="px-2 py-1.5 text-right">{figure(r.net_income, "net_income", d.currency)}</td>
                    <td className="px-2 py-1.5 text-right">{yoyCell(r.net_income)}</td>
                    {hasEps && <td className="px-2 py-1.5 text-right">{figure(r.eps_diluted, "eps_diluted", d.currency)}</td>}
                    {hasEps && <td className="px-2 py-1.5 text-right">{yoyCell(r.eps_diluted)}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs leading-4 text-fg-3">
            Source: {d.source}
            {d.fetched_at ? ` · fetched ${formatRelative(d.fetched_at)}` : ""}. Reported figures only; year-on-year change is computed here against the period
            ending a year earlier (not shown when that period is missing or the base is not positive). R marks a figure restated in a later filing.
            {d.notes?.map((n) => ` ${n}`)} {d.consensus.reason}
          </p>
        </div>
      )}
    </Panel>
  );
}

/* ------------------------------------------------------------------ cross-universe calendar (Alerts page) */
const AHEAD_OPTIONS = [
  { value: "30", label: "30 d" },
  { value: "60", label: "60 d" },
  { value: "120", label: "120 d" },
] as const;

/** Dated events across a declared universe: results dates, dividends, splits, proxies and meetings in a window. */
export function UniverseEventsPanel({ className }: { className?: string }) {
  const [universe, setUniverse] = useState("watchlists");
  const [ahead, setAhead] = useState<(typeof AHEAD_OPTIONS)[number]["value"]>("60");
  const { data: lists } = useWatchlists();
  const q = useUniverseEvents(universe, Number(ahead), 14);
  const d = q.data;
  const today = new Date().toISOString().slice(0, 10);
  const sources = d ? [...new Set([...d.upcoming, ...d.past].map((e) => e.source))] : [];
  return (
    <Panel title="Corporate events" titleId="ue-title" className={className} refreshing={q.isFetching && !q.isLoading} wrapHeader
      meta={d ? `${d.universe.label} · ${d.universe.scanned} of ${d.universe.members} listings` : undefined}>
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <label className="flex items-center gap-1.5 text-xs text-fg-3">
          <span>Universe</span>
          <select className="h-8 rounded-[var(--radius-control)] border border-line bg-panel px-1.5 text-xs text-fg" value={universe} onChange={(e) => setUniverse(e.target.value)}>
            <option value="watchlists">All watchlists</option>
            <option value="holdings">Holdings</option>
            {(lists ?? []).map((w) => <option key={w.id} value={`watchlist:${w.id}`}>{w.name}</option>)}
          </select>
        </label>
        <Segmented label="Days ahead" value={ahead} onChange={setAhead} options={[...AHEAD_OPTIONS]} />
      </div>
      {q.isLoading ? (
        <SkeletonRows rows={5} />
      ) : q.isError || !d ? (
        <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
      ) : !d.upcoming.length && !d.past.length ? (
        <EmptyState title="No dated events in this window">
          Dates appear for US registrants (SEC filings), Indian listings (SEBI deadlines) and provider-reported dividends and splits.
        </EmptyState>
      ) : (
        <div className="space-y-3">
          {d.upcoming.length > 0 && (
            <div>
              <h3 className="text-xs font-medium text-fg-2">Ahead</h3>
              <ul className="divide-y divide-line-subtle">{d.upcoming.slice(0, 40).map((e, i) => <EventRow key={`${e.symbol}${e.date}${e.kind}${i}`} e={e} today={today} showSymbol compact />)}</ul>
            </div>
          )}
          {d.past.length > 0 && (
            <div>
              <h3 className="text-xs font-medium text-fg-2">Last two weeks</h3>
              <ul className="divide-y divide-line-subtle">{d.past.slice(0, 20).map((e, i) => <EventRow key={`${e.symbol}${e.date}${e.kind}${i}`} e={e} today={today} showSymbol compact />)}</ul>
            </div>
          )}
          {d.failed.length > 0 && <InlineNotice tone="warn">Not scanned: {d.failed.join(", ")}.</InlineNotice>}
          <p className="text-xs leading-4 text-fg-3">
            <span className="num">{formatSessionDate(d.window.from)} – {formatSessionDate(d.window.to)}</span>. {d.note}
            {sources.length > 0 && <> Sources: {sources.join(" · ")}. Open a listing's Events tab for each date's explanation and link.</>}
          </p>
        </div>
      )}
    </Panel>
  );
}
