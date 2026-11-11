import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { Panel } from "@/components/ui/Panel";
import { ErrorState, SkeletonRows } from "@/components/ui/States";
import { api, errorMessage } from "@/lib/api/client";
import { cn } from "@/lib/cn";
import { DASH, formatNumber, formatPercent } from "@/lib/format";

interface Item { symbol: string; label: string; kind: "level" | "yield"; value: string | null; why?: string; as_of?: string; d1?: number | null; m1?: number | null; correlation?: number | null; n?: number }
interface Ctx { symbol: string; items: Item[]; note: string }

const chg = (v: number | null | undefined, kind: Item["kind"]) => {
  if (v === null || v === undefined) return <span className="text-fg-3">{DASH}</span>;
  const text = kind === "yield" ? `${v > 0 ? "+" : ""}${v.toFixed(2)} pp` : formatPercent(v);
  return <span className={cn("num", v > 0 ? "text-pos" : v < 0 ? "text-neg" : "text-fg-2")}>{text}</span>;
};

/** Terminal T8: what the market around this security is doing, and how closely the security has moved with it. */
export function ContextPanel({ symbol, className }: { symbol: string; className?: string }) {
  const q = useQuery({
    queryKey: ["terminal", "context", symbol],
    queryFn: ({ signal }) => api.get<Ctx>("/api/terminal/context", { symbol }, signal),
    staleTime: 10 * 60_000,
    retry: false,
  });
  const d = q.data;
  return (
    <Panel title="Market context" titleId="ctx-title" className={className} refreshing={q.isFetching && !q.isLoading}
      actions={<Link to="/macro" className="text-xs text-fg-2 hover:text-fg">Macro</Link>}>
      {q.isLoading ? <SkeletonRows rows={5} /> : q.isError || !d ? <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} /> : (
        <div className="space-y-2">
          <div tabIndex={0} className="scroll-x scrollbar-thin overflow-x-auto">
          <table className="w-full min-w-[22rem] text-[13px]" aria-label={`Market context for ${symbol}`}>
            <thead><tr className="border-b border-line-subtle text-xs text-fg-3">
              <th scope="col" className="py-1.5 text-left font-medium">Series</th>
              <th scope="col" className="px-2 text-right font-medium">Last</th>
              <th scope="col" className="px-2 text-right font-medium">1D</th>
              <th scope="col" className="px-2 text-right font-medium">1M</th>
              <th scope="col" className="pl-2 text-right font-medium" title="Correlation of daily changes with this security over the last year">Co-move 1Y</th>
            </tr></thead>
            <tbody>{d.items.map((it) => (
              <tr key={it.symbol} className="border-b border-line-subtle/60">
                <th scope="row" className="py-1.5 text-left font-normal">
                  <Link to={`/instrument/${encodeURIComponent(it.symbol)}`} className="text-fg hover:text-accent-text">{it.label}</Link>
                  <span className="num block text-[11px] text-fg-3">{it.symbol}</span>
                </th>
                {it.value === null ? (
                  <td colSpan={4} className="text-right text-xs text-fg-3">{it.why}</td>
                ) : (
                  <>
                    <td className="num px-2 text-right">{formatNumber(it.value)}{it.kind === "yield" ? "%" : ""}</td>
                    <td className="px-2 text-right">{chg(it.d1, it.kind)}</td>
                    <td className="px-2 text-right">{chg(it.m1, it.kind)}</td>
                    <td className="pl-2 text-right">
                      {it.correlation === null || it.correlation === undefined ? <span className="text-xs text-fg-3" title={`${it.n ?? 0} paired days`}>{DASH}</span> : (
                        <span className="inline-flex items-center justify-end gap-1.5" title={`${it.n} paired days`}>
                          <span aria-hidden className="relative h-1.5 w-10 rounded-full bg-elevated">
                            <span className="absolute inset-y-0 left-1/2 w-px bg-line" />
                            <span className={cn("absolute inset-y-0 rounded-full", it.correlation >= 0 ? "left-1/2 bg-info" : "right-1/2 bg-warn")} style={{ width: `${Math.abs(it.correlation) * 50}%` }} />
                          </span>
                          <span className="num text-xs">{it.correlation.toFixed(2)}</span>
                        </span>
                      )}
                    </td>
                  </>
                )}
              </tr>
            ))}</tbody>
          </table>
          </div>
          <p className="text-xs leading-4 text-fg-3">{d.note}</p>
        </div>
      )}
    </Panel>
  );
}
