import { ArrowDown, ArrowUp, Minus } from "lucide-react";
import { DASH, formatPercent, formatSignedMoney, tone, toNumber } from "@/lib/format";
import { cn } from "@/lib/cn";

const toneClass = { positive: "text-pos", negative: "text-neg", neutral: "text-fg-2" } as const;

/** Gain/loss with colour AND sign AND arrow (never colour alone). */
export function ChangeText({
  value,
  percent,
  currency = "INR",
  className,
  showAmount = true,
  showIcon = true,
}: {
  value?: string | null;
  percent?: string | null;
  currency?: string | null;
  className?: string;
  showAmount?: boolean;
  showIcon?: boolean;
}) {
  const t = tone(percent ?? value);
  if (toNumber(percent) === null && toNumber(value) === null) {
    return <span className={cn("num text-fg-3", className)}>{DASH}</span>;
  }
  const Icon = t === "positive" ? ArrowUp : t === "negative" ? ArrowDown : Minus;
  const word = t === "positive" ? "up" : t === "negative" ? "down" : "unchanged";
  return (
    <span className={cn("num inline-flex items-center gap-1 whitespace-nowrap", toneClass[t], className)}>
      {showIcon && <Icon aria-hidden className="size-3.5 shrink-0" strokeWidth={2.4} />}
      <span className="sr-only">{word} </span>
      {showAmount && value !== undefined && <span>{formatSignedMoney(value, currency)}</span>}
      {percent !== undefined && <span>{showAmount && value !== undefined ? `(${formatPercent(percent)})` : formatPercent(percent)}</span>}
    </span>
  );
}

export function PnlText({ value, currency = "INR", className }: { value: string | null | undefined; currency?: string; className?: string }) {
  const t = tone(value);
  return <span className={cn("num whitespace-nowrap", toneClass[t], className)}>{formatSignedMoney(value, currency)}</span>;
}
