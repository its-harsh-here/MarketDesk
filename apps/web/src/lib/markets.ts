import type { Instrument, MarketSession } from "@/lib/api/client";
import { formatInstant } from "@/lib/format";

export const REGION_LABEL: Record<string, string> = { IN: "India", US: "US" };

/** "NSE · IN · INR · EQUITY" — enough to tell apart listings that share a name (e.g. INFY.NS and the INFY ADR). */
export function listingLabel(inst: Pick<Instrument, "exchange" | "country" | "currency" | "kind">): string {
  return [inst.exchange, inst.country, inst.currency, inst.kind && inst.kind !== "EQUITY" ? inst.kind : null].filter(Boolean).join(" · ");
}

export function sessionFor(sessions: MarketSession[] | undefined, country: string | null | undefined): MarketSession | undefined {
  return country ? sessions?.find((s) => s.market === country) : undefined;
}

/** Plain-language session line, with times in the exchange's own timezone. */
export function sessionText(s: MarketSession): string {
  const at = (iso: string | null | undefined) => (iso ? formatInstant(iso, s.timezone) : null);
  if (s.state === "open") return `Open · closes ${at(s.closes_at)}${s.reason.startsWith("Early") ? " (early close)" : ""}`;
  if (s.state === "closed") return `Closed · ${s.reason.replace(/\.$/, "")}${s.next_open ? ` · opens ${at(s.next_open)}` : ""}`;
  return `Status unknown · ${s.reason.replace(/\.$/, "")}`;
}
