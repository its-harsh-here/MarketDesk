import { Link } from "react-router";
import type { Briefing } from "@/lib/api/client";
import { cn } from "@/lib/cn";

const toneDot: Record<string, string> = {
  positive: "bg-pos",
  negative: "bg-neg",
  neutral: "bg-fg-3",
  info: "bg-info",
  warning: "bg-warn",
};

/** Rule-based briefing lines: a tone dot (tone is also stated in the words), the text, and an optional detail. */
export function BriefingItems({ items, className }: { items: Briefing["items"]; className?: string }) {
  return (
    <ul className={cn("space-y-2.5", className)}>
      {items.map((it, i) => (
        <li key={i} className="flex gap-3 text-[13px] leading-5">
          <span className={cn("mt-1.5 size-1.5 shrink-0 rounded-full", toneDot[it.tone] ?? "bg-fg-3")} aria-hidden />
          <div className="min-w-0">
            <p className="text-fg">
              {it.symbol && it.text.startsWith(it.symbol) ? (
                <>
                  <Link className="num font-semibold hover:text-accent-text" to={`/instrument/${encodeURIComponent(it.symbol)}`}>
                    {it.symbol}
                  </Link>
                  {it.text.slice(it.symbol.length)}
                </>
              ) : (
                it.text
              )}
            </p>
            {it.detail && <p className="text-xs text-fg-3">{it.detail}</p>}
          </div>
        </li>
      ))}
    </ul>
  );
}
