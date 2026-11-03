import { Star } from "lucide-react";
import { useMemo } from "react";
import { useNavigate } from "react-router";
import { DataTable, type Column, type SortState } from "@/components/ui/DataTable";
import { FreshnessBadge, InstrumentBadge } from "@/components/ui/Badges";
import { ChangeText } from "@/components/ui/Change";
import { Sparkline } from "@/components/ui/Sparkline";
import { IconButton } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { errorMessage, type Snapshot, type Watchlist } from "@/lib/api/client";
import { DASH, formatMoney, formatVolume, toNumber } from "@/lib/format";
import { useWatchlistMutations } from "./api";
import { useSession } from "@/features/settings/api";
import { cn } from "@/lib/cn";

export interface Row {
  symbol: string;
  position: number;
  snap?: Snapshot;
  name: string | null;
  exchange: string | null;
  country: string | null;
}

export function buildRows(wl: Watchlist, snaps: Snapshot[] | undefined): Row[] {
  const bySym = new Map((snaps ?? []).map((s) => [s.symbol, s]));
  return wl.items.map((it) => {
    const snap = bySym.get(it.symbol);
    return {
      symbol: it.symbol,
      position: it.position,
      snap,
      name: snap?.instrument.name ?? it.instrument.name ?? null,
      exchange: snap?.instrument.exchange ?? it.instrument.exchange ?? null,
      country: snap?.instrument.country ?? it.instrument.country ?? null,
    };
  });
}

const sorters: Record<string, (r: Row) => number | string | null> = {
  symbol: (r) => r.symbol,
  name: (r) => r.name ?? "",
  last_price: (r) => toNumber(r.snap?.quote?.last_price),
  change_percent: (r) => toNumber(r.snap?.quote?.change_percent),
  volume: (r) => toNumber(r.snap?.quote?.volume),
  manual: (r) => r.position,
};

export function sortRows(rows: Row[], sort: SortState | null): Row[] {
  if (!sort || sort.key === "manual") return [...rows].sort((a, b) => a.position - b.position);
  const get = sorters[sort.key] ?? sorters.manual;
  const dir = sort.dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const va = get(a);
    const vb = get(b);
    if (va === null && vb === null) return 0;
    if (va === null) return 1; // missing values always last, never treated as zero
    if (vb === null) return -1;
    return (va < vb ? -1 : va > vb ? 1 : 0) * dir;
  });
}

export function RemoveStar({ watchlist, symbol }: { watchlist: Watchlist; symbol: string }) {
  const { removeSymbol } = useWatchlistMutations();
  const toast = useToast();
  const { data: session } = useSession();
  const disabled = Boolean(session?.read_only);
  return (
    <IconButton
      size="sm"
      label={disabled ? `${symbol} is in ${watchlist.name} (read-only demo)` : `Remove ${symbol} from ${watchlist.name}`}
      active
      disabled={disabled || removeSymbol.isPending}
      onClick={(e) => {
        e.stopPropagation();
        removeSymbol.mutate(
          { id: watchlist.id, symbol },
          { onSuccess: () => toast("success", `Removed ${symbol} from ${watchlist.name}.`), onError: (err) => toast("error", errorMessage(err)) },
        );
      }}
    >
      <Star className="size-4 fill-current" aria-hidden />
    </IconButton>
  );
}

export function WatchlistTable({
  watchlist,
  snapshots,
  sort,
  onSortChange,
  compact,
  caption,
  region = "all",
}: {
  watchlist: Watchlist;
  snapshots: Snapshot[] | undefined;
  sort: SortState | null;
  onSortChange?: (s: SortState) => void;
  compact?: boolean;
  caption?: string;
  /** Show only listings in this market ("other" = unknown or other countries). */
  region?: "all" | "IN" | "US" | "other";
}) {
  const navigate = useNavigate();
  const rows = useMemo(() => {
    const all = buildRows(watchlist, snapshots);
    const inRegion = region === "all" ? all : all.filter((r) => (region === "other" ? r.country !== "IN" && r.country !== "US" : r.country === region));
    return sortRows(inRegion, sort);
  }, [watchlist, snapshots, sort, region]);
  const ccy = (r: Row) => r.snap?.instrument.currency ?? null;

  const columns: Column<Row>[] = [
    {
      key: "symbol",
      header: "Instrument",
      sortable: true,
      render: (r) => <InstrumentBadge symbol={r.symbol} name={r.name} exchange={compact ? null : r.exchange} />,
      // Compact (Overview side panel): the instrument column takes whatever width is left and truncates, so the
      // price, change and star columns always stay inside the panel.
      className: compact ? "w-full max-w-0" : "max-w-[260px]",
    },
    {
      key: "last_price",
      header: "Last",
      align: "right",
      sortable: true,
      mobileLabel: "Last price",
      render: (r) => (
        <span className="inline-flex items-center justify-end gap-2">
          {compact && r.snap && <FreshnessBadge meta={r.snap.meta} compact />}
          {r.snap?.quote ? (
            <span className="num text-fg">{formatMoney(r.snap.quote.last_price, ccy(r))}</span>
          ) : (
            <span className="text-fg-3" title={r.snap?.meta.message ?? "No quote"}>{DASH}</span>
          )}
        </span>
      ),
    },
    ...(!compact
      ? [
          {
            key: "change",
            header: "Chg",
            align: "right" as const,
            mobileLabel: "Change",
            render: (r: Row) => <ChangeText value={r.snap?.quote?.change ?? null} currency={ccy(r)} showIcon={false} />,
          },
        ]
      : []),
    {
      key: "change_percent",
      header: "Chg %",
      align: "right",
      sortable: true,
      mobileLabel: "Change %",
      render: (r) => <ChangeText percent={r.snap?.quote?.change_percent ?? null} />,
    },
    ...(!compact
      ? [
          {
            key: "volume",
            header: "Volume",
            align: "right" as const,
            sortable: true,
            hideBelow: "lg" as const,
            render: (r: Row) => (
              <span className="num text-fg-2" title={r.snap?.quote?.volume_note ?? undefined}>
                {formatVolume(r.snap?.quote?.volume)}
              </span>
            ),
          },
        ]
      : []),
    {
      key: "trend",
      header: "3M",
      srHeader: " trend",
      align: "right",
      hideBelow: compact ? "2xl" : undefined,
      mobileLabel: "3-month trend",
      render: (r) => (
        <span className="inline-flex justify-end">
          <Sparkline points={r.snap?.sparkline ?? []} width={compact ? 64 : 88} height={24} />
        </span>
      ),
    },
    ...(!compact
      ? [
          {
            key: "fresh",
            header: "Data",
            align: "left" as const,
            mobileLabel: "Data",
            render: (r: Row) => (r.snap ? <FreshnessBadge meta={r.snap.meta} /> : <span className="skeleton inline-block h-3 w-12" />),
          },
        ]
      : []),
    {
      key: "star",
      header: <span className="sr-only">Watchlist membership</span>,
      align: "right",
      width: "44px",
      render: (r) => <RemoveStar watchlist={watchlist} symbol={r.symbol} />,
    },
  ];

  return (
    <DataTable
      caption={caption ?? `${watchlist.name} watchlist`}
      columns={columns}
      rows={rows}
      rowKey={(r) => r.symbol}
      sort={sort}
      onSortChange={onSortChange}
      onRowClick={(r) => navigate(`/instrument/${encodeURIComponent(r.symbol)}`)}
      mobileDetailKeys={["change", "volume", "trend", "fresh"]}
      mobileSummary={(r) => (
        <div className="flex items-center gap-3">
          <InstrumentBadge symbol={r.symbol} name={r.name} link={false} className="min-w-0 flex-1" />
          <div className="text-right">
            <div className={cn("num text-[14px]", r.snap?.quote ? "text-fg" : "text-fg-3")}>
              {r.snap?.quote ? formatMoney(r.snap.quote.last_price, ccy(r)) : DASH}
            </div>
            <ChangeText percent={r.snap?.quote?.change_percent ?? null} className="text-xs" />
          </div>
          <RemoveStar watchlist={watchlist} symbol={r.symbol} />
        </div>
      )}
    />
  );
}
