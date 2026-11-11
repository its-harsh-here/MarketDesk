import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Panel } from "@/components/ui/Panel";
import { ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { api, errorMessage } from "@/lib/api/client";
import { cn } from "@/lib/cn";
import { DASH, formatCompact, formatInstant, formatMoney, formatNumber, formatPercent, formatRelative, formatSessionDate } from "@/lib/format";
import { usePrefs } from "@/features/settings/api";

interface Row { contract: string; strike: string; last: string | null; bid: string | null; ask: string | null; volume: number | null; open_interest: number | null; iv: string | null; itm: boolean | null }
interface Chain {
  symbol: string; status: string; reason?: string; source?: string; fetched_at?: string | null; expiries?: string[]; expiry?: string;
  days_to_expiry?: number; currency?: string | null; spot?: string | null; spot_time?: string | null; calls?: Row[]; puts?: Row[];
  stats?: { calls: { open_interest: number; volume: number }; puts: { open_interest: number; volume: number }; put_call_oi: string | null;
    put_call_volume: string | null; max_pain: string | null; atm: { strike: string; iv: string | null } | null;
    smile: { strike: string; side: "call" | "put"; iv: string }[] };
  note?: string;
}

function Smile({ points, spot }: { points: NonNullable<Chain["stats"]>["smile"]; spot: number | null }) {
  const W = 520, H = 140, P = 24;
  if (points.length < 3) return null;
  const xs = points.map((p) => Number(p.strike)), ys = points.map((p) => Number(p.iv) * 100);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const sx = (x: number) => P + ((x - x0) / (x1 - x0 || 1)) * (W - 2 * P);
  const sy = (y: number) => H - P - ((y - y0) / (y1 - y0 || 1)) * (H - 2 * P);
  const line = (side: "call" | "put") => points.filter((p) => p.side === side).sort((a, b) => Number(a.strike) - Number(b.strike))
    .map((p, i) => `${i ? "L" : "M"}${sx(Number(p.strike)).toFixed(1)},${sy(Number(p.iv) * 100).toFixed(1)}`).join(" ");
  return (
    <figure className="m-0">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Implied volatility by strike: from ${y0.toFixed(1)}% to ${y1.toFixed(1)}%`}>
        {spot !== null && spot >= x0 && spot <= x1 && <line x1={sx(spot)} x2={sx(spot)} y1={P / 2} y2={H - P} stroke="var(--fg-3)" strokeDasharray="3 3" />}
        <path d={line("call")} fill="none" stroke="var(--info)" strokeWidth={2} className="fx-spark-path" />
        <path d={line("put")} fill="none" stroke="var(--accent)" strokeWidth={2} />
        <text x={P} y={H - 6} fontSize="10" fill="var(--fg-3)">{formatNumber(x0)}</text>
        <text x={W - P} y={H - 6} fontSize="10" fill="var(--fg-3)" textAnchor="end">{formatNumber(x1)}</text>
        <text x={4} y={sy(y1) + 4} fontSize="10" fill="var(--fg-3)">{y1.toFixed(0)}%</text>
        <text x={4} y={sy(y0) + 4} fontSize="10" fill="var(--fg-3)">{y0.toFixed(0)}%</text>
      </svg>
      <figcaption className="flex gap-4 text-xs text-fg-3">
        <span><span className="mr-1 inline-block h-0.5 w-3 bg-info align-middle" />Calls</span>
        <span><span className="mr-1 inline-block h-0.5 w-3 bg-accent align-middle" />Puts</span>
        <span>dashed: last price</span>
      </figcaption>
    </figure>
  );
}

/** Terminal T7: one expiry of the option chain, read-only. */
export function OptionsTab({ symbol }: { symbol: string }) {
  const [expiry, setExpiry] = useState<string | null>(null);
  const { data: prefs } = usePrefs();
  const q = useQuery({
    queryKey: ["terminal", "options", symbol, expiry],
    queryFn: ({ signal }) => api.get<Chain>("/api/terminal/options", { symbol, ...(expiry ? { expiry } : {}) }, signal),
    staleTime: 5 * 60_000,
    retry: false,
    placeholderData: keepPreviousData,
  });
  const d = q.data;
  const rows = useMemo(() => {
    const byStrike = new Map<string, { strike: number; call?: Row; put?: Row }>();
    for (const c of d?.calls ?? []) byStrike.set(c.strike, { ...(byStrike.get(c.strike) ?? { strike: Number(c.strike) }), call: c });
    for (const p of d?.puts ?? []) byStrike.set(p.strike, { ...(byStrike.get(p.strike) ?? { strike: Number(p.strike) }), put: p });
    return [...byStrike.values()].sort((a, b) => a.strike - b.strike);
  }, [d]);
  const maxOi = Math.max(1, ...rows.flatMap((r) => [r.call?.open_interest ?? 0, r.put?.open_interest ?? 0]));
  const spot = d?.spot ? Number(d.spot) : null;
  const ccy = d?.currency ?? null;
  if (q.isLoading) return <Panel title="Options" titleId="opt-title" className="lg:col-span-12"><SkeletonRows rows={10} /></Panel>;
  if (q.isError || !d) return <Panel title="Options" titleId="opt-title" className="lg:col-span-12"><ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} /></Panel>;
  if (!d.calls) return <Panel title="Options" titleId="opt-title" className="lg:col-span-12"><InlineNotice>{d.reason}</InlineNotice></Panel>;
  const st = d.stats!;
  const cell = (r: Row | undefined, k: keyof Row) => (r && r[k] !== null && r[k] !== undefined ? r[k] : null);
  const side = (r: Row | undefined, align: "left" | "right") => {
    const oi = r?.open_interest ?? 0;
    return (
      <>
        <td className={cn("num px-2 text-right", r?.itm && "bg-accent-soft")}>{cell(r, "last") ? formatNumber(r!.last) : DASH}</td>
        <td className={cn("num px-2 text-right text-fg-2 max-md:hidden", r?.itm && "bg-accent-soft")}>{cell(r, "bid") ? `${formatNumber(r!.bid)}–${formatNumber(r!.ask)}` : DASH}</td>
        <td className={cn("num px-2 text-right text-fg-2 max-sm:hidden", r?.itm && "bg-accent-soft")}>{r?.volume ?? DASH}</td>
        <td className={cn("relative px-2 text-right", r?.itm && "bg-accent-soft")}>
          <span aria-hidden className={cn("absolute inset-y-1 rounded-sm opacity-30", align === "left" ? "right-1 bg-info" : "left-1 bg-accent")} style={{ width: `${(oi / maxOi) * 70}%` }} />
          <span className="num relative">{r?.open_interest !== null && r?.open_interest !== undefined ? formatCompact(r.open_interest) : DASH}</span>
        </td>
        <td className={cn("num px-2 text-right text-fg-2", r?.itm && "bg-accent-soft")}>{r?.iv ? formatPercent(Number(r.iv) * 100, { signed: false }) : DASH}</td>
      </>
    );
  };
  return (
    <>
      <Panel title="Option chain" titleId="opt-title" className="lg:col-span-8" refreshing={q.isFetching} wrapHeader
        meta={`${d.source}${d.fetched_at ? ` · fetched ${formatRelative(d.fetched_at)}` : ""}`}
        actions={
          <label className="flex items-center gap-1.5 text-xs text-fg-3">
            <span>Expiry</span>
            <select aria-label="Expiry" value={d.expiry} onChange={(e) => setExpiry(e.target.value)} className="h-8 rounded-[var(--radius-control)] border border-line bg-panel px-1.5 text-xs text-fg">
              {d.expiries!.map((x) => <option key={x} value={x}>{formatSessionDate(x)}</option>)}
            </select>
          </label>
        }>
        <div tabIndex={0} className="scroll-x scrollbar-thin max-h-[36rem] overflow-auto">
          <table className="w-full min-w-[38rem] text-[13px]" aria-label={`${symbol} options expiring ${formatSessionDate(d.expiry)}: calls left, puts right`}>
            <thead className="sticky top-0 z-10 bg-panel">
              <tr className="text-xs text-fg-3"><th colSpan={5} scope="colgroup" className="py-1 text-center font-medium text-info">Calls</th><th /><th colSpan={5} scope="colgroup" className="py-1 text-center font-medium text-accent-text">Puts</th></tr>
              <tr className="border-b border-line-subtle text-xs text-fg-3">
                {["Last", "Bid–ask", "Vol", "Open int.", "IV"].map((h) => <th key={`c${h}`} scope="col" className={cn("px-2 py-1 text-right font-medium", h === "Bid–ask" && "max-md:hidden", h === "Vol" && "max-sm:hidden")}>{h}</th>)}
                <th scope="col" className="px-3 py-1 text-center font-semibold text-fg">Strike</th>
                {["Last", "Bid–ask", "Vol", "Open int.", "IV"].map((h) => <th key={`p${h}`} scope="col" className={cn("px-2 py-1 text-right font-medium", h === "Bid–ask" && "max-md:hidden", h === "Vol" && "max-sm:hidden")}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const spotHere = spot !== null && i > 0 && rows[i - 1].strike < spot && r.strike >= spot;
                return (
                  <tr key={r.strike} className={cn("border-b border-line-subtle/60", spotHere && "border-t-2 border-t-accent")}>
                    {side(r.call, "left")}
                    <th scope="row" className={cn("num px-3 text-center font-semibold", st.max_pain && Number(st.max_pain) === r.strike ? "text-warn" : "text-fg")}
                      title={st.max_pain && Number(st.max_pain) === r.strike ? "Max pain strike" : undefined}>{formatNumber(r.strike)}</th>
                    {side(r.put, "right")}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs leading-4 text-fg-3">Shaded cells are in the money; the line marks the last price; the amber strike is max pain. {d.note}</p>
      </Panel>
      <Panel title="Chain summary" titleId="opt-sum" className="lg:col-span-4 lg:self-start">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-[13px]">
          <div><dt className="text-xs text-fg-3">Last price</dt><dd className="num text-base font-semibold">{spot !== null ? formatMoney(d.spot, ccy) : DASH}</dd><dd className="text-[11px] text-fg-3">{d.spot_time ? formatInstant(d.spot_time, prefs?.display_timezone) : ""}</dd></div>
          <div><dt className="text-xs text-fg-3">Days to expiry</dt><dd className="num text-base font-semibold">{d.days_to_expiry}</dd></div>
          <div><dt className="text-xs text-fg-3">Put/call (open interest)</dt><dd className="num">{st.put_call_oi ? formatNumber(st.put_call_oi) : DASH}</dd></div>
          <div><dt className="text-xs text-fg-3">Put/call (volume)</dt><dd className="num">{st.put_call_volume ? formatNumber(st.put_call_volume) : DASH}</dd></div>
          <div><dt className="text-xs text-fg-3">Open interest calls / puts</dt><dd className="num">{formatCompact(st.calls.open_interest)} / {formatCompact(st.puts.open_interest)}</dd></div>
          <div><dt className="text-xs text-fg-3">Max pain</dt><dd className="num text-warn">{st.max_pain ? formatNumber(st.max_pain) : DASH}</dd></div>
          <div className="col-span-2"><dt className="text-xs text-fg-3">At-the-money implied volatility</dt><dd className="num">{st.atm?.iv ? `${formatPercent(Number(st.atm.iv) * 100, { signed: false })} at ${formatNumber(st.atm.strike)}` : DASH}</dd></div>
        </dl>
        <div className="mt-4"><Smile points={st.smile} spot={spot} /></div>
      </Panel>
    </>
  );
}
