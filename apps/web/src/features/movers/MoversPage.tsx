import { useQuery } from "@tanstack/react-query";
import { Activity, Flame, TrendingDown, TrendingUp } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { ChangeText } from "@/components/ui/Change";
import { Panel } from "@/components/ui/Panel";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/States";
import { api, errorMessage } from "@/lib/api/client";
import { formatLargeMoney, formatMoney, formatSessionDate, formatVolume } from "@/lib/format";
import { useWatchlists } from "@/features/watchlists/api";

interface MoverRow {
  symbol: string;
  name: string | null;
  currency: string | null;
  status: string;
  message: string | null;
  last?: string;
  change?: string | null;
  change_pct?: string | null;
  volume?: number | null;
  volume_note?: string | null;
  traded_value?: string | null;
  session?: string | null;
  unusual?: { session: string; volume: number; median: number; n: number; ratio: number } | null;
  range_pos?: number | null;
}
interface Movers {
  universe: { label: string; members: number };
  gainers: MoverRow[];
  losers: MoverRow[];
  active: MoverRow[];
  unusual: MoverRow[];
  rows: MoverRow[];
  breadth: { advancing: number; declining: number; unchanged: number; no_quote: number };
  currencies: string[];
  notes: string[];
}

function useMovers(universe: string) {
  return useQuery({
    queryKey: ["terminal", "movers", universe],
    queryFn: ({ signal }) => api.get<Movers>("/api/terminal/movers", { universe }, signal),
    staleTime: 60_000,
    refetchInterval: 120_000,
    refetchIntervalInBackground: false,
  });
}

function List({ rows, metric, empty }: { rows: MoverRow[]; metric: (r: MoverRow) => ReactNode; empty: string }) {
  const navigate = useNavigate();
  if (!rows.length) return <p className="py-6 text-center text-[13px] text-fg-3">{empty}</p>;
  return (
    <ol className="divide-y divide-line-subtle">
      {rows.map((r, i) => (
        <li key={r.symbol}>
          <button type="button" onClick={() => navigate(`/instrument/${encodeURIComponent(r.symbol)}`)}
            className="group flex w-full items-center gap-3 px-1 py-2 text-left transition-colors hover:bg-hover/50">
            <span className="num w-5 shrink-0 text-xs text-fg-3">{i + 1}</span>
            <span className="min-w-0 flex-1">
              <span className="num block truncate text-[13px] font-semibold text-fg group-hover:text-accent-text">{r.symbol}</span>
              <span className="block truncate text-xs text-fg-3">{r.name}</span>
            </span>
            <span className="num shrink-0 text-right text-[13px] text-fg">{formatMoney(r.last, r.currency)}</span>
            <span className="w-28 shrink-0 text-right">{metric(r)}</span>
          </button>
        </li>
      ))}
    </ol>
  );
}

function Breadth({ b }: { b: Movers["breadth"] }) {
  const total = b.advancing + b.declining + b.unchanged || 1;
  const seg = (n: number) => `${(n / total) * 100}%`;
  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded-full bg-elevated" role="img" aria-label={`${b.advancing} advancing, ${b.declining} declining, ${b.unchanged} unchanged`}>
        <span className="bg-pos transition-[width] duration-700" style={{ width: seg(b.advancing) }} />
        <span className="bg-fg-3/50 transition-[width] duration-700" style={{ width: seg(b.unchanged) }} />
        <span className="bg-neg transition-[width] duration-700" style={{ width: seg(b.declining) }} />
      </div>
      <dl className="mt-2 grid grid-cols-4 gap-2 text-center text-xs">
        <div><dt className="text-fg-3">Up</dt><dd className="num text-base font-semibold text-pos">▲ {b.advancing}</dd></div>
        <div><dt className="text-fg-3">Flat</dt><dd className="num text-base font-semibold text-fg-2">{b.unchanged}</dd></div>
        <div><dt className="text-fg-3">Down</dt><dd className="num text-base font-semibold text-neg">▼ {b.declining}</dd></div>
        <div><dt className="text-fg-3">No quote</dt><dd className="num text-base font-semibold text-fg-3">{b.no_quote}</dd></div>
      </dl>
    </div>
  );
}

/** Terminal T9: who moved across the owner's universes, from each member's latest provider quote. */
export function MoversPage() {
  const [params, setParams] = useSearchParams();
  const universe = params.get("uni") ?? "watchlists";
  const q = useMovers(universe);
  const { data: lists } = useWatchlists();
  const d = q.data;
  const oneCcy = (d?.currencies.length ?? 0) <= 1;
  return (
    <div className="grid grid-cols-1 gap-4 p-4 md:p-6 lg:grid-cols-12 lg:gap-5">
      <Panel title="Market movers" titleId="mv-title" className="lg:col-span-12" refreshing={q.isFetching && !q.isLoading} wrapHeader
        meta={d ? `${d.universe.label} · ${d.universe.members} listings · refreshes every 2 minutes while open` : undefined}
        actions={
          <label className="flex items-center gap-1.5 text-xs text-fg-3">
            <span>Universe</span>
            <select className="h-8 rounded-[var(--radius-control)] border border-line bg-panel px-1.5 text-xs text-fg" value={universe}
              onChange={(e) => setParams((p) => { const n = new URLSearchParams(p); n.set("uni", e.target.value); return n; }, { replace: true })}>
              <option value="watchlists">All watchlists</option>
              <option value="holdings">Holdings</option>
              {(lists ?? []).map((w) => <option key={w.id} value={`watchlist:${w.id}`}>{w.name}</option>)}
            </select>
          </label>
        }>
        {q.isLoading ? <SkeletonRows rows={2} /> : q.isError || !d ? <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} /> : d.universe.members === 0 ? (
          <EmptyState title="No listings in this universe">
            Add symbols to a watchlist to see who is moving. <Link to="/watchlists" className="text-accent-text underline">Open watchlists</Link>
          </EmptyState>
        ) : <Breadth b={d.breadth} />}
      </Panel>
      {d && d.universe.members > 0 && (
        <>
          <Panel title={<><TrendingUp className="mr-1 inline size-4 text-pos" aria-hidden />Top gainers</>} titleId="mv-g" className="lg:col-span-6">
            <List rows={d.gainers} empty="Nothing is up." metric={(r) => <ChangeText percent={r.change_pct} />} />
          </Panel>
          <Panel title={<><TrendingDown className="mr-1 inline size-4 text-neg" aria-hidden />Top losers</>} titleId="mv-l" className="lg:col-span-6">
            <List rows={d.losers} empty="Nothing is down." metric={(r) => <ChangeText percent={r.change_pct} />} />
          </Panel>
          <Panel title={<><Activity className="mr-1 inline size-4 text-info" aria-hidden />Most active</>} titleId="mv-a" className="lg:col-span-6"
            meta={oneCcy ? "by traded value" : "by traded value · mixed currencies are not comparable"}>
            <List rows={d.active} empty="No volume reported."
              metric={(r) => <span className="num text-[13px] text-fg-2" title={r.volume_note ?? undefined}>{formatLargeMoney(r.traded_value, r.currency)}{r.volume_note ? "*" : ""}</span>} />
          </Panel>
          <Panel title={<><Flame className="mr-1 inline size-4 text-warn" aria-hidden />Unusual volume</>} titleId="mv-u" className="lg:col-span-6" meta="completed session vs 20-session median">
            <List rows={d.unusual} empty="No listing traded 1.5× its usual volume in the last completed session."
              metric={(r) => r.unusual ? (
                <span className="num text-[13px] text-warn" title={`${formatVolume(r.unusual.volume)} on ${formatSessionDate(r.unusual.session)} vs median ${formatVolume(r.unusual.median)} of ${r.unusual.n} sessions`}>
                  {r.unusual.ratio.toFixed(1)}× avg
                </span>
              ) : null} />
          </Panel>
          <div className="space-y-1 text-xs text-fg-3 lg:col-span-12">{d.notes.map((n) => <p key={n}>{n}</p>)}</div>
        </>
      )}
    </div>
  );
}
