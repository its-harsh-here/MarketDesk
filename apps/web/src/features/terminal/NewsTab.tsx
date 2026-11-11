import { useQuery } from "@tanstack/react-query";
import { ExternalLink, FileText, Megaphone, Newspaper, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { useDialogs } from "@/app/dialogs";
import { Pill } from "@/components/ui/Badges";
import { Button } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/States";
import { api, errorMessage } from "@/lib/api/client";
import { cn } from "@/lib/cn";
import { formatInstant, formatRelative, formatSessionDate } from "@/lib/format";
import { usePrefs } from "@/features/settings/api";

type Category = "filing" | "release" | "news";
export interface StreamItem {
  at: string | null;
  precision: "date" | "instant" | "unknown";
  category: Category;
  headline: string;
  form?: string;
  items?: { code: string; label: string }[];
  important: boolean;
  source: "SEC EDGAR" | "provider";
  publisher: string | null;
  url: string | null;
  index_url?: string | null;
  kind?: string;
  related?: string[];
  broad?: boolean;
}
interface Stream {
  symbol: string;
  as_of: string;
  items: StreamItem[];
  counts: Record<Category, number>;
  fetched_at: string | null;
  sources: string[];
  notes: string[];
  policy: string;
}

export function useNewsStream(symbol: string) {
  return useQuery({
    queryKey: ["terminal", "news", symbol],
    queryFn: ({ signal }) => api.get<Stream>("/api/terminal/news", { symbol }, signal),
    staleTime: 10 * 60_000,
    retry: false,
  });
}

const ICON = { filing: FileText, release: Megaphone, news: Newspaper } as const;
const LABEL: Record<Category, string> = { filing: "Filing", release: "Release", news: "Headline" };
type Filter = "all" | Category | "important";

function dayKey(it: StreamItem) {
  return it.at ? it.at.slice(0, 10) : "undated";
}

/** Terminal T5: filings (plain-language 8-K items) and provider headlines, newest first, grouped by day. */
export function NewsTab({ symbol }: { symbol: string }) {
  const q = useNewsStream(symbol);
  const { open } = useDialogs();
  const { data: prefs } = usePrefs();
  const tz = prefs?.display_timezone;
  const [filter, setFilter] = useState<Filter>("all");
  const d = q.data;
  const shown = useMemo(
    () => (d?.items ?? []).filter((i) => filter === "all" || (filter === "important" ? i.important : i.category === filter)),
    [d, filter],
  );
  const groups = useMemo(() => {
    const g = new Map<string, StreamItem[]>();
    for (const it of shown) g.set(dayKey(it), [...(g.get(dayKey(it)) ?? []), it]);
    return [...g.entries()];
  }, [shown]);
  const options: { value: Filter; label: string }[] = [
    { value: "all", label: `All ${d ? d.items.length : ""}`.trim() },
    { value: "news", label: `Headlines ${d?.counts.news ?? ""}`.trim() },
    { value: "release", label: `Releases ${d?.counts.release ?? ""}`.trim() },
    { value: "filing", label: `Filings ${d?.counts.filing ?? ""}`.trim() },
    { value: "important", label: "Key events" },
  ];
  return (
    <>
      <Panel title="News and filings" titleId="news-title" className="lg:col-span-8" refreshing={q.isFetching && !q.isLoading} wrapHeader
        meta={d?.fetched_at ? `headlines fetched ${formatRelative(d.fetched_at)}` : undefined}
        actions={<Segmented label="Show" value={filter} onChange={setFilter} options={options} />}>
        {q.isLoading ? (
          <SkeletonRows rows={10} />
        ) : q.isError || !d ? (
          <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
        ) : !shown.length ? (
          <EmptyState title={d.items.length ? "Nothing of this kind" : "No headlines or filings"}>
            {d.items.length ? "Choose another filter to see the rest of the stream." : d.notes[0] ?? "The sources available for this listing returned nothing."}
          </EmptyState>
        ) : (
          <ol className="space-y-4" aria-label={`News and filings for ${symbol}, newest first`}>
            {groups.map(([day, list]) => (
              <li key={day}>
                <h3 className="sticky top-16 z-10 mb-1 inline-block rounded-full bg-elevated/80 px-2.5 py-0.5 text-xs font-medium text-fg-2 backdrop-blur">
                  {day === "undated" ? "Undated" : formatSessionDate(day)}
                </h3>
                <ul className="divide-y divide-line-subtle">
                  {list.map((it, i) => {
                    const Icon = ICON[it.category];
                    return (
                      <li key={`${it.url ?? it.headline}${i}`} className="group flex gap-3 py-2.5">
                        <span className={cn("mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border border-line-subtle transition-transform group-hover:scale-110",
                          it.category === "news" ? "text-info" : it.category === "release" ? "text-accent-text" : "text-fg-2")} aria-hidden>
                          <Icon className="size-4" />
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                            {it.url ? (
                              <a href={it.url} target="_blank" rel="noopener noreferrer" className="text-[14px] font-medium text-fg hover:text-accent-text">
                                {it.headline}
                                <ExternalLink className="ml-1 inline size-3 align-baseline opacity-60" aria-hidden />
                                <span className="sr-only"> (opens the {it.source === "SEC EDGAR" ? "filing" : "publisher's page"})</span>
                              </a>
                            ) : (
                              <span className="text-[14px] font-medium text-fg">{it.headline}</span>
                            )}
                            {it.important && <Pill tone="warn" className="py-0">key event</Pill>}
                          </div>
                          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-fg-3">
                            <span>{LABEL[it.category]}</span>
                            {it.form && <span className="num">· {it.form}</span>}
                            {it.items && it.items.length > 0 && <span className="num">· items {it.items.map((x) => x.code).join(", ")}</span>}
                            <span>· {it.publisher ?? "unknown publisher"}</span>
                            {it.broad && <span title="This story tags many symbols; it may be about the market rather than this company.">· broad market story</span>}
                            {!it.broad && it.related && it.related.length > 0 && <span className="num">· also {it.related.join(", ")}</span>}
                            {it.at && it.precision === "instant" && <span className="num">· {formatInstant(it.at, tz)}</span>}
                            {it.precision === "date" && <span>· filing date</span>}
                            {it.index_url && it.index_url !== it.url && (
                              <a href={it.index_url} target="_blank" rel="noopener noreferrer" className="underline decoration-fg-3/40 underline-offset-2 hover:text-fg-2">filing index</a>
                            )}
                          </div>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </li>
            ))}
          </ol>
        )}
      </Panel>
      <Panel title="About this stream" titleId="news-about" className="lg:col-span-4 lg:self-start">
        <div className="space-y-3 text-[13px] text-fg-2">
          <Button size="sm" variant="primary" icon={<Sparkles className="size-4" aria-hidden />} onClick={() => open({ kind: "ai", symbol, task: "catalysts" })}>
            Cited AI summary of recent filings
          </Button>
          <p className="text-xs text-fg-3">The AI reads the filings it retrieves and cites each one; it is model output, not a source.</p>
          {d && (
            <>
              <ul className="space-y-1 text-xs text-fg-3">{d.sources.map((s) => <li key={s}>{s}</li>)}</ul>
              {d.notes.map((n) => <p key={n} className="text-xs text-fg-3">{n}</p>)}
              <p className="text-xs text-fg-3">{d.policy}</p>
            </>
          )}
        </div>
      </Panel>
    </>
  );
}
