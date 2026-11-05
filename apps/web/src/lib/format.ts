/**
 * Display formatting. Values arrive from the API as decimal strings and are rounded only here.
 * Missing values render as an em dash; callers supply the explanation (tooltip / caption).
 */
export const DASH = "—";

type Num = string | number | null | undefined;

export function toNumber(v: Num): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

const cache = new Map<string, Intl.NumberFormat>();
function nf(key: string, opts: Intl.NumberFormatOptions, locale = "en-IN") {
  const k = locale + key;
  let f = cache.get(k);
  if (!f) {
    f = new Intl.NumberFormat(locale, opts);
    cache.set(k, f);
  }
  return f;
}

export function currencySymbol(ccy: string | null | undefined): string {
  if (ccy === "INR") return "₹";
  if (ccy === "USD") return "$";
  return ccy ? `${ccy} ` : "";
}

/** Price/amount with fixed decimals and Indian digit grouping for INR. */
export function formatMoney(v: Num, ccy: string | null | undefined = "INR", digits = 2): string {
  const n = toNumber(v);
  if (n === null) return DASH;
  const locale = ccy === "INR" || !ccy ? "en-IN" : "en-US";
  const s = nf(`m${digits}`, { minimumFractionDigits: digits, maximumFractionDigits: digits }, locale).format(Math.abs(n));
  return `${n < 0 ? "−" : ""}${currencySymbol(ccy)}${s}`;
}

/** A plain number (no currency) with fixed decimals. */
export function formatNumber(v: Num, digits = 2): string {
  const n = toNumber(v);
  if (n === null) return DASH;
  const s = nf(`n${digits}`, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(Math.abs(n));
  return `${n < 0 ? "−" : ""}${s}`;
}

/** Quantity: up to 6 decimals, no trailing zeros. */
export function formatQuantity(v: Num): string {
  const n = toNumber(v);
  if (n === null) return DASH;
  return nf("q", { minimumFractionDigits: 0, maximumFractionDigits: 6 }).format(n);
}

/** Signed money change, e.g. "+₹12.40" / "−₹3.10". */
export function formatSignedMoney(v: Num, ccy: string | null | undefined = "INR", digits = 2): string {
  const n = toNumber(v);
  if (n === null) return DASH;
  if (n === 0) return formatMoney(0, ccy, digits);
  return `${n > 0 ? "+" : ""}${formatMoney(n, ccy, digits)}`;
}

/** Percent given in percent points (2.5 → "+2.50%"). */
export function formatPercent(v: Num, { signed = true, digits = 2 } = {}): string {
  const n = toNumber(v);
  if (n === null) return DASH;
  const s = nf(`p${digits}`, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(Math.abs(n));
  const sign = n > 0 ? (signed ? "+" : "") : n < 0 ? "−" : "";
  return `${sign}${s}%`;
}

/** A ratio such as P/E or P/B (16.79 → "16.79×"). Never shown as a percent. */
export function formatRatio(v: Num, digits = 2): string {
  const n = toNumber(v);
  if (n === null) return DASH;
  return `${nf(`r${digits}`, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n)}×`;
}

/** Absolute currency amounts at scale: INR in crore (₹3,34,351 Cr), others compact. */
export function formatLargeMoney(v: Num, ccy: string | null | undefined = "INR"): string {
  const n = toNumber(v);
  if (n === null) return DASH;
  if (ccy === "INR") {
    const crore = n / 1e7;
    const digits = crore >= 100 ? 0 : 2;
    return `₹${nf(`c${digits}`, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(crore)} Cr`;
  }
  return `${currencySymbol(ccy)}${nf("cmp", { notation: "compact", maximumFractionDigits: 2 }, "en-US").format(n)}`;
}

/** A count in international compact notation (e.g. 15.4B shares), for SEC filers' share counts. */
export function formatCompact(v: Num): string {
  const n = toNumber(v);
  if (n === null) return DASH;
  return nf("cmp", { notation: "compact", maximumFractionDigits: 2 }, "en-US").format(n);
}

export function formatVolume(v: Num): string {
  const n = toNumber(v);
  if (n === null) return DASH;
  if (n >= 1e7) return `${formatNumber(n / 1e7, 2)} Cr`;
  if (n >= 1e5) return `${formatNumber(n / 1e5, 2)} L`;
  return nf("v", { maximumFractionDigits: 0 }).format(n);
}

export type Tone = "positive" | "negative" | "neutral";
export function tone(v: Num): Tone {
  const n = toNumber(v);
  if (n === null || n === 0) return "neutral";
  return n > 0 ? "positive" : "negative";
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Exchange/session calendar date (YYYY-MM-DD). Not converted between timezones. */
export function formatSessionDate(d: string | null | undefined, withYear = true): string {
  if (!d) return DASH;
  const [y, m, day] = d.slice(0, 10).split("-").map(Number);
  if (!y || !m || !day) return DASH;
  return withYear ? `${day} ${MONTHS[m - 1]} ${y}` : `${day} ${MONTHS[m - 1]}`;
}

/** A UTC instant shown in the display timezone, e.g. "30 Jun 2026, 15:30 IST". */
export function formatInstant(iso: string | null | undefined, tz = "Asia/Kolkata", opts: { seconds?: boolean } = {}) {
  if (!iso) return DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return DASH;
  const parts = new Intl.DateTimeFormat("en-IN", {
    timeZone: tz,
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: opts.seconds ? "2-digit" : undefined,
    hour12: false,
    timeZoneName: "short",
  }).formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const time = [get("hour"), get("minute"), opts.seconds ? get("second") : ""].filter(Boolean).join(":");
  return `${get("day")} ${get("month")} ${get("year")}, ${time} ${get("timeZoneName")}`.trim();
}

export function formatRelative(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return DASH;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return DASH;
  const s = Math.round((now - t) / 1000);
  if (s < 0) return "just now";
  if (s < 45) return "just now";
  if (s < 90) return "1 min ago";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 36) return `${h} h ago`;
  return `${Math.round(h / 24)} d ago`;
}

export function todayIso(tz = "Asia/Kolkata"): string {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" })
    .format(new Date());
  return parts;
}
