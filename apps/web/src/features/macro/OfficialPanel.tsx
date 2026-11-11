import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { Panel } from "@/components/ui/Panel";
import { ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { api, errorMessage } from "@/lib/api/client";
import { cn } from "@/lib/cn";
import { DASH, formatNumber, formatPercent, formatSessionDate } from "@/lib/format";

interface Row { id: string; name: string; unit: string; show: "level" | "yoy" | "change"; frequency?: string; last_updated?: string; url: string;
  date?: string; value: string | null; vintage?: string; previous?: { date: string; value: string } | null; change?: string | null;
  yoy_pct?: string | null; previous_yoy_pct?: string | null; why?: string }
interface Official { status: string; reason?: string; how?: string; source: string; attribution: string; series?: Row[];
  calendar?: { date: string; release: string; url: string }[]; failed?: string[]; note?: string }

function headline(r: Row) {
  if (r.value === null) return <span className="text-fg-3">{DASH}</span>;
  if (r.show === "yoy" && r.yoy_pct) return <span className="num">{formatPercent(Number(r.yoy_pct))} <span className="text-xs text-fg-3">y/y</span></span>;
  if (r.show === "change" && r.change) return <span className="num">{Number(r.change) > 0 ? "+" : ""}{formatNumber(r.change, 0)} <span className="text-xs text-fg-3">{r.unit}</span></span>;
  return <span className="num">{formatNumber(r.value)}<span className="text-xs text-fg-3"> {r.unit}</span></span>;
}

function delta(r: Row) {
  const v = r.show === "yoy" ? (r.yoy_pct && r.previous_yoy_pct ? Number(r.yoy_pct) - Number(r.previous_yoy_pct) : null) : r.show === "level" && r.change ? Number(r.change) : null;
  if (v === null) return <span className="text-fg-3">{DASH}</span>;
  return <span className={cn("num text-xs", v > 0 ? "text-pos" : v < 0 ? "text-neg" : "text-fg-2")}>{v > 0 ? "+" : ""}{v.toFixed(2)} pp vs previous</span>;
}

/** Terminal T8: US official statistics with release and revision dates, and what is released next (FRED). */
export function OfficialPanel({ className }: { className?: string }) {
  const q = useQuery({ queryKey: ["macro", "official"], queryFn: ({ signal }) => api.get<Official>("/api/macro/official", undefined, signal), staleTime: 60 * 60_000, retry: false });
  const d = q.data;
  return (
    <Panel title="US official statistics" titleId="off-title" className={className} meta={d?.attribution} refreshing={q.isFetching && !q.isLoading}>
      {q.isLoading ? <SkeletonRows rows={6} /> : q.isError || !d ? <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} /> : d.status === "not_configured" ? (
        <InlineNotice>{d.reason} {d.how}</InlineNotice>
      ) : (
        <div className="grid gap-5 lg:grid-cols-3">
          <div tabIndex={0} className="scroll-x scrollbar-thin overflow-x-auto lg:col-span-2">
            <table className="w-full min-w-[32rem] text-[13px]" aria-label="US official statistics from FRED">
              <thead><tr className="border-b border-line-subtle text-xs text-fg-3">
                <th scope="col" className="py-1.5 text-left font-medium">Series</th>
                <th scope="col" className="px-2 text-right font-medium">Latest</th>
                <th scope="col" className="px-2 text-right font-medium">Change</th>
                <th scope="col" className="pl-2 text-right font-medium">Period · vintage</th>
              </tr></thead>
              <tbody>{(d.series ?? []).map((r) => (
                <tr key={r.id} className="border-b border-line-subtle/60">
                  <th scope="row" className="py-1.5 text-left font-normal">
                    <a href={r.url} target="_blank" rel="noopener noreferrer" className="text-fg hover:text-accent-text">{r.name} <ExternalLink className="inline size-3 opacity-60" aria-hidden /></a>
                    <span className="num block text-[11px] text-fg-3">{r.id} · {r.frequency ?? ""}</span>
                  </th>
                  <td className="px-2 text-right">{headline(r)}</td>
                  <td className="px-2 text-right">{delta(r)}</td>
                  <td className="num pl-2 text-right text-xs text-fg-3">{r.date ? formatSessionDate(r.date) : DASH}<span className="block">rev. {r.vintage ? formatSessionDate(r.vintage) : DASH}</span></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <div>
            <h3 className="mb-1 text-xs font-medium text-fg-2">Next releases</h3>
            {d.calendar && d.calendar.length ? (
              <ul className="divide-y divide-line-subtle text-[13px]" aria-label="Upcoming US data releases">
                {d.calendar.slice(0, 12).map((c) => (
                  <li key={`${c.date}${c.release}`} className="flex justify-between gap-3 py-1.5">
                    <a href={c.url} target="_blank" rel="noopener noreferrer" className="min-w-0 truncate text-fg hover:text-accent-text">{c.release}</a>
                    <span className="num shrink-0 text-fg-2">{formatSessionDate(c.date)}</span>
                  </li>
                ))}
              </ul>
            ) : <p className="text-[13px] text-fg-3">No scheduled releases in the next 45 days from the tracked list.</p>}
          </div>
          {d.failed && d.failed.length > 0 && <InlineNotice tone="warn" className="lg:col-span-3">Not loaded: {d.failed.join("; ")}</InlineNotice>}
          <p className="text-xs leading-4 text-fg-3 lg:col-span-3">{d.note}</p>
        </div>
      )}
    </Panel>
  );
}
