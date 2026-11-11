import { Link } from "react-router";
import type { DataMeta } from "@/lib/api/client";
import { formatInstant, formatRelative } from "@/lib/format";
import { cn } from "@/lib/cn";
import { Tooltip } from "./Tooltip";
import { usePrefs } from "@/features/settings/api";

const STATUS: Record<string, { label: string; dot: string; text: string; explain: string }> = {
  sample: { label: "Sample", dot: "bg-info", text: "text-info", explain: "Fictitious sample data from the fixed dataset. Not a live quotation." },
  available: { label: "Fetched", dot: "bg-pos", text: "text-fg-2", explain: "Fetched from the provider for this request. A recent fetch does not prove the quotation itself is recent; check the market time." },
  cached: { label: "Cached", dot: "bg-pos/70", text: "text-fg-2", explain: "Served from the server cache within its refresh window." },
  stale: { label: "Stale", dot: "bg-warn", text: "text-warn", explain: "The provider failed, so this is the last successful result." },
  missing: { label: "No data", dot: "bg-fg-3", text: "text-fg-3", explain: "The provider has no data for this request." },
  unsupported: { label: "Unsupported", dot: "bg-fg-3", text: "text-fg-3", explain: "Not supported by the active provider." },
  unavailable: { label: "Unavailable", dot: "bg-neg", text: "text-neg", explain: "The provider could not be reached and nothing usable is cached." },
};

export function statusInfo(status: string) {
  return STATUS[status] ?? STATUS.missing;
}

export function FreshnessBadge({ meta, compact = false, className }: { meta: DataMeta | null | undefined; compact?: boolean; className?: string }) {
  const { data: prefs } = usePrefs();
  const tz = prefs?.display_timezone ?? "Asia/Kolkata";
  if (!meta) return null;
  const s = statusInfo(meta.status);
  const content = (
    <div className="space-y-1">
      <div className="font-semibold">{s.label}</div>
      <div className="text-fg-2">{meta.message ?? s.explain}</div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 pt-1 text-fg-2">
        <dt className="text-fg-3">Source</dt>
        <dd>{meta.source === "fixture" ? "Sample dataset" : meta.source === "yahoo" ? "Yahoo Finance (yfinance)" : meta.source}</dd>
        <dt className="text-fg-3">Market time</dt>
        <dd>{formatInstant(meta.market_time, tz)}</dd>
        <dt className="text-fg-3">Fetched</dt>
        <dd>{meta.fetched_at ? `${formatInstant(meta.fetched_at, tz, { seconds: true })}` : "—"}</dd>
        {meta.currency && (
          <>
            <dt className="text-fg-3">Currency</dt>
            <dd>{meta.currency}</dd>
          </>
        )}
        {meta.timezone && (
          <>
            <dt className="text-fg-3">Exchange tz</dt>
            <dd>{meta.timezone}</dd>
          </>
        )}
      </dl>
    </div>
  );
  return (
    <Tooltip content={content}>
      <button
        type="button"
        className={cn("inline-flex items-center gap-1.5 rounded-full text-xs whitespace-nowrap", s.text, className)}
        aria-label={`Data status: ${s.label}. ${meta.message ?? s.explain}`}
      >
        <span className={cn("size-1.5 shrink-0 rounded-full", s.dot)} aria-hidden />
        {!compact && <span>{s.label}</span>}
        {!compact && meta.status !== "sample" && meta.fetched_at && <span className="text-fg-3">· {formatRelative(meta.fetched_at)}</span>}
      </button>
    </Tooltip>
  );
}

export function InstrumentBadge({
  symbol,
  name,
  exchange,
  link = true,
  className,
}: {
  symbol: string;
  name?: string | null;
  exchange?: string | null;
  link?: boolean;
  className?: string;
}) {
  const body = (
    <span className="flex min-w-0 flex-col">
      <span className="flex items-center gap-1.5">
        <span className="num truncate text-[13px] font-semibold text-fg">{symbol}</span>
        {exchange && <span className="rounded border border-line-subtle px-1 text-[11px] leading-4 text-fg-3">{exchange}</span>}
      </span>
      {name && <span className="truncate text-xs text-fg-3">{name}</span>}
    </span>
  );
  if (!link) return <span className={cn("min-w-0", className)}>{body}</span>;
  return (
    <Link to={`/instrument/${encodeURIComponent(symbol)}`} className={cn("min-w-0 rounded hover:[&_.num]:text-accent-text", className)}>
      {body}
    </Link>
  );
}

export function Pill({ children, tone = "neutral", className }: { children: React.ReactNode; tone?: "neutral" | "info" | "warn" | "pos" | "neg" | "accent"; className?: string }) {
  const tones = {
    neutral: "border-line text-fg-2",
    info: "border-info/40 bg-info-soft text-info",
    warn: "border-warn/40 bg-warn-soft text-warn",
    pos: "border-pos/40 bg-pos-soft text-pos",
    neg: "border-neg/40 bg-neg-soft text-neg",
    accent: "border-accent/40 bg-accent-soft text-accent-text",
  };
  return <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap", tones[tone], className)}>{children}</span>;
}

/** Marks a price that comes from the streaming IEX trade feed rather than the polled quote. */
export function LiveBadge({ time, compact = false }: { time: string; compact?: boolean }) {
  const t = new Date(time).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  const title = `Last trade on IEX at ${t} New York time (streamed via Alpaca). IEX is a single exchange, not consolidated market data; change is measured from the provider's previous close.`;
  return (
    <span title={title} aria-label={`Live IEX trade at ${t} New York time`} className="inline-flex items-center gap-1 rounded-full border border-pos/40 bg-pos/10 px-1.5 py-0.5 text-[11px] font-medium leading-none text-pos">
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-pos motion-safe:animate-pulse" />
      {compact ? "IEX" : `IEX live · ${t}`}
    </span>
  );
}
