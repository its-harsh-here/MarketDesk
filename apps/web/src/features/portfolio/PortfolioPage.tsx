import { ArrowLeftRight, Briefcase, Download, FileUp, Pencil, Plus } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router";
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
import { Segmented } from "@/components/ui/Segmented";
import { errorMessage, type AccountCurrency, type Holding, type PortfolioOverview, type Transaction } from "@/lib/api/client";
import { DASH, formatInstant, formatMoney, formatNumber, formatPercent, formatQuantity, formatSessionDate, tone } from "@/lib/format";
import { cn } from "@/lib/cn";
import { usePrefs, useSession } from "@/features/settings/api";
import { usePortfolioOverview, usePortfolioSummary, useTransactions } from "./api";

const TYPE_TONE: Record<string, "pos" | "neg" | "info" | "neutral" | "accent"> = {
  DEPOSIT: "info",
  WITHDRAWAL: "neutral",
  BUY: "pos",
  SELL: "neg",
  DIVIDEND: "accent",
  SPLIT: "neutral",
  FX: "info",
};

type View = AccountCurrency | "ALL";

function Allocation({ holdings, cashPct, cash, ccy }: { holdings: Holding[]; cashPct: string | null | undefined; cash: string; ccy: AccountCurrency }) {
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
              {formatPercent(it.pct, { signed: false, digits: 1 })} · {formatMoney(it.value, ccy)}
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

function MarkCell({ h, ccy }: { h: Holding; ccy: AccountCurrency }) {
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
      <button type="button" className={cn("num inline-flex items-center gap-1.5", h.mark_status === "stale" ? "text-warn" : "text-fg")} aria-label={`Last price ${formatMoney(h.last_price, ccy)}, ${s.label}`}>
        {h.mark_status === "stale" && <span className="size-1.5 rounded-full bg-warn" aria-hidden />}
        {formatMoney(h.last_price, ccy)}
      </button>
    </Tooltip>
  );
}

function rateLine(a: PortfolioOverview["accounts"][number], tz?: string) {
  const r = a.rate;
  if (r.status === "identity") return "Base currency";
  if (r.rate === null) return `No usable ${r.pair} rate${r.message ? ` (${r.message})` : ""}`;
  return `${r.pair} ${formatNumber(r.rate, 4)} · ${statusInfo(r.status).label.toLowerCase()} · ${formatInstant(r.market_time, tz)} · ${r.source ?? ""}`;
}

function AccountsOverview({ ov, onOpen }: { ov: PortfolioOverview; onOpen: (c: AccountCurrency) => void }) {
  const { data: prefs } = usePrefs();
  const tz = prefs?.display_timezone;
  return (
    <div className="space-y-4">
      <section aria-label="All accounts in INR" className="rounded-[var(--radius-panel)] border border-line-subtle bg-panel px-[var(--panel-pad)] py-3">
        <Metric
          size="lg"
          label={ov.complete ? "All accounts, in INR at current rates" : "All accounts, in INR — incomplete"}
          value={formatMoney(ov.complete ? ov.total_in_base : ov.partial_in_base, ov.base_currency)}
          caption={ov.complete ? "Display conversion only; each account keeps its own currency" : "Partial: some value could not be priced or converted (see below)"}
        />
      </section>
      {!ov.complete && (
        <InlineNotice tone="warn">
          <ul className="list-disc space-y-1 pl-4">
            {ov.incomplete_reasons.map((r) => <li key={r}>{r}</li>)}
          </ul>
        </InlineNotice>
      )}
      {ov.stale_rates.length > 0 && <InlineNotice tone="warn">Valuation rate is stale for {ov.stale_rates.join(", ")}; converted figures use the last available rate.</InlineNotice>}
      <Panel title="Accounts" titleId="acct-title" bodyClassName="p-0">
        <ul className="divide-y divide-line-subtle">
          {ov.accounts.map((a) => (
            <li key={a.currency} className="flex flex-wrap items-center gap-x-6 gap-y-2 px-[var(--panel-pad)] py-3">
              <div className="min-w-40 flex-1">
                <button type="button" className="text-[13px] font-semibold text-fg hover:text-accent-text" onClick={() => onOpen(a.currency)}>
                  {a.currency} account
                </button>
                <div className="text-xs text-fg-3">Cash {formatMoney(a.cash, a.currency)} · holdings {formatMoney(a.holdings_value, a.currency)}</div>
              </div>
              <div className="text-right">
                <div className="num text-[14px] text-fg">{formatMoney(a.complete ? a.total_equity : a.partial_equity, a.currency)}</div>
                <div className="text-xs text-fg-3">{a.complete ? "Native value" : "Partial native value"}</div>
              </div>
              <div className="min-w-48 text-right">
                <div className="num text-[14px] text-fg">{formatMoney(a.value_in_base ?? null, "INR")}</div>
                <div className="text-xs text-fg-3">{rateLine(a, tz)}</div>
              </div>
            </li>
          ))}
        </ul>
      </Panel>
      <p className="text-xs leading-4 text-fg-3">{ov.note}</p>
    </div>
  );
}

export function PortfolioPage() {
  const [params, setParams] = useSearchParams();
  const raw = params.get("account");
  const view: View = raw === "USD" || raw === "ALL" ? raw : "INR";
  const ccy: AccountCurrency = view === "ALL" ? "INR" : view;
  const setView = (v: View) => {
    const next = new URLSearchParams(params);
    if (v === "INR") next.delete("account");
    else next.set("account", v);
    setParams(next, { replace: true });
  };
  const summary = usePortfolioSummary(view !== "ALL", ccy);
  const overview = usePortfolioOverview();
  const { data: session } = useSession();
  const { open } = useDialogs();
  const [type, setType] = useState("");
  const [symbol, setSymbol] = useState("");
  const txns = useTransactions({ type: type || undefined, symbol: symbol || undefined, currency: ccy });
  const readOnly = Boolean(session?.read_only);
  const s = summary.data;
  const anyAccount = (overview.data?.accounts.length ?? 0) > 0;

  const holdingCols: Column<Holding>[] = [
    { key: "inst", header: "Instrument", render: (h) => <InstrumentBadge symbol={h.symbol} name={h.name} exchange={h.exchange} />, className: "max-w-[240px]" },
    { key: "qty", header: "Quantity", align: "right", render: (h) => <span className="num">{formatQuantity(h.quantity)}</span> },
    { key: "avg", header: "Avg cost", align: "right", render: (h) => <span className="num">{formatMoney(h.average_cost, ccy)}</span> },
    { key: "basis", header: "Cost basis", align: "right", hideBelow: "lg", render: (h) => <span className="num text-fg-2">{formatMoney(h.cost_basis, ccy)}</span> },
    { key: "last", header: "Last price", align: "right", render: (h) => <MarkCell h={h} ccy={ccy} /> },
    { key: "mv", header: "Market value", align: "right", render: (h) => <span className="num">{formatMoney(h.market_value, ccy)}</span> },
    {
      key: "upnl",
      header: "Unrealized P&L",
      align: "right",
      render: (h) =>
        h.unrealized_pnl === null ? (
          <span className="text-fg-3">{DASH}</span>
        ) : (
          <span className="inline-flex flex-col items-end">
            <PnlText value={h.unrealized_pnl} currency={ccy} />
            <span className={cn("num text-xs", tone(h.unrealized_pct) === "positive" ? "text-pos" : tone(h.unrealized_pct) === "negative" ? "text-neg" : "text-fg-3")}>{formatPercent(h.unrealized_pct)}</span>
          </span>
        ),
    },
    { key: "real", header: "Realized", align: "right", hideBelow: "xl", render: (h) => <PnlText value={h.realized_pnl} currency={ccy} className="text-fg-2" /> },
    { key: "w", header: "Weight", align: "right", hideBelow: "lg", render: (h) => <span className="num text-fg-2">{formatPercent(h.weight_pct, { signed: false, digits: 1 })}</span> },
  ];

  /** Cash change in the account being viewed (the receiving side of an FX conversion gets the amount received). */
  const cashIn = (t: Transaction) => (t.type === "FX" && t.counter_currency === ccy ? t.counter_amount : t.cash_effect);

  const txnCols: Column<Transaction>[] = [
    { key: "date", header: "Date", render: (t) => <span className="num whitespace-nowrap text-fg-2">{formatSessionDate(t.effective_date)}</span> },
    { key: "type", header: "Type", render: (t) => <Pill tone={TYPE_TONE[t.type]} className="py-0">{t.type}</Pill> },
    {
      key: "sym",
      header: "Instrument",
      render: (t) =>
        t.symbol ? <InstrumentBadge symbol={t.symbol} /> : t.type === "FX" ? <span className="num text-fg-2">{t.currency} → {t.counter_currency}</span> : <span className="text-fg-3">Cash</span>,
    },
    {
      key: "detail",
      header: "Qty × price",
      align: "right",
      render: (t) =>
        t.type === "BUY" || t.type === "SELL" ? (
          <span className="num whitespace-nowrap">{formatQuantity(t.quantity)} × {formatNumber(t.price, 2)}</span>
        ) : t.type === "SPLIT" ? (
          <span className="num">{formatQuantity(t.split_from)} → {formatQuantity(t.split_to)}</span>
        ) : t.type === "FX" ? (
          <span className="num whitespace-nowrap" title={`Source: ${t.fx_source ?? "—"}${t.fx_rate ? ` · quoted ${t.fx_rate} INR per USD` : ""}`}>
            {formatMoney(t.amount, t.currency)} → {formatMoney(t.counter_amount, t.counter_currency)} @ {formatNumber(t.effective_rate, 4)}
          </span>
        ) : (
          <span className="text-fg-3">{DASH}</span>
        ),
    },
    { key: "fees", header: "Fees", align: "right", hideBelow: "lg", render: (t) => <span className="num text-fg-2">{t.fees === "0" ? DASH : formatMoney(t.fees, t.currency)}</span> },
    { key: "cash", header: `Cash effect (${ccy})`, align: "right", render: (t) => <PnlText value={cashIn(t)} currency={ccy} /> },
    { key: "after", header: "Cash after", align: "right", hideBelow: "xl", render: (t) => <span className="num text-fg-2">{t.currency === ccy ? formatMoney(t.cash_after, ccy) : DASH}</span> },
    { key: "rpnl", header: "Realized", align: "right", hideBelow: "lg", render: (t) => (t.realized_pnl !== null ? <PnlText value={t.realized_pnl} currency={ccy} /> : <span className="text-fg-3">{DASH}</span>) },
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
      <Button variant="primary" icon={<Plus className="size-4" aria-hidden />} onClick={() => open({ kind: "transaction", currency: ccy })}>Add transaction</Button>
      <Button icon={<ArrowLeftRight className="size-4" aria-hidden />} onClick={() => open({ kind: "transaction", type: "FX", currency: ccy === "USD" ? "INR" : ccy })}>Convert currency</Button>
      <Button icon={<FileUp className="size-4" aria-hidden />} onClick={() => open({ kind: "import" })}>Import CSV</Button>
    </div>
  );

  const switcher = (
    <Segmented<View>
      label="Portfolio account"
      size="md"
      value={view}
      onChange={setView}
      options={[
        { value: "INR", label: "INR account" },
        { value: "USD", label: "USD account" },
        { value: "ALL", label: "All accounts" },
      ]}
    />
  );

  if (view === "ALL") {
    return (
      <div className="space-y-4 p-4 md:space-y-5 md:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          {switcher}
          {actions}
        </div>
        {overview.isLoading ? (
          <SkeletonRows rows={4} />
        ) : overview.isError ? (
          <ErrorState message={errorMessage(overview.error)} onRetry={() => overview.refetch()} />
        ) : !anyAccount ? (
          <EmptyState icon={<Briefcase aria-hidden />} title="No transactions yet" actions={actions}>Record a deposit in the INR or USD account first.</EmptyState>
        ) : (
          <AccountsOverview ov={overview.data!} onOpen={setView} />
        )}
      </div>
    );
  }

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
      <div className="space-y-4 p-4 md:p-6">
        {switcher}
        <Panel title={`Portfolio · ${ccy} account`}>
          <EmptyState
            icon={<Briefcase aria-hidden />}
            title={anyAccount ? `No ${ccy} transactions yet` : "No transactions yet"}
            actions={<>{actions}</>}
          >
            {ccy === "USD"
              ? "Fund the USD account with an FX conversion from INR (rate, source, time and fees are recorded), or a USD deposit. US-listed stocks and ETFs are recorded here, in USD."
              : "Record a deposit first, then your buys and sells. Holdings, cash and P&L are computed from this INR ledger; US-listed stocks and ETFs belong in the USD account."}
          </EmptyState>
        </Panel>
      </div>
    );
  }

  const symbolsInLedger = Array.from(new Set(s!.holdings.map((h) => h.symbol)));

  return (
    <div className="space-y-4 p-4 md:space-y-5 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {switcher}
        <div className="flex flex-wrap gap-2">
          {actions}
          <a className="inline-flex h-9 items-center gap-2 rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-fg hover:bg-hover max-md:h-11" href="/api/portfolio/export/transactions.csv">
            <Download className="size-4" aria-hidden /> Export transactions
          </a>
          <a className="inline-flex h-9 items-center gap-2 rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-fg hover:bg-hover max-md:h-11" href={`/api/portfolio/export/holdings.csv?currency=${ccy}`}>
            <Download className="size-4" aria-hidden /> Export holdings
          </a>
        </div>
      </div>

      <section aria-label="Portfolio summary" className="grid grid-cols-2 gap-px overflow-hidden rounded-[var(--radius-panel)] border border-line-subtle bg-line-subtle md:grid-cols-3 xl:grid-cols-7">
        {[
          <Metric key="eq" size="lg" label={s!.complete ? "Total equity" : "Partial equity"} value={formatMoney(s!.complete ? s!.total_equity : s!.partial_equity, ccy)} caption={s!.complete ? `Cash + marked holdings · ${ccy}` : `Incomplete: excludes ${s!.missing_marks.join(", ")}`} />,
          <Metric key="cash" label="Cash" value={formatMoney(s!.cash, ccy)} caption={`Ledger balance · ${ccy}`} />,
          <Metric key="hv" label="Holdings value" value={formatMoney(s!.holdings_value, ccy)} caption={s!.stale_marks.length ? `Includes stale marks: ${s!.stale_marks.join(", ")}` : "Last observed prices"} />,
          <Metric key="u" label="Unrealized P&L" value={s!.unrealized_pnl !== null ? <PnlText value={s!.unrealized_pnl} currency={ccy} /> : DASH} caption={s!.unrealized_pnl === null ? "Unavailable while valuation is incomplete" : "vs. remaining cost basis"} />,
          <Metric key="r" label="Realized P&L" value={<PnlText value={s!.realized_pnl} currency={ccy} />} caption={`Dividends ${formatMoney(s!.dividends, ccy)} tracked separately`} />,
          <Metric
            key="nc"
            label="Net contributions"
            value={formatMoney(s!.net_contributions, ccy)}
            caption={Number(s!.fx_in) || Number(s!.fx_out) ? `Deposits − withdrawals; FX in ${formatMoney(s!.fx_in, ccy)} / out ${formatMoney(s!.fx_out, ccy)} are transfers` : "Deposits − withdrawals (not a gain)"}
          />,
        ].map((m, i) => (
          <div key={i} className={cn("bg-panel px-[var(--panel-pad)] py-3", i === 0 && "col-span-2 md:col-span-1 xl:col-span-2", i === 5 && "max-md:col-span-2")}>{m}</div>
        ))}
      </section>

      <p className="max-w-3xl text-xs leading-4 text-fg-3">{s!.accounting_note}</p>
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
          Total profit before dividends (realized + unrealized): <PnlText value={s!.total_profit_before_dividends} currency={ccy} />. Change in portfolio value is not an investment return; time-weighted returns are not computed in this release.
        </p>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12 lg:gap-5">
        <Panel title="Holdings" titleId="hold-title" className="lg:col-span-9" bodyClassName="p-0" refreshing={summary.isFetching} meta={`${s!.holdings.length} open position(s) · long-only · ${ccy}`}>
          {s!.holdings.length === 0 ? (
            <EmptyState title="No open positions">This account has no shares currently held. Cash {formatMoney(s!.cash, ccy)}.</EmptyState>
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
                    <div className="num text-[14px]">{formatMoney(h.market_value, ccy)}</div>
                    {h.unrealized_pnl !== null ? <PnlText value={h.unrealized_pnl} currency={ccy} className="text-xs" /> : <span className="text-xs text-warn">No price</span>}
                  </div>
                </div>
              )}
            />
          )}
        </Panel>
        <Panel title="Allocation" titleId="alloc-title" className="lg:col-span-3" meta="By market value">
          <Allocation holdings={s!.holdings} cashPct={s!.cash_weight_pct} cash={s!.cash} ccy={ccy} />
        </Panel>
      </div>

      <Panel
        title="Transactions"
        titleId="txn-title"
        bodyClassName="p-0"
        wrapHeader
        meta={txns.data ? `${txns.data.total} total` : undefined}
        actions={
          <div className="flex gap-2">
            <Select aria-label="Filter by type" className="h-8 w-32 text-[13px] max-md:h-10" value={type} onChange={(e) => setType(e.target.value)}>
              <option value="">All types</option>
              {["DEPOSIT", "WITHDRAWAL", "BUY", "SELL", "DIVIDEND", "SPLIT", "FX"].map((t) => <option key={t} value={t}>{t}</option>)}
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
                    <span className="num truncate text-[13px] font-semibold">{t.symbol ?? (t.type === "FX" ? `${t.currency} → ${t.counter_currency}` : "Cash")}</span>
                  </div>
                  <div className="num mt-0.5 text-xs text-fg-3">{formatSessionDate(t.effective_date)}</div>
                </div>
                <PnlText value={cashIn(t)} currency={ccy} className="text-[13px]" />
              </div>
            )}
          />
        )}
      </Panel>
    </div>
  );
}
