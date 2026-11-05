/** Offline read-only copy (M14). Opt-in per device; a snapshot of watchlists and holdings, stamped with the time it
 * was synced, shown only when the server cannot be reached and always labelled as a past copy, never as live.
 * Erased on sign-out, when the session ends and when the owner turns it off. */
import { api, type PortfolioSummary, type Snapshot, type Watchlist } from "@/lib/api/client";

const ENABLED = "md-offline-enabled";
const SNAP = "md-offline-snapshot";
const MAX_LISTS = 5;

export type OfflineRow = {
  symbol: string;
  name: string | null;
  currency: string | null;
  last_price: string | null;
  change_percent: string | null;
  session_date: string | null;
  market_time: string | null;
  status: string;
};
export type OfflineSnapshot = {
  version: 1;
  synced_at: string;
  timezone: string;
  watchlists: { name: string; rows: OfflineRow[] }[];
  accounts: {
    currency: string;
    cash: string;
    holdings_value: string;
    total_equity: string | null;
    holdings: { symbol: string; name: string | null; quantity: string; last_price: string | null; market_value: string | null; unrealized_pnl: string | null; mark_status: string }[];
  }[];
};

function store(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function offlineEnabled(): boolean {
  return store()?.getItem(ENABLED) === "1";
}

export function readSnapshot(): OfflineSnapshot | null {
  try {
    const raw = store()?.getItem(SNAP);
    const s = raw ? (JSON.parse(raw) as OfflineSnapshot) : null;
    return s?.version === 1 ? s : null;
  } catch {
    return null;
  }
}

/** Erase every MarketDesk copy on this device: the snapshot and the service worker's shell caches. */
export function clearOffline() {
  const s = store();
  s?.removeItem(SNAP);
  s?.removeItem(ENABLED);
  try {
    navigator.serviceWorker?.controller?.postMessage("md-clear");
  } catch {
    /* no service worker */
  }
}

export function setOfflineEnabled(on: boolean) {
  if (on) store()?.setItem(ENABLED, "1");
  else clearOffline();
}

/** Fetch and store a fresh snapshot (only when enabled). Returns it, or null when off or nothing could be read. */
export async function syncSnapshot(timezone: string): Promise<OfflineSnapshot | null> {
  if (!offlineEnabled()) return null;
  const lists = (await api.get<Watchlist[]>("/api/watchlists")).slice(0, MAX_LISTS);
  const full = await Promise.all(lists.map((l) => api.get<Watchlist>(`/api/watchlists/${l.id}`)));
  const symbols = Array.from(new Set(full.flatMap((l) => l.items.map((i) => i.symbol)))).slice(0, 60);
  const snaps = symbols.length ? await api.get<Snapshot[]>("/api/market/snapshots", { symbols: symbols.join(",") }) : [];
  const bySym = new Map(snaps.map((s) => [s.symbol, s]));
  const accounts: OfflineSnapshot["accounts"] = [];
  for (const currency of ["INR", "USD"] as const) {
    const p = await api.get<PortfolioSummary>("/api/portfolio/summary", { currency });
    if (!p.has_transactions) continue;
    accounts.push({
      currency,
      cash: p.cash,
      holdings_value: p.holdings_value,
      total_equity: p.total_equity ?? null,
      holdings: p.holdings.map((h) => ({ symbol: h.symbol, name: h.name ?? null, quantity: h.quantity, last_price: h.last_price ?? null, market_value: h.market_value ?? null, unrealized_pnl: h.unrealized_pnl ?? null, mark_status: h.mark_status })),
    });
  }
  if (!offlineEnabled()) return null; // turned off (or signed out) while syncing
  const snap: OfflineSnapshot = {
    version: 1,
    synced_at: new Date().toISOString(),
    timezone,
    watchlists: full.map((l) => ({
      name: l.name,
      rows: l.items.map((i) => {
        const s = bySym.get(i.symbol);
        return {
          symbol: i.symbol,
          name: i.instrument.name ?? null,
          currency: i.instrument.currency ?? null,
          last_price: s?.quote?.last_price ?? null,
          change_percent: s?.quote?.change_percent ?? null,
          session_date: s?.quote?.session_date ?? null,
          market_time: s?.quote?.market_time ?? null,
          status: s?.meta.status ?? "missing",
        };
      }),
    })),
    accounts,
  };
  try {
    store()?.setItem(SNAP, JSON.stringify(snap));
  } catch {
    return null; // storage full or blocked: no offline copy rather than a partial one
  }
  return snap;
}
