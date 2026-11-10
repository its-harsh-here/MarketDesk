import { useMemo } from "react";
import { formatSessionDate, toNumber } from "@/lib/format";

/** Small trend line drawn from real provider closes (never random). Decorative for AT; the row has the figures. */
export function Sparkline({ points, width = 96, height = 28, label }: { points: { date: string; close: string }[]; width?: number; height?: number; label?: string }) {
  const path = useMemo(() => {
    const vals = points.map((p) => toNumber(p.close)).filter((v): v is number => v !== null);
    if (vals.length < 2) return null;
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const span = max - min || 1;
    const step = (width - 2) / (vals.length - 1);
    const d = vals.map((v, i) => `${i === 0 ? "M" : "L"}${(1 + i * step).toFixed(2)},${(1 + (height - 2) * (1 - (v - min) / span)).toFixed(2)}`).join(" ");
    return { d, area: `${d} L${(1 + (vals.length - 1) * step).toFixed(2)},${height} L1,${height} Z`, up: vals[vals.length - 1] >= vals[0] };
  }, [points, width, height]);
  if (!path) return <span className="text-xs text-fg-3">—</span>;
  const first = points[0];
  const last = points[points.length - 1];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label ?? `Trend from ${formatSessionDate(first.date)} to ${formatSessionDate(last.date)}`} className="fx-spark block overflow-visible" style={{ color: path.up ? "var(--positive)" : "var(--negative)" }}>
      <path className="area" d={path.area} fill="currentColor" opacity={0.12} stroke="none" />
      <path className="line" pathLength={1} d={path.d} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
