import { ChangeText } from "@/components/ui/Change";
import { DASH, formatLargeMoney, formatMoney, formatPercent, formatRatio, formatSessionDate, formatVolume } from "@/lib/format";
import type { Cell, MetricDef } from "./api";

/** Percent metrics that describe a change (shown with sign, arrow and colour); others are levels. */
export const CHANGE_METRICS = new Set(["change_1d_pct", "return_1m_pct", "return_3m_pct", "return_6m_pct", "return_1y_pct", "from_52w_high_pct", "revenue_growth_pct"]);

export function formatMetric(def: MetricDef, v: string | null | undefined, currency: string | null | undefined): string {
  if (v === null || v === undefined) return DASH;
  switch (def.unit) {
    case "currency":
      return def.key === "last_price" ? formatMoney(v, currency) : formatLargeMoney(v, currency);
    case "percent":
      return formatPercent(v, { signed: CHANGE_METRICS.has(def.key) });
    case "multiple":
      return formatRatio(v);
    case "shares":
      return formatVolume(v);
  }
}

/** When and from what a value was observed, in words (for titles and the preview). */
export function cellNote(def: MetricDef, cell: Cell | null | undefined): string {
  if (!cell) return "Not loaded yet: refresh the dataset.";
  if (cell.v === null) return cell.why ?? "Not reported.";
  const parts = [];
  if (cell.from) parts.push(`from ${formatSessionDate(cell.from)}`);
  if (cell.as_of) parts.push(def.source === "statements" ? `fiscal year ending ${formatSessionDate(cell.as_of.slice(0, 10))}` : `as of ${formatSessionDate(cell.as_of.slice(0, 10))}`);
  if (cell.n) parts.push(`${cell.n} daily returns`);
  return parts.join(" · ");
}

export function MetricValue({ def, cell, currency }: { def: MetricDef; cell: Cell | null | undefined; currency: string | null | undefined }) {
  const note = cellNote(def, cell);
  if (!cell || cell.v === null) {
    return (
      <span className="num whitespace-nowrap text-fg-3" title={note}>
        {DASH}
        <span className="sr-only">: {note}</span>
      </span>
    );
  }
  if (def.unit === "percent" && CHANGE_METRICS.has(def.key)) {
    return (
      <span title={`${def.label} ${note ? `· ${note}` : ""}`}>
        <ChangeText percent={cell.v} showAmount={false} />
      </span>
    );
  }
  return (
    <span className="num whitespace-nowrap" title={`${def.label}${note ? ` · ${note}` : ""}`}>
      {formatMetric(def, cell.v, currency)}
    </span>
  );
}

export const UNIT_HINT: Record<MetricDef["unit"], string> = {
  currency: "amount",
  percent: "%",
  multiple: "×",
  shares: "shares",
};

/** Input scales for currency amounts, so a market-cap filter can be typed as "50,000 Cr" or "10 B". */
export const SCALES: Record<"INR" | "USD", { label: string; factor: number }[]> = {
  INR: [
    { label: "₹ Cr", factor: 1e7 },
    { label: "₹ lakh", factor: 1e5 },
    { label: "₹", factor: 1 },
  ],
  USD: [
    { label: "$ B", factor: 1e9 },
    { label: "$ M", factor: 1e6 },
    { label: "$", factor: 1 },
  ],
};

export function defaultScale(metric: string, ccy: "INR" | "USD"): number {
  if (metric === "last_price") return 1;
  if (metric === "avg_value_20d") return ccy === "INR" ? 1e7 : 1e6;
  return ccy === "INR" ? 1e7 : 1e9;
}
