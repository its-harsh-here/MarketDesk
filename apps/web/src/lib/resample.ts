/** Daily bars → weekly (ISO week, Monday start) or monthly bars: first open, highest high, lowest low, last close,
 * summed volume. A period's date is its last session. Missing OHLC stays missing (never invented from closes). */
export interface OHLCV {
  time: string; // YYYY-MM-DD session date
  open: number | null;
  high: number | null;
  low: number | null;
  close: number;
  volume: number | null;
}
export type Frequency = "daily" | "weekly" | "monthly";

function weekKey(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  const day = (d.getUTCDay() + 6) % 7; // Monday = 0
  d.setUTCDate(d.getUTCDate() - day);
  return d.toISOString().slice(0, 10);
}

export function resample(bars: OHLCV[], freq: Frequency): (OHLCV & { sessions: number })[] {
  if (freq === "daily") return bars.map((b) => ({ ...b, sessions: 1 }));
  const key = freq === "weekly" ? weekKey : (iso: string) => iso.slice(0, 7);
  const out: (OHLCV & { sessions: number })[] = [];
  let cur: (OHLCV & { sessions: number; k: string; ohlcOk: boolean; volOk: boolean }) | null = null;
  const flush = () => {
    if (!cur) return;
    const { k: _k, ohlcOk, volOk, ...b } = cur;
    void _k;
    out.push({ ...b, open: ohlcOk ? b.open : null, high: ohlcOk ? b.high : null, low: ohlcOk ? b.low : null, volume: volOk ? b.volume : null });
  };
  for (const b of bars) {
    const k = key(b.time);
    if (!cur || cur.k !== k) {
      flush();
      cur = { ...b, sessions: 1, k, ohlcOk: b.open !== null && b.high !== null && b.low !== null, volOk: b.volume !== null };
      continue;
    }
    cur.time = b.time;
    cur.close = b.close;
    cur.sessions += 1;
    cur.ohlcOk = cur.ohlcOk && b.open !== null && b.high !== null && b.low !== null;
    if (cur.ohlcOk) {
      cur.high = Math.max(cur.high!, b.high!);
      cur.low = Math.min(cur.low!, b.low!);
    }
    cur.volOk = cur.volOk && b.volume !== null;
    if (cur.volOk) cur.volume = cur.volume! + b.volume!;
  }
  flush();
  return out;
}
