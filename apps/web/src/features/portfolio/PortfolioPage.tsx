import { Briefcase, Download, FileUp, Pencil, Plus, Sparkles } from "lucide-react";
import { useState } from "react";
import { useDialogs } from "@/app/dialogs";
import { Panel } from "@/components/ui/Panel";
import { Button, IconButton } from "@/components/ui/Button";
import { Metric } from "@/components/ui/Metric";
import { PnlText } from "@/components/ui/Change";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { InstrumentBadge, Pill, statusInfo } from "@/components/ui/Badges";
import { EmptyState, ErrorState, InlineNotice, Skeleton, SkeletonRows } from "@/components/ui/States";
import { Select } from "@/components/ui/Form";
import { Tooltip } from "@/components/ui/Tooltip";
import { useToast } from "@/components/ui/Toast";
import { errorMessage, type Holding, type Transaction } from "@/lib/api/client";
import { DASH, formatInstant, formatMoney, formatNumber, formatPercent, formatQuantity, formatSessionDate, tone } from "@/lib/format";
import { cn } from "@/lib/cn";
import { usePrefs, useSession, useStatus } from "@/features/settings/api";
import { usePortfolioSummary, useTransactionMutations, useTransactions } from "./api";

const TYPE_TONE: Record<string, "pos" | "neg" | "info" | "neutral" | "accent"> = {
  DEPOSIT: "info",
  WITHDRAWAL: "neutral",
  BUY: "pos",
  SELL: "neg",
  DIVIDEND: "accent",
  SPLIT: "neutral",
};

function Allocation({ holdings, cashPct, cash }: { holdings: Holding[]; cashPct: string | null | undefined; cash: string }) {
  const items = [
    ...holdings.filter((h) => h.weight_pct !== null).map((h) => ({ label: h.symbol, pct: Number(h.weight_pct), value: h.market_value })),
    ...(cashPct != null ? [{ label: "Cash", pct: Number(cashPct), value: cash }] : []),
  ].sort((a, b) => b.pct - a.pct);
  if (!items.length) return <p className="text-[13px] text-fg-3">Allocation needs a usable price for every holding.</p>;
  return (
    <ul className="space-y-2.5" aria-label="Allocation by market value">
      {items.map((it) => (
        <li key={it.label} className="text-[13px]">
          <div className="flex items-baseline justify-between gap-2">
            <span className={cn("num", it.label === "Cash" ? "text-fg-2" : "font-semibold text-fg")}>{it.label}</span>
            <span className="num text-fg-2">
              {formatPercent(it.pct, { signed: false, digits: 1 })} · {formatMoney(it.value)}
            </span>
          </div>
          <div className="mt-1 h-1.5 rounded-full bg-elevated" aria-hidden>
            <div className={cn("h-full rounded-full", it.label === "Cash" ? "bg-fg-3/60" : "bg-accent")} style={{ width: `${Math.max(1, Math.min(100, it.pct))}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

function MarkCell({ h }: { h: Holding }) {
  const { data: prefs } = usePrefs();
  if (h.last_price === null) {
    return (
      <Tooltip content={h.mark_message ?? "No usable price; this holding is excluded from total valuation."}>
        <button type="button" className="text-warn underline decoration-dotted underline-offset-4" aria-label={`No price for ${h.symbol}: ${h.mark_message ?? "excluded from valuation"}`}>
          No price
        </button>
      </Tooltip>
    );
  }
  const s = statusInfo(h.mark_status);
  return (
    <Tooltip content={<span>{s.label}. Market time {formatInstant(h.mark_time, prefs?.display_timezone)}. {h.mark_message ?? ""}</span>}>
      <button type="button" className={cn("num inline-flex items-center gap-1.5", h.mark_status === "stale" ? "text-warn" : "text-fg")} aria-label={`Last price ${formatMoney(h.last_price)}, ${s.label}`}>
        {h.mark_status === "stale" && <span className="size-1.5 rounded-full bg-warn" aria-hidden />}
        {formatMoney(h.last_price)}
      </button>
    </Tooltip>
  );
}

export function PortfolioPage() {
  const summary = usePortfolioSummary();
  const { data: status } = useStatus();
  const { data: session } = useSession();
  const { open } = useDialogs();
  const [type, setType] = useState("");
  const [symbol, setSymbol] = useState("");
  const txns = useTransactions({ type: type || undefined, symbol: symbol || undefined });
  const { sample } = useTransactionMutations();
  const toast = useToast();
  const readOnly = Boolean(session?.read_only);
  const s = summary.data;

  const holdingCols: Column<Holding>[] = [
    { key: "inst", header: "Instrument", render: (h) => <InstrumentBadge symbol={h.symbol} name={h.name} exchange={h.exchange} />, className: "max-w-[240px]" },
    { key: "qty", header: "Quantity", align: "right", render: (h) => <span className="num">{formatQuantity(h.quantity)}</span> },
    { key: "avg", header: "Avg cost", align: "right", render: (h) => <span className="num">{formatMoney(h.average_cost)}</span> },
    { key: "basis", header: "Cost basis", align: "right", hideBelow: "lg", render: (h) => <span className="num text-fg-2">{formatMoney(h.cost_basis)}</span> },
    { key: "last", header: "Last price", align: "right", render: (h) => <MarkCell h={h} /> },
    { key: "mv", header: "Market value", align: "right", render: (h) => <span className="num">{formatMoney(h.market_value)}</span> },
    {
      key: "upnl",
      header: "Unrealized P&L",
      align: "right",
      render: (h) =>
        h.unrealized_pnl === null ? (
          <span className="text-fg-3">{DASH}</span>
        ) : (
          <span className="inline-flex flex-col items-end">
            <PnlText value={h.unrealized_pnl} />
            <span className={cn("num text-xs", tone(h.unrealized_pct) === "positive" ? "text-pos" : tone(h.unrealized_pct) === "negative" ? "text-neg" : "text-fg-3")}>{formatPercent(h.unrealized_pct)}</span>
          </span>
        ),
    },
    { key: "real", header: "Realized", align: "right", hideBelow: "xl", render: (h) => <PnlText value={h.realized_pnl} className="text-fg-2" /> },
    { key: "w", header: "Weight", align: "right", hideBelow: "lg", render: (h) => <span className="num text-fg-2">{formatPercent(h.weight_pct, { signed: false, digits: 1 })}</span> },
  ];

  const txnCols: Column<Transaction>[] = [
    { key: "date", header: "Date", render: (t) => <span className="num whitespace-nowrap text-fg-2">{formatSessionDate(t.effective_date)}</span> },
    { key: "type", header: "Type", render: (t) => <Pill tone={TYPE_TONE[t.type]} className="py-0">{t.type}</Pill> },
    { key: "sym", header: "Instrument", render: (t) => (t.symbol ? <InstrumentBadge symbol={t.symbol} /> : <span className="text-fg-3">Cash</span>) },
    {
      key: "detail",
      header: "Qty × price",
      align: "right",
      render: (t) =>
        t.type === "BUY" || t.type === "SELL" ? (
          <span className="num whitespace-nowrap">{formatQuantity(t.quantity)} × {formatNumber(t.price, 2)}</span>
        ) : t.type === "SPLIT" ? (
          <span className="num">{formatQuantity(t.split_from)} → {formatQuantity(t.split_to)}</span>
        ) : (
          <span className="text-fg-3">{DASH}</span>
        ),
    },
    { key: "fees", header: "Fees", align: "right", hideBelow: "lg", render: (t) => <span className="num text-fg-2">{t.fees === "0" ? DASH : formatMoney(t.fees)}</span> },
    { key: "cash", header: "Cash effect", align: "right", render: (t) => <PnlText value={t.cash_effect} /> },
    { key: "after", header: "Cash after", align: "right", hideBelow: "xl", render: (t) => <span className="num text-fg-2">{formatMoney(t.cash_after)}</span> },
    { key: "rpnl", header: "Realized", align: "right", hideBelow: "lg", render: (t) => (t.realized_pnl !== null ? <PnlText value={t.realized_pnl} /> : <span className="text-fg-3">{DASH}</span>) },
    { key: "notes", header: "Notes", hideBelow: "xl", render: (t) => <span className="block max-w-48 truncate text-fg-2" title={t.notes ?? undefined}>{t.notes ?? ""}</span> },
    {
      key: "edit",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      width: "44px",
      render: (t) =>
        readOnly ? null : (
          <IconButton size="sm" label={`Edit transaction #${t.id}`} onClick={(e) => { e.stopPropagation(); open({ kind: "transaction", editing: t }); }}>
            <Pencil className="size-3.5" aria-hidden />
          </IconButton>
        ),
    },
  ];

  const actions = !readOnly && (
    <div className="flex flex-wrap gap-2">
      <Button variant="primary" icon={<Plus className="size-4" aria-hidden />} onClick={() => open({ kind: "transaction" })}>Add transaction</Button>
      <Button icon={<FileUp className="size-4" aria-hidden />} onClick={() => open({ kind: "import" })}>Import CSV</Button>
    </div>
  );

  if (summary.isLoading) {
    return (
      <div className="space-y-4 p-4 md:p-6">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24" />)}</div>
        <SkeletonRows rows={6} />
      </div>
    );
  }
  if (summary.isError) return <div className="p-6"><ErrorState message={errorMessage(summary.error)} onRetry={() => summary.refetch()} /></div>;

  if (!s!.has_transactions) {
    return (
      <div className="p-4 md:p-6">
        <Panel title="Portfolio">
          <EmptyState
            icon={<Briefcase aria-hidden />}
            title="No transactions yet"
            actions={
              <>
                {actions}
                {!readOnly && status?.sample_data && (
                  <Button icon={<Sparkles className="size-4" aria-hidden />} loading={sample.isPending} onClick={() => sample.mutate(undefined, { onError: (e) => toast("error", errorMessage(e)) })}>
                    Load sample portfolio
                  </Button>
                )}
              </>
            }
          >
            Record a deposit first, then your buys and sells. Holdings, cash and P&amp;L are computed from this INR ledger.
            {status?.sample_data && " The sample portfolio uses fictitious SX: companies and is only offered while your ledger is empty."}
          </EmptyState>
        </Panel>
      </div>
    );
  }

  const symbolsInLedger = Array.from(new Set(s!.holdings.map((h) => h.symbol)));

  return (
    <div className="space-y-4 p-4 md:space-y-5 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-xs leading-4 text-fg-3">{s!.accounting_note}</p>
        <div className="flex flex-wrap gap-2">
          {actions}
          <a className="inline-flex h-9 items-center gap-2 rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-fg hover:bg-hover max-md:h-11" href="/api/portfolio/export/transactions.csv">
            <Download className="size-4" aria-hidden /> Export transactions
          </a>
          <a className="inline-flex h-9 items-center gap-2 rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-fg hover:bg-hover max-md:h-11" href="/api/portfolio/export/holdings.csv">
            <Download className="size-4" aria-hidden /> Export holdings
          </a>
        </div>
      </div>

      <section aria-label="Portfolio summary" className="grid grid-cols-2 gap-px overflow-hidden rounded-[var(--radius-panel)] border border-line-subtle bg-line-subtle md:grid-cols-3 xl:grid-cols-7">
        {[
          <Metric key="eq" size="lg" label={s!.complete ? "Total equity" : "Partial equity"} value={formatMoney(s!.complete ? s!.total_equity : s!.partial_equity)} caption={s!.complete ? "Cash + marked holdings · INR" : `Incomplete: excludes ${s!.missing_marks.join(", ")}`} />,
          <Metric key="cash" label="Cash" value={formatMoney(s!.cash)} caption="Ledger balance · INR" />,
          <Metric key="hv" label="Holdings value" value={formatMoney(s!.holdings_value)} caption={s!.stale_marks.length ? `Includes stale marks: ${s!.stale_marks.join(", ")}` : "Last observed prices"} />,
          <Metric key="u" label="Unrealized P&L" value={s!.unrealized_pnl !== null ? <PnlText value={s!.unrealized_pnl} /> : DASH} caption={s!.unrealized_pnl === null ? "Unavailable while valuation is incomplete" : "vs. remaining cost basis"} />,
          <Metric key="r" label="Realized P&L" value={<PnlText value={s!.realized_pnl} />} caption={`Dividends ${formatMoney(s!.dividends)} tracked separately`} />,
          <Metric key="nc" label="Net contributions" value={formatMoney(s!.net_contributions)} caption="Deposits − withdrawals (not a gain)" />,
        ].map((m, i) => (
          <div key={i} className={cn("bg-panel px-[var(--panel-pad)] py-3", i === 0 && "col-span-2 md:col-span-1 xl:col-span-2", i === 5 && "max-md:col-span-2")}>{m}</div>
        ))}
      </section>

      {!s!.complete && (
        <InlineNotice tone="warn">
          Valuation is incomplete: {s!.missing_marks.join(", ")} {s!.missing_marks.length > 1 ? "have" : "has"} no usable price, so total equity, unrealized P&amp;L and weights are not shown as complete figures. Missing prices are never valued at zero.
        </InlineNotice>
      )}
      {s!.complete && s!.stale_marks.length > 0 && (
        <InlineNotice tone="warn">Some holdings are marked at stale prices ({s!.stale_marks.join(", ")}); the provider could not be reached for a fresh observation.</InlineNotice>
      )}
      {s!.total_profit_before_dividends !== null && (
        <p className="text-[13px] text-fg-2">
          Total profit before dividends (realized + unrealized): <PnlText value={s!.total_profit_before_dividends} />. Change in portfolio value is not an investment return; time-weighted returns are not computed in this release.
        </p>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12 lg:gap-5">
        <Panel title="Holdings" titleId="hold-title" className="lg:col-span-9" bodyClassName="p-0" refreshing={summary.isFetching} meta={`${s!.holdings.length} open position(s) · long-only · INR`}>
          {s!.holdings.length === 0 ? (
            <EmptyState title="No open positions">Your ledger has no shares currently held. Cash {formatMoney(s!.cash)}.</EmptyState>
          ) : (
            <DataTable
              caption="Holdings"
              columns={holdingCols}
              rows={s!.holdings}
              rowKey={(h) => h.symbol}
              mobileDetailKeys={["qty", "avg", "basis", "last", "real", "w"]}
              mobileSummary={(h) => (
                <div className="flex items-center gap-3">
                  <InstrumentBadge symbol={h.symbol} name={h.name} link={false} className="min-w-0 flex-1" />
                  <div className="text-right">
                    <div className="num text-[14px]">{formatMoney(h.market_value)}</div>
                    {h.unrealized_pnl !== null ? <PnlText value={h.unrealized_pnl} className="text-xs" /> : <span className="text-xs text-warn">No price</span>}
                  </div>
                </div>
              )}
            />
          )}
        </Panel>
        <Panel title="Allocation" titleId="alloc-title" className="lg:col-span-3" meta="By market value">
          <Allocation holdings={s!.holdings} cashPct={s!.cash_weight_pct} cash={s!.cash} />
        </Panel>
      </div>

      <Panel
        title="Transactions"
        titleId="txn-title"
        bodyClassName="p-0"
        meta={txns.data ? `${txns.data.total} total` : undefined}
        actions={
          <div className="flex gap-2">
            <Select aria-label="Filter by type" className="h-8 w-32 text-[13px] max-md:h-10" value={type} onChange={(e) => setType(e.target.value)}>
              <option value="">All types</option>
              {["DEPOSIT", "WITHDRAWAL", "BUY", "SELL", "DIVIDEND", "SPLIT"].map((t) => <option key={t} value={t}>{t}</option>)}
            </Select>
            <Select aria-label="Filter by instrument" className="h-8 w-36 text-[13px] max-md:h-10" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              <option value="">All instruments</option>
              {symbolsInLedger.map((x) => <option key={x} value={x}>{x}</option>)}
            </Select>
          </div>
        }
      >
        {txns.isLoading ? (
          <SkeletonRows rows={5} className="p-4" />
        ) : txns.isError ? (
          <ErrorState message={errorMessage(txns.error)} onRetry={() => txns.refetch()} />
        ) : !txns.data!.items.length ? (
          <EmptyState title="No matching transactions" />
        ) : (
          <DataTable
            caption="Transaction ledger"
            columns={txnCols}
            rows={txns.data!.items}
            rowKey={(t) => String(t.id)}
            onRowClick={readOnly ? undefined : (t) => open({ kind: "transaction", editing: t })}
            mobileDetailKeys={["detail", "fees", "after", "rpnl", "notes"]}
            mobileSummary={(t) => (
              <div className="flex items-center gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Pill tone={TYPE_TONE[t.type]} className="py-0">{t.type}</Pill>
                    <span className="num truncate text-[13px] font-semibold">{t.symbol ?? "Cash"}</span>
                  </div>
                  <div className="num mt-0.5 text-xs text-fg-3">{formatSessionDate(t.effective_date)}</div>
                </div>
                <PnlText value={t.cash_effect} className="text-[13px]" />
              </div>
            )}
          />
        )}
      </Panel>
    </div>
  );
}
