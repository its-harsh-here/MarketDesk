import { Bell, NotebookPen, Plus, Sparkles } from "lucide-react";
import { useRef } from "react";
import { useParams, useSearchParams } from "react-router";
import { Link } from "react-router";
import { useDialogs } from "@/app/dialogs";
import { Panel } from "@/components/ui/Panel";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/Button";
import { ChangeText } from "@/components/ui/Change";
import { FreshnessBadge, Pill } from "@/components/ui/Badges";
import { EmptyState, ErrorState, InlineNotice, Skeleton, SkeletonRows } from "@/components/ui/States";
import { Tooltip } from "@/components/ui/Tooltip";
import { errorMessage } from "@/lib/api/client";
import {
  DASH,
  formatInstant,
  formatLargeMoney,
  formatMoney,
  formatPercent,
  formatRatio,
  formatSessionDate,
  formatVolume,
  toNumber,
} from "@/lib/format";
import { ChartPanel } from "@/features/market/ChartPanel";
import { useActions, useFundamentals, useSessions, useSnapshots } from "@/features/market/api";
import { ComparePanel } from "@/features/market/ComparePanel";
import { EventsTab, FilingsTab, FinancialsTab } from "@/features/research/ResearchTabs";
import { PeersTab } from "@/features/screener/PeersTab";
import { ValuationTab } from "@/features/valuation/ValuationTab";
import { useAiStatus } from "@/features/ai/api";
import { REGION_LABEL, sessionFor, sessionText } from "@/lib/markets";
import { usePrefs, useSession } from "@/features/settings/api";
import { StarToggle } from "@/features/watchlists/StarToggle";
import { useAlerts } from "@/features/alerts/api";
import { useJournal } from "@/features/journal/api";

function FundRow({ label, value, kind, note }: { label: string; value: string; kind: string; note?: string }) {
  const missing = value === DASH;
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-line-subtle py-2 last:border-0">
      <dt className="text-[13px] text-fg-2">
        {label} <span className="text-[11px] text-fg-3">{kind}</span>
      </dt>
      <dd className="num text-right text-[13px] text-fg">
        {missing ? (
          <Tooltip content={note ?? "Not reported by the provider."}>
            <button type="button" className="text-fg-3 underline decoration-dotted underline-offset-4" aria-label={`${label} not available: ${note ?? "not reported by the provider"}`}>
              {DASH}
            </button>
          </Tooltip>
        ) : (
          value
        )}
      </dd>
    </div>
  );
}

function RangeBar({ low, high, last, currency }: { low: string | null | undefined; high: string | null | undefined; last: string | null | undefined; currency?: string | null }) {
  const l = toNumber(low);
  const h = toNumber(high);
  const p = toNumber(last);
  if (l === null || h === null || h <= l) return null;
  const pos = p === null ? null : Math.min(100, Math.max(0, ((p - l) / (h - l)) * 100));
  return (
    <div className="pt-3 pb-1" aria-label={`52-week range ${formatMoney(low, currency)} to ${formatMoney(high, currency)}${p !== null ? `, last ${formatMoney(last, currency)}` : ""}`} role="img">
      <div className="relative h-1.5 rounded-full bg-elevated">
        {pos !== null && <span className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-panel bg-accent" style={{ left: `${pos}%` }} />}
      </div>
      <div className="num mt-1.5 flex justify-between text-[11px] text-fg-3">
        <span>{formatMoney(low, currency)}</span>
        <span>52-week range</span>
        <span>{formatMoney(high, currency)}</span>
      </div>
    </div>
  );
}

export function InstrumentPage() {
  const { symbol: raw } = useParams();
  const symbol = decodeURIComponent(raw ?? "").toUpperCase();
  const snap = useSnapshots(symbol ? [symbol] : []);
  const fund = useFundamentals(symbol);
  const actions = useActions(symbol);
  const { data: prefs } = usePrefs();
  const { data: session } = useSession();
  const { open } = useDialogs();
  const alerts = useAlerts();
  const notes = useJournal({ symbol });
  const s = snap.data?.[0];
  const sessions = useSessions();
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find((t) => t.value === params.get("tab"))?.value ?? "overview") as Tab;
  const setTab = (t: Tab) => setParams((p) => {
    const next = new URLSearchParams(p);
    if (t === "overview") next.delete("tab");
    else next.set("tab", t);
    return next;
  }, { replace: true });
  const tz = prefs?.display_timezone ?? "Asia/Kolkata";
  const inst = s?.instrument;
  const marketSession = sessionFor(sessions.data, inst?.country);
  const ccy = inst?.currency ?? fund.data?.currency ?? null;
  const readOnly = Boolean(session?.read_only);
  const ai = useAiStatus();
  const kindUpper = (inst?.kind ?? "").toUpperCase();
  const account = inst?.currency === "INR" || inst?.currency === "USD" ? inst.currency : null;
  const holdable = Boolean(inst && account && kindUpper !== "INDEX" && kindUpper !== "CURRENCY");
  const holdReason = !inst
    ? "Instrument not loaded"
    : kindUpper === "INDEX" || kindUpper === "CURRENCY"
      ? `${kindUpper === "INDEX" ? "Indices" : "Exchange rates"} cannot be held in the portfolio.`
      : !account
        ? `Trades in ${inst.currency ?? "an unverified currency"}; portfolio accounts exist for INR and USD only, and amounts are never converted by relabeling.`
        : undefined;
  const myAlerts = alerts.data?.filter((a) => a.symbol === symbol) ?? [];
  const f = fund.data?.values;
  const notesFor = (field: string) => f?.notes.find((n) => n.toLowerCase().includes(field));

  if (snap.isError && !s) {
    return (
      <div className="p-6">
        <ErrorState title={`Could not load ${symbol}`} message={errorMessage(snap.error)} onRetry={() => snap.refetch()} />
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 p-4 md:p-6 lg:grid-cols-12 lg:gap-5">
      <section className="lg:col-span-12" aria-labelledby="inst-title">
        <div className="flex flex-wrap items-start gap-x-6 gap-y-3 rounded-[var(--radius-panel)] border border-line-subtle bg-panel px-5 py-4">
          {/* No min-w-0 here: the column must never be narrower than the (unbreakable) symbol, otherwise a long
              ticker such as RELIANCE.NS overlaps the price. When space runs short the price/actions wrap instead. */}
          <div className="flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 id="inst-title" className="num text-xl font-semibold text-fg">{symbol}</h1>
              {inst?.exchange && <Pill>{inst.exchange}</Pill>}
              {inst?.country && <Pill>{REGION_LABEL[inst.country] ?? inst.country}</Pill>}
              {ccy && <Pill>{ccy}</Pill>}
              {inst?.kind && <Pill>{inst.kind}</Pill>}
              {s && <FreshnessBadge meta={s.meta} />}
            </div>
            <div className="mt-1 line-clamp-2 text-[13px] break-words text-fg-2">{snap.isLoading ? <Skeleton className="h-4 w-56" /> : inst?.name ?? "Name not reported"}</div>
            {!snap.isLoading && (
              <div className="mt-1 text-xs text-fg-3">
                {marketSession ? (
                  <span title={`Exchange schedule from the ${marketSession.source} calendar; not a live exchange feed.`}>
                    {REGION_LABEL[marketSession.market] ?? marketSession.market} session: {sessionText(marketSession)}
                  </span>
                ) : (
                  <span>Market status unavailable for this listing.</span>
                )}
                {inst?.mic && <span className="num"> · {inst.mic}</span>}
              </div>
            )}
          </div>
          <div>
            {snap.isLoading ? (
              <Skeleton className="h-8 w-40" />
            ) : s?.quote ? (
              <>
                <div className="num text-[28px] leading-8 font-semibold text-fg">{formatMoney(s.quote.last_price, ccy)}</div>
                <ChangeText value={s.quote.change} percent={s.quote.change_percent} currency={ccy} className="text-[13px]" />
                <div className="mt-1 text-xs text-fg-3">
                  Last observed · market time {formatInstant(s.quote.market_time, tz)}
                  {s.quote.session_date && ` · session ${formatSessionDate(s.quote.session_date)}`}
                </div>
              </>
            ) : (
              <div className="max-w-xs text-[13px] text-fg-2">
                <div className="num text-[28px] leading-8 text-fg-3">{DASH}</div>
                {s?.meta.message ?? "No quotation available."}
              </div>
            )}
          </div>
          <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:self-center">
            <StarToggle symbol={symbol} />
            <Button size="sm" icon={<Bell className="size-3.5" aria-hidden />} disabled={readOnly} title={readOnly ? "Read-only demo" : undefined} onClick={() => open({ kind: "alert", symbol, price: s?.quote?.last_price })}>
              Create alert
            </Button>
            <Button
              size="sm"
              icon={<Plus className="size-3.5" aria-hidden />}
              disabled={readOnly || !holdable}
              title={readOnly ? "Read-only demo" : holdReason}
              onClick={() => open({ kind: "transaction", symbol, type: "BUY", currency: account ?? undefined })}
            >
              Add transaction
            </Button>
            <Button size="sm" variant="ghost" icon={<NotebookPen className="size-3.5" aria-hidden />} disabled={readOnly} onClick={() => open({ kind: "journal", symbol })}>
              Note
            </Button>
            <Button
              size="sm"
              variant="ghost"
              icon={<Sparkles className="size-3.5" aria-hidden />}
              title={ai.data && !ai.data.enabled ? `AI research unavailable: ${ai.data.reason}` : "Cited research from the evidence MarketDesk retrieves"}
              onClick={() => open({ kind: "ai", symbol })}
            >
              Ask AI
            </Button>
          </div>
          {holdReason && inst && <p className="w-full text-xs text-fg-3">{holdReason}</p>}
        </div>
      </section>

      <ResearchTabList value={tab} onChange={setTab} />
      {tab === "financials" ? (
        <FinancialsTab symbol={symbol} />
      ) : tab === "filings" ? (
        <FilingsTab symbol={symbol} />
      ) : tab === "events" ? (
        <EventsTab symbol={symbol} />
      ) : tab === "peers" ? (
        <PeersTab symbol={symbol} />
      ) : tab === "valuation" ? (
        <ValuationTab symbol={symbol} />
      ) : (
        <>
      <ChartPanel symbol={symbol} currency={ccy} title="Price history" className="lg:col-span-8" height={400} defaultRange="1Y" />

      <Panel title="Fundamentals" titleId="fund-title" className="lg:col-span-4" meta={fund.data ? <FreshnessBadge meta={fund.data.meta} /> : undefined}>
        {fund.isLoading ? (
          <SkeletonRows rows={7} />
        ) : fund.isError ? (
          <ErrorState message={errorMessage(fund.error)} onRetry={() => fund.refetch()} />
        ) : !f ? (
          <EmptyState title="Fundamentals unavailable">{fund.data?.meta.message ?? "The provider returned no company information."}</EmptyState>
        ) : (
          <>
            <dl>
              <FundRow label="Market cap" kind="absolute" value={formatLargeMoney(f.market_cap, ccy)} />
              <FundRow label="P/E (trailing)" kind="ratio" value={formatRatio(f.pe_ratio)} note={notesFor("p/e")} />
              <FundRow label="Dividend yield" kind="percent" value={formatPercent(f.dividend_yield_percent, { signed: false })} note={notesFor("dividend")} />
              <FundRow label="Price / book" kind="ratio" value={formatRatio(f.price_to_book)} note={notesFor("book")} />
              <FundRow label="52-week high" kind={ccy ?? ""} value={formatMoney(f.fifty_two_week_high, ccy)} />
              <FundRow label="52-week low" kind={ccy ?? ""} value={formatMoney(f.fifty_two_week_low, ccy)} />
              <FundRow label="Last fiscal year end" kind="date" value={formatSessionDate(f.last_fiscal_year_end)} note={notesFor("statement")} />
              <FundRow label="Most recent quarter" kind="date" value={formatSessionDate(f.most_recent_quarter)} note={notesFor("statement")} />
              <FundRow label="Sector" kind="" value={f.sector ?? DASH} />
              <FundRow label="Industry" kind="" value={f.industry ?? DASH} />
            </dl>
            <RangeBar low={f.fifty_two_week_low} high={f.fifty_two_week_high} last={s?.quote?.last_price} currency={ccy} />
            {f.notes.length > 0 && (
              <ul className="mt-3 space-y-1 text-xs leading-4 text-fg-3">
                {f.notes.map((n) => <li key={n}>• {n}</li>)}
              </ul>
            )}
            {s?.quote?.volume != null && (
              <p className="mt-3 text-xs text-fg-3">
                Session volume {formatVolume(s.quote.volume)} — {s.quote.volume_note}
              </p>
            )}
          </>
        )}
      </Panel>

      <Panel title="Corporate actions" titleId="ca-title" className="lg:col-span-4" meta={actions.data ? <FreshnessBadge meta={actions.data.meta} /> : undefined}>
        {actions.isLoading ? (
          <SkeletonRows rows={3} />
        ) : actions.isError ? (
          <ErrorState message={errorMessage(actions.error)} onRetry={() => actions.refetch()} />
        ) : !actions.data?.actions.length ? (
          <p className="text-[13px] text-fg-3">{actions.data?.meta.message ?? "No dividends or splits reported."}</p>
        ) : (
          <>
            <ul className="divide-y divide-line-subtle text-[13px]">
              {actions.data.actions.slice(0, 8).map((a, i) => (
                <li key={i} className="flex items-baseline justify-between gap-3 py-2">
                  <span className="num text-fg-2">{formatSessionDate(a.date)}</span>
                  <span className="min-w-0 flex-1 truncate text-fg">{a.kind === "SPLIT" ? `Split ${a.value}:1` : `Dividend ${formatMoney(a.value, ccy)}`}</span>
                </li>
              ))}
            </ul>
            <InlineNotice className="mt-3">Splits are not applied to your ledger automatically. Record a confirmed SPLIT transaction to adjust holdings once.</InlineNotice>
          </>
        )}
      </Panel>

      <Panel title="Your alerts" titleId="ia-title" className="lg:col-span-4" actions={<Link to="/alerts" className="text-xs text-fg-2 hover:text-fg">All alerts</Link>}>
        {alerts.isLoading ? (
          <SkeletonRows rows={2} />
        ) : myAlerts.length === 0 ? (
          <p className="text-[13px] text-fg-3">No alerts for {symbol}.</p>
        ) : (
          <ul className="divide-y divide-line-subtle text-[13px]">
            {myAlerts.map((a) => (
              <li key={a.id} className="flex items-center justify-between gap-2 py-2">
                <span className="text-fg">
                  {a.direction === "ABOVE" ? "At or above" : "At or below"} <span className="num">{formatMoney(a.target_price, ccy)}</span>
                </span>
                <Pill tone={a.active ? "pos" : "neutral"}>{a.active ? "Armed" : a.events.length ? "Triggered" : "Paused"}</Pill>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel title="Journal notes" titleId="ij-title" className="lg:col-span-4" actions={<Link to={`/journal?symbol=${encodeURIComponent(symbol)}`} className="text-xs text-fg-2 hover:text-fg">Open journal</Link>}>
        {notes.isLoading ? (
          <SkeletonRows rows={2} />
        ) : !notes.data?.items.length ? (
          <p className="text-[13px] text-fg-3">No notes for {symbol}.</p>
        ) : (
          <ul className="divide-y divide-line-subtle text-[13px]">
            {notes.data.items.slice(0, 5).map((n) => (
              <li key={n.id} className="py-2">
                <div className="text-xs text-fg-3">{formatSessionDate(n.entry_date)}</div>
                <div className="truncate text-fg">{n.title}</div>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <ComparePanel symbol={symbol} className="lg:col-span-12" />
        </>
      )}
    </div>
  );
}

const TABS = [
  { value: "overview", label: "Overview" },
  { value: "financials", label: "Financials" },
  { value: "filings", label: "Filings" },
  { value: "events", label: "Events" },
  { value: "peers", label: "Peers" },
  { value: "valuation", label: "Valuation" },
] as const;
type Tab = (typeof TABS)[number]["value"];

/** Accessible tab strip (arrow keys move between tabs); the choice lives in the URL so it survives reloads. */
function ResearchTabList({ value, onChange }: { value: Tab; onChange: (t: Tab) => void }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  return (
    <div role="tablist" aria-label="Instrument sections" className="scrollbar-thin flex gap-1 overflow-x-auto border-b border-line-subtle lg:col-span-12"
      onKeyDown={(e) => {
        const i = TABS.findIndex((t) => t.value === value);
        const next = e.key === "ArrowRight" ? (i + 1) % TABS.length : e.key === "ArrowLeft" ? (i - 1 + TABS.length) % TABS.length : -1;
        if (next >= 0) {
          e.preventDefault();
          onChange(TABS[next].value);
          refs.current[next]?.focus();
        }
      }}
    >
      {TABS.map((t, i) => (
        <button
          key={t.value}
          ref={(el) => { refs.current[i] = el; }}
          role="tab"
          type="button"
          aria-selected={value === t.value}
          tabIndex={value === t.value ? 0 : -1}
          onClick={() => onChange(t.value)}
          className={cn("-mb-px border-b-2 px-3 py-2 text-[13px] whitespace-nowrap max-md:min-h-11", value === t.value ? "border-accent font-medium text-fg" : "border-transparent text-fg-3 hover:text-fg-2")}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
