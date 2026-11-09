/** Recently viewed instruments: a per-device convenience for the command palette (browser storage only, newest
 * first, at most eight). Cleared at sign-out with the other per-device copies. */
export type Recent = { symbol: string; name: string | null; at: number };

const KEY = "md-recent-instruments";
const MAX = 8;

function store(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function readRecents(): Recent[] {
  try {
    const raw = store()?.getItem(KEY);
    const list = raw ? (JSON.parse(raw) as Recent[]) : [];
    return Array.isArray(list) ? list.filter((r) => typeof r?.symbol === "string").slice(0, MAX) : [];
  } catch {
    return [];
  }
}

export function recordRecent(symbol: string, name: string | null | undefined) {
  const rest = readRecents().filter((r) => r.symbol !== symbol);
  try {
    store()?.setItem(KEY, JSON.stringify([{ symbol, name: name ?? null, at: Date.now() }, ...rest].slice(0, MAX)));
  } catch {
    /* storage unavailable: nothing is remembered */
  }
}

/** Drop one entry, e.g. a symbol that turned out not to exist. */
export function forgetRecent(symbol: string) {
  try {
    store()?.setItem(KEY, JSON.stringify(readRecents().filter((r) => r.symbol !== symbol)));
  } catch {
    /* nothing stored */
  }
}

export function clearRecents() {
  try {
    store()?.removeItem(KEY);
  } catch {
    /* nothing stored */
  }
}
