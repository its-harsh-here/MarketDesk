import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { useCountUp, useFlash } from "@/lib/fx";

interface MetricProps {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  caption?: ReactNode; // unit / period / source
  size?: "lg" | "md";
  className?: string;
  title?: string;
}

export function Metric({ label, value, sub, caption, size = "md", className, title }: MetricProps) {
  const plain = typeof value === "string" || typeof value === "number" ? String(value) : null;
  const flash = useFlash(plain);
  const counted = useCountUp(plain);
  return (
    <div className={cn("min-w-0", className)} title={title}>
      <div className="text-xs font-medium text-fg-3">{label}</div>
      <div className={cn("num fx-reveal mt-1 truncate font-semibold text-fg", flash, size === "lg" ? "text-[26px] leading-8" : "text-lg leading-6")}>
        {plain !== null ? (
          <>
            <span aria-hidden>{counted}</span>
            <span className="sr-only">{plain}</span>
          </>
        ) : (
          value
        )}
      </div>
      {sub && <div className="num mt-0.5 text-[13px]">{sub}</div>}
      {caption && <div className="mt-1 text-xs text-fg-3">{caption}</div>}
    </div>
  );
}
