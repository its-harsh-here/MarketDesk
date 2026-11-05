import { CloudOff, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { formatInstant, formatMoney, formatNumber, formatPercent, formatRelative } from "@/lib/format";
import type { OfflineSnapshot } from "@/lib/offline";
import { cn } from "@/lib/cn";

/** Read-only view of this device's last synced copy, shown only when the server cannot be reached. It is labelled on
 * every screen as a past copy (sync time, "not live") and offers no actions that would change anything. */
export function OfflineView({ snapshot, onRetry, reason }: { snapshot: OfflineSnapshot; onRetry: () => void; reason: string }) {
  const tz = snapshot.timezone;
  return (
    <div className="min-h-dvh bg-canvas">
      <header className="safe-top sticky top-0 z-10 border-b border-warn/40 bg-warn-soft">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
          <CloudOff className="size-5 shrink-0 text-warn" aria-hidden />
          <div className="min-w-0 flex-1 basis-60">
            <h1 className="text-[15px] font-semibold text-fg">Offline copy · read-only · not live</h1>
            <p className="text-[13px] text-fg-2">
              Synced from this device on <span className="num">{formatInstant(snapshot.synced_at, tz)}</span> ({formatRelative(snapshot.synced_at)}). {reason}
            </p>
          </div>
          <Button size="sm" icon={<RefreshCw className="size-3.5" aria-hidden />} onClick={onRetry}>
            Try the server again
          </Button>
        </div>
      </header>
      <main className="mx-auto max-w-5xl space-y-6 px-4 py-5">
        <p className="text-xs text-fg-3">
          Prices are the last observations MarketDesk had when this copy was made, each with its own market time. Nothing can be changed here; alerts, AI and research need the server.
        </p>
        {snapshot.watchlists.length === 0 && snapshot.accounts.length === 0 && (
          <p className="rounded-[var(--radius-panel)] border border-line-subtle bg-panel px-4 py-3 text-[13px] text-fg-2">This copy has no watchlists or holdings: there were none when it was synced.</p>
        )}
        {snapshot.watchlists.map((w) => (
          <section key={w.name} aria-labelledby={`off-${w.name}`} className="rounded-[var(--radius-panel)] border border-line-subtle bg-panel">
            <h2 id={`off-${w.name}`} className="border-b border-line-subtle px-4 py-2.5 text-[14px] font-semibold">{w.name}</h2>
            {w.rows.length === 0 ? (
              <p className="px-4 py-3 text-[13px] text-fg-3">Empty watchlist.</p>
            ) : (
              <table className="w-full text-[13px]">
                <caption className="sr-only">{w.name}: last observed prices at sync time</caption>
                <thead>
                  <tr className="text-xs text-fg-3">
                    <th scope="col" className="px-4 py-1.5 text-left font-medium">Instrument</th>
                    <th scope="col" className="px-2 py-1.5 text-right font-medium">Last observed</th>
                    <th scope="col" className="px-2 py-1.5 text-right font-medium">Change</th>
                    <th scope="col" className="px-4 py-1.5 text-right font-medium max-sm:hidden">Market time</th>
                  </tr>
                </thead>
                <tbody>
                  {w.rows.map((r) => {
                    const ch = r.change_percent === null ? null : Number(r.change_percent);
                    return (
                      <tr key={r.symbol} className="border-t border-line-subtle/60">
                        <th scope="row" className="px-4 py-1.5 text-left font-normal">
                          <span className="num block">{r.symbol}</span>
                          <span className="block truncate text-xs text-fg-3">{r.name}</span>
                        </th>
                        <td className="num px-2 py-1.5 text-right">{formatMoney(r.last_price, r.currency ?? "INR")}</td>
                        <td className={cn("num px-2 py-1.5 text-right", ch === null ? "text-fg-3" : ch >= 0 ? "text-pos" : "text-neg")}>
                          {ch === null ? "—" : `${ch >= 0 ? "▲" : "▼"} ${formatPercent(r.change_percent)}`}
                        </td>
                        <td className="num px-4 py-1.5 text-right text-xs text-fg-3 max-sm:hidden">{formatInstant(r.market_time, tz)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </section>
        ))}
        {snapshot.accounts.map((a) => (
          <section key={a.currency} aria-labelledby={`off-acct-${a.currency}`} className="rounded-[var(--radius-panel)] border border-line-subtle bg-panel">
            <h2 id={`off-acct-${a.currency}`} className="border-b border-line-subtle px-4 py-2.5 text-[14px] font-semibold">
              {a.currency} account <span className="font-normal text-fg-3">· cash {formatMoney(a.cash, a.currency)} · equity {a.total_equity ? formatMoney(a.total_equity, a.currency) : "incomplete"} at sync</span>
            </h2>
            <table className="w-full text-[13px]">
              <caption className="sr-only">{a.currency} holdings at sync time</caption>
              <thead>
                <tr className="text-xs text-fg-3">
                  <th scope="col" className="px-4 py-1.5 text-left font-medium">Holding</th>
                  <th scope="col" className="px-2 py-1.5 text-right font-medium">Quantity</th>
                  <th scope="col" className="px-2 py-1.5 text-right font-medium">Value</th>
                  <th scope="col" className="px-4 py-1.5 text-right font-medium">Unrealized</th>
                </tr>
              </thead>
              <tbody>
                {a.holdings.map((h) => (
                  <tr key={h.symbol} className="border-t border-line-subtle/60">
                    <th scope="row" className="num px-4 py-1.5 text-left font-normal">{h.symbol}</th>
                    <td className="num px-2 py-1.5 text-right">{formatNumber(h.quantity, 0)}</td>
                    <td className="num px-2 py-1.5 text-right">{formatMoney(h.market_value, a.currency)}</td>
                    <td className="num px-4 py-1.5 text-right">{formatMoney(h.unrealized_pnl, a.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ))}
      </main>
    </div>
  );
}

/** A thin notice while the browser reports no network: panels keep their last results and cannot refresh. */
export function OfflineBanner() {
  const [offline, setOffline] = useState(() => typeof navigator !== "undefined" && navigator.onLine === false);
  useEffect(() => {
    const on = () => setOffline(false);
    const off = () => setOffline(true);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);
  if (!offline) return null;
  return (
    <div role="status" className="border-b border-warn/40 bg-warn-soft px-4 py-2 text-[13px] text-fg md:px-6">
      <CloudOff className="mr-2 inline size-4 align-[-3px] text-warn" aria-hidden />
      No network connection. What you see was loaded earlier and is not refreshing; changes cannot be saved until the connection returns.
    </div>
  );
}
