import { useQuery } from "@tanstack/react-query";
import { ArrowRight, BookOpen, Briefcase, FileUp, ListChecks, Plus, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { MarketStrip } from "@/app/Shell";
import { useDialogs } from "@/app/dialogs";
import { Panel } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Form";
import { EmptyState, ErrorState, InlineNotice, Skeleton, SkeletonRows } from "@/components/ui/States";
import { Pill } from "@/components/ui/Badges";
import { Metric } from "@/components/ui/Metric";
import { PnlText } from "@/components/ui/Change";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage, type Briefing } from "@/lib/api/client";
import { formatInstant, formatMoney, formatPercent, formatSessionDate } from "@/lib/format";
import { cn } from "@/lib/cn";
import { useMediaQuery } from "@/lib/hooks";
import { ChartPanel } from "@/features/market/ChartPanel";
import { useSnapshots } from "@/features/market/api";
import { usePatchPrefs, usePrefs, useSession, useStatus } from "@/features/settings/api";
import { useWatchlistMutations, useWatchlists } from "@/features/watchlists/api";
import { WatchlistTable } from "@/features/watchlists/WatchlistTable";
import { BriefingItems } from "@/features/briefing/BriefingItems";
import { usePortfolioSummary } from "@/features/portfolio/api";
import { useJournal } from "@/features/journal/api";
import type { SortState } from "@/components/ui/DataTable";

function useBriefing() {
  return useQuery({ queryKey: ["briefing"], queryFn: () => api.get<Briefing>("/api/briefing"), refetchInterval: 120_000 });
}

function BriefingPanel({ className }: { className?: string }) {
  const q = useBriefing();
  const { data: prefs } = usePrefs();
  return (
    <Panel
      title="Daily briefing"
      titleId="briefing-title"
      className={className}
      refreshing={q.isFetching && !q.isLoading}
      meta={q.data ? `Rule-based · ${formatInstant(q.data.generated_at, prefs?.display_timezone)}` : undefined}
    >
      {q.isLoading ? (
        <SkeletonRows rows={4} />
      ) : q.isError ? (
        <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
      ) : (
        <>
          <BriefingItems items={q.data!.items} />
          {q.data!.data_status === "stale" && <InlineNotice tone="warn" className="mt-3">Some figures above are from stale data.</InlineNotice>}
          <p className="mt-4 text-xs leading-4 text-fg-3">{q.data!.method}</p>
        </>
      )}
    </Panel>
  );
}

function PortfolioSnapshot({ className }: { className?: string }) {
  const q = usePortfolioSummary();
  const { open } = useDialogs();
  const { data: session } = useSession();
  const s = q.data;
  const hasHoldings = Boolean(s && s.holdings.length > 0);
  return (
    <Panel
      title="Portfolio · INR account"
      titleId="pf-title"
      className={className}
      actions={
        <Link to="/portfolio" className="inline-flex items-center gap-1 rounded px-1 text-xs text-fg-2 hover:text-fg">
          Open <ArrowRight className="size-3" aria-hidden />
        </Link>
      }
    >
      {q.isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-8 w-40" />
          <Skeleton className="h-4 w-28" />
          <Skeleton className="h-4 w-32" />
        </div>
      ) : q.isError ? (
        <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
      ) : !hasHoldings ? (
        <EmptyState
          icon={<Briefcase aria-hidden />}
          title={s?.has_transactions ? "No open holdings" : "No transactions yet"}
          className="py-6"
          actions={
            !session?.read_only && (
              <>
                <Button size="sm" variant="primary" icon={<Plus className="size-3.5" aria-hidden />} onClick={() => open({ kind: "transaction" })}>
                  Add transaction
                </Button>
                <Button size="sm" icon={<FileUp className="size-3.5" aria-hidden />} onClick={() => open({ kind: "import" })}>
                  Import CSV
                </Button>
              </>
            )
          }
        >
          {s?.has_transactions ? `Cash ${formatMoney(s.cash)}.` : "Portfolio value appears here once you record holdings."}
        </EmptyState>
      ) : (
        <div className="space-y-4">
          <Metric
            size="lg"
            label={s!.complete ? "Total equity (cash + holdings)" : "Partial equity — valuation incomplete"}
            value={formatMoney(s!.complete ? s!.total_equity : s!.partial_equity)}
            caption={
              <span>
                INR · marked at last observed prices{s!.stale_marks.length ? " (some stale)" : ""}
                {!s!.complete && <span className="block text-warn">Excludes {s!.missing_marks.join(", ")} (no usable price)</span>}
              </span>
            }
          />
          <dl className="grid grid-cols-2 gap-3 text-[13px]">
            <div>
              <dt className="text-xs text-fg-3">Unrealized P&amp;L</dt>
              <dd className="mt-0.5">{s!.unrealized_pnl !== null ? <PnlText value={s!.unrealized_pnl} /> : <span className="text-fg-3">—</span>}</dd>
            </div>
            <div>
              <dt className="text-xs text-fg-3">Realized P&amp;L</dt>
              <dd className="mt-0.5"><PnlText value={s!.realized_pnl} /></dd>
            </div>
            <div>
              <dt className="text-xs text-fg-3">Cash</dt>
              <dd className="num mt-0.5 text-fg">{formatMoney(s!.cash)}</dd>
            </div>
            <div>
              <dt className="text-xs text-fg-3">Holdings</dt>
              <dd className="num mt-0.5 text-fg">{s!.holdings.length}</dd>
            </div>
          </dl>
        </div>
      )}
    </Panel>
  );
}

function JournalActivity({ className }: { className?: string }) {
  const q = useJournal({}, 5);
  const { open } = useDialogs();
  const { data: session } = useSession();
  return (
    <Panel
      title="Recent journal"
      titleId="journal-title"
      className={className}
      actions={
        <Link to="/journal" className="inline-flex items-center gap-1 rounded px-1 text-xs text-fg-2 hover:text-fg">
          All notes <ArrowRight className="size-3" aria-hidden />
        </Link>
      }
    >
      {q.isLoading ? (
        <SkeletonRows rows={3} />
      ) : q.isError ? (
        <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
      ) : !q.data!.items.length ? (
        <EmptyState
          icon={<BookOpen aria-hidden />}
          title="No journal notes"
          className="py-6"
          actions={!session?.read_only && <Button size="sm" onClick={() => open({ kind: "journal" })}>New note</Button>}
        >
          Record a thesis, its risks and what would prove it wrong.
        </EmptyState>
      ) : (
        <ul className="divide-y divide-line-subtle">
          {q.data!.items.map((e) => (
            <li key={e.id} className="py-2.5 first:pt-0 last:pb-0">
              <div className="flex items-center gap-2 text-xs text-fg-3">
                <Link to={`/instrument/${encodeURIComponent(e.symbol)}`} className="num font-semibold text-fg-2 hover:text-accent-text">
                  {e.symbol}
                </Link>
                <span>{formatSessionDate(e.entry_date)}</span>
                {e.review_due && <Pill tone="accent" className="py-0">Review due</Pill>}
              </div>
              <Link to={`/journal?symbol=${encodeURIComponent(e.symbol)}`} className="mt-0.5 block truncate text-[13px] text-fg hover:underline">
                {e.title}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export function OverviewPage() {
  const { data: lists, isLoading: listsLoading, isError: listsError, error, refetch } = useWatchlists();
  const { data: prefs } = usePrefs();
  const patch = usePatchPrefs();
  const { data: status } = useStatus();
  const { data: session } = useSession();
  const { open } = useDialogs();
  const { starter } = useWatchlistMutations();
  const toast = useToast();
  const [sort, setSort] = useState<SortState | null>(null);
  const sideBySide = useMediaQuery("(min-width: 1280px)");
  const readOnly = Boolean(session?.read_only);

  const wl = lists?.find((l) => l.id === prefs?.default_watchlist_id) ?? lists?.[0];
  const symbols = useMemo(() => wl?.items.map((i) => i.symbol) ?? [], [wl]);
  const snaps = useSnapshots(symbols);
  const benchmarks = status?.benchmarks ?? [];
  const chartSymbol = prefs?.chart_symbol ?? symbols[0] ?? benchmarks[0] ?? null;
  const chartOptions = Array.from(new Set([...(chartSymbol ? [chartSymbol] : []), ...symbols, ...benchmarks]));
  const chartSnap = snaps.data?.find((s) => s.symbol === chartSymbol);

  const sortState = sort ?? (wl && wl.sort_key !== "manual" ? { key: wl.sort_key, dir: wl.sort_dir as "asc" | "desc" } : null);

  return (
    <>
      <MarketStrip />
      {status?.storage.warning && (
        <div className="px-4 pt-4 md:px-6">
          <InlineNotice tone="warn">
            <strong className="font-semibold">Your data is not on a persistent disk.</strong> {status.storage.message}
          </InlineNotice>
        </div>
      )}
      <div className="grid grid-cols-1 gap-4 p-4 md:p-6 lg:grid-cols-12 lg:gap-5">
        {chartSymbol ? (
          <ChartPanel
            key={chartSymbol}
            className="lg:col-span-12 xl:col-span-7 min-[87.5rem]:col-span-8"
            symbol={chartSymbol}
            currency={chartSnap?.instrument.currency ?? "INR"}
            height={340}
            title={
              <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <Link to={`/instrument/${encodeURIComponent(chartSymbol)}`} className="num hover:text-accent-text">
                  {chartSymbol}
                </Link>
                {chartSnap?.quote && (
                  <span className="num whitespace-nowrap font-normal text-fg-2">
                    {formatMoney(chartSnap.quote.last_price, chartSnap.instrument.currency)}{" "}
                    <span className={cn(Number(chartSnap.quote.change_percent) > 0 ? "text-pos" : Number(chartSnap.quote.change_percent) < 0 ? "text-neg" : "")}>
                      {formatPercent(chartSnap.quote.change_percent)}
                    </span>
                  </span>
                )}
              </span>
            }
            headerExtra={
              <label className="flex items-center gap-2 text-xs text-fg-3">
                <span className="max-sm:sr-only">Chart</span>
                <Select
                  aria-label="Chart symbol"
                  className="h-8 w-40 text-[13px] max-md:h-10"
                  value={chartSymbol}
                  disabled={readOnly}
                  title={readOnly ? "Preference changes are disabled in the read-only demo" : undefined}
                  onChange={(e) => patch.mutate({ chart_symbol: e.target.value }, { onError: (err) => toast("error", errorMessage(err)) })}
                >
                  {chartOptions.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </Select>
              </label>
            }
          />
        ) : (
          <Panel title="Chart" className="lg:col-span-12 xl:col-span-7 min-[87.5rem]:col-span-8">
            {listsLoading ? <Skeleton className="h-[340px] w-full" /> : <EmptyState title="Choose an instrument">Add symbols to a watchlist to chart them here.</EmptyState>}
          </Panel>
        )}

        <Panel
          title="Watchlist"
          titleId="wl-title"
          className="lg:col-span-12 xl:col-span-5 min-[87.5rem]:col-span-4"
          refreshing={snaps.isFetching && !snaps.isLoading}
          bodyClassName="p-0"
          meta={wl ? `${wl.items.length} symbols` : undefined}
          actions={
            lists && lists.length > 0 ? (
              <>
                <Select
                  aria-label="Watchlist shown on Overview"
                  className="h-8 w-44 text-[13px] max-md:h-10"
                  value={wl?.id ?? ""}
                  disabled={readOnly}
                  onChange={(e) => patch.mutate({ default_watchlist_id: Number(e.target.value) })}
                >
                  {lists.map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.name}
                    </option>
                  ))}
                </Select>
                <Link to={wl ? `/watchlists?id=${wl.id}` : "/watchlists"} className="inline-flex size-8 items-center justify-center rounded-md text-fg-2 hover:bg-hover" aria-label="Open watchlist page" title="Open watchlist page">
                  <ArrowRight className="size-4" aria-hidden />
                </Link>
              </>
            ) : null
          }
        >
          {listsLoading ? (
            <SkeletonRows rows={8} className="p-4" />
          ) : listsError ? (
            <ErrorState message={errorMessage(error)} onRetry={() => refetch()} />
          ) : !wl ? (
            <EmptyState
              icon={<ListChecks aria-hidden />}
              title="No watchlist yet"
              actions={
                !readOnly && (
                  <>
                    <Button size="sm" variant="primary" icon={<Plus className="size-3.5" aria-hidden />} onClick={() => open({ kind: "new-watchlist" })}>
                      Create watchlist
                    </Button>
                    <Button
                      size="sm"
                      icon={<Sparkles className="size-3.5" aria-hidden />}
                      loading={starter.isPending}
                      onClick={() => starter.mutate(undefined, { onError: (e) => toast("error", errorMessage(e)) })}
                    >
                      {status?.sample_data ? "Load sample starter" : "Load NSE starter"}
                    </Button>
                  </>
                )
              }
            >
              {status?.sample_data
                ? "The sample starter adds fictitious SX: companies from the fixed dataset."
                : "The NSE starter adds a few large Yahoo symbols; prices are fetched live."}
            </EmptyState>
          ) : wl.items.length === 0 ? (
            <EmptyState
              icon={<ListChecks aria-hidden />}
              title={`${wl.name} is empty`}
              actions={!readOnly && <Button size="sm" variant="primary" icon={<Plus className="size-3.5" aria-hidden />} onClick={() => open({ kind: "add-symbol", watchlistId: wl.id })}>Add symbol</Button>}
            />
          ) : snaps.isError && !snaps.data ? (
            <ErrorState message={errorMessage(snaps.error)} onRetry={() => snaps.refetch()} />
          ) : (
            <WatchlistTable watchlist={wl} snapshots={snaps.data} sort={sortState} onSortChange={setSort} compact={sideBySide} />
          )}
        </Panel>

        <BriefingPanel className="lg:col-span-6 xl:col-span-4 min-[87.5rem]:col-span-5" />
        <PortfolioSnapshot className="lg:col-span-6 xl:col-span-3" />
        <JournalActivity className="lg:col-span-12 xl:col-span-5 min-[87.5rem]:col-span-4" />
      </div>
    </>
  );
}
