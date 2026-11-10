/** Technical indicators computed from daily closes (pure; null until enough bars exist). Standard textbook
 * definitions: SMA, EMA seeded with the first SMA, Bollinger (SMA ± k·population SD), Wilder's RSI, MACD 12/26/9. */
export type Series = (number | null)[];

export function sma(v: number[], n: number): Series {
  const out: Series = [];
  let sum = 0;
  for (let i = 0; i < v.length; i++) {
    sum += v[i];
    if (i >= n) sum -= v[i - n];
    out.push(i >= n - 1 ? sum / n : null);
  }
  return out;
}

export function ema(v: number[], n: number): Series {
  const out: Series = [];
  const k = 2 / (n + 1);
  let prev: number | null = null;
  for (let i = 0; i < v.length; i++) {
    if (i < n - 1) out.push(null);
    else if (prev === null) {
      prev = v.slice(0, n).reduce((a, b) => a + b, 0) / n;
      out.push(prev);
    } else {
      prev = v[i] * k + prev * (1 - k);
      out.push(prev);
    }
  }
  return out;
}

export function bollinger(v: number[], n = 20, k = 2): { mid: Series; upper: Series; lower: Series } {
  const mid = sma(v, n);
  const upper: Series = [];
  const lower: Series = [];
  for (let i = 0; i < v.length; i++) {
    const m = mid[i];
    if (m === null) {
      upper.push(null);
      lower.push(null);
      continue;
    }
    const win = v.slice(i - n + 1, i + 1);
    const sd = Math.sqrt(win.reduce((a, x) => a + (x - m) ** 2, 0) / n);
    upper.push(m + k * sd);
    lower.push(m - k * sd);
  }
  return { mid, upper, lower };
}

/** Wilder's RSI: first average over n changes, then smoothed (avg = (prev·(n−1) + x) / n). */
export function rsi(v: number[], n = 14): Series {
  const out: Series = v.map(() => null);
  if (v.length <= n) return out;
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= n; i++) {
    const d = v[i] - v[i - 1];
    gain += Math.max(d, 0);
    loss += Math.max(-d, 0);
  }
  gain /= n;
  loss /= n;
  const val = () => (loss === 0 ? (gain === 0 ? 50 : 100) : 100 - 100 / (1 + gain / loss));
  out[n] = val();
  for (let i = n + 1; i < v.length; i++) {
    const d = v[i] - v[i - 1];
    gain = (gain * (n - 1) + Math.max(d, 0)) / n;
    loss = (loss * (n - 1) + Math.max(-d, 0)) / n;
    out[i] = val();
  }
  return out;
}

export function macd(v: number[], fast = 12, slow = 26, signal = 9): { macd: Series; signal: Series; hist: Series } {
  const f = ema(v, fast);
  const s = ema(v, slow);
  const line: Series = v.map((_, i) => (f[i] !== null && s[i] !== null ? f[i]! - s[i]! : null));
  const start = line.findIndex((x) => x !== null);
  const sig: Series = v.map(() => null);
  if (start >= 0) {
    const tail = ema(line.slice(start) as number[], signal);
    tail.forEach((x, j) => (sig[start + j] = x));
  }
  return { macd: line, signal: sig, hist: line.map((x, i) => (x !== null && sig[i] !== null ? x - sig[i]! : null)) };
}

export type IndicatorKey = "sma20" | "sma50" | "sma200" | "ema20" | "bb" | "rsi" | "macd";
export const INDICATORS: { key: IndicatorKey; label: string; pane: "price" | "lower"; help: string }[] = [
  { key: "sma20", label: "SMA 20", pane: "price", help: "Simple moving average of the last 20 closes" },
  { key: "sma50", label: "SMA 50", pane: "price", help: "Simple moving average of the last 50 closes" },
  { key: "sma200", label: "SMA 200", pane: "price", help: "Simple moving average of the last 200 closes (needs a 1Y+ range)" },
  { key: "ema20", label: "EMA 20", pane: "price", help: "Exponential moving average, 20 closes" },
  { key: "bb", label: "Bollinger 20, 2", pane: "price", help: "SMA 20 ± 2 standard deviations" },
  { key: "rsi", label: "RSI 14", pane: "lower", help: "Wilder's relative strength index, 14 sessions (70/30 guides)" },
  { key: "macd", label: "MACD 12/26/9", pane: "lower", help: "EMA12 − EMA26, its 9-session EMA signal, and the difference" },
];
