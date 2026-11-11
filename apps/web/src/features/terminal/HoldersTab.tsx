import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { Panel } from "@/components/ui/Panel";
import { ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { api, errorMessage } from "@/lib/api/client";
import { cn } from "@/lib/cn";
import { DASH, formatCompact, formatLargeMoney, formatMoney, formatPercent, formatRelative, formatSessionDate } from "@/lib/format";

interface HolderRow { holder: string; shares: string | null; pct_held: string | null; value: string | null; reported: string | null; pct_change: string | null }
interface Txn {
  date: string | null; insider: string; roles: string[]; code: string | null; action: string; acquired: boolean | null;
  shares: string | null; price: string | null; value: string | null; owned_after: string | null; direct: boolean;
  plan_10b5_1: boolean; filed: string; url: string | null; form: string;
}
interface Side { count: number; shares: string; value: string; insiders: number }
interface Major { holder: string; type: string | null; shares: string | null; percent: string | null; event_date: string | null; filed: string; form: string;
  url: string | null; kind: string; below_threshold: boolean; persons: number }
interface Holding { insider: string; roles: string[]; shares: string; as_of: string | null; url: string | null }
interface Ownership {
  symbol: string;
  holders: { status: string; reason?: string; source?: string; fetched_at?: string | null; insiders_pct?: string | null; institutions_pct?: string | null;
    institutions_float_pct?: string | null; institutions_count?: number | null; institutions?: HolderRow[]; funds?: HolderRow[] };
  major?: { status?: string; reason?: string; source: string; filings_read?: number; holders?: Major[]; note?: string };
  insiders: { status?: string; reason?: string; source: string; filings_read?: number; filings_failed?: number; transactions?: Txn[]; holdings?: Holding[];
    summary?: { days: number; buys: Side; sales: Side }[]; note?: string };
  notes: string[];
}

const pct = (v: string | null | undefined, signed = false) => (v === null || v === undefined ? DASH : formatPercent(Number(v) * 100, { signed }));

function Breakdown({ h }: { h: Ownership["holders"] }) {
  const ins = Number(h.insiders_pct ?? 0), inst = Number(h.institutions_pct ?? 0);
  const other = Math.max(0, 1 - ins - inst);
  return (
    <div className="space-y-3">
      <div className="flex h-4 overflow-hidden rounded-full bg-elevated" role="img"
        aria-label={`Insiders ${pct(h.insiders_pct)}, institutions ${pct(h.institutions_pct)}, others ${formatPercent(other * 100, { signed: false })}`}>
        <span className="bg-accent transition-[width] duration-700" style={{ width: `${ins * 100}%` }} />
        <span className="bg-info transition-[width] duration-700" style={{ width: `${inst * 100}%` }} />
        <span className="bg-fg-3/40" style={{ width: `${other * 100}%` }} />
      </div>
      <dl className="grid grid-cols-2 gap-3 text-[13px] sm:grid-cols-4">
        <div><dt className="text-xs text-fg-3"><span className="mr-1 inline-block size-2 rounded-sm bg-accent" />Insiders</dt><dd className="num text-base font-semibold">{pct(h.insiders_pct)}</dd></div>
        <div><dt className="text-xs text-fg-3"><span className="mr-1 inline-block size-2 rounded-sm bg-info" />Institutions</dt><dd className="num text-base font-semibold">{pct(h.institutions_pct)}</dd></div>
        <div><dt className="text-xs text-fg-3">Institutions, % of float</dt><dd className="num">{pct(h.institutions_float_pct)}</dd></div>
        <div><dt className="text-xs text-fg-3">Institutions holding</dt><dd className="num">{h.institutions_count ?? DASH}</dd></div>
      </dl>
    </div>
  );
}

function HolderTable({ rows, label, currency }: { rows: HolderRow[]; label: string; currency: string | null }) {
  if (!rows.length) return <p className="text-[13px] text-fg-3">None reported.</p>;
  return (
    <div tabIndex={0} className="scroll-x scrollbar-thin overflow-x-auto">
      <table className="w-full min-w-[30rem] text-[13px]" aria-label={label}>
        <thead><tr className="border-b border-line-subtle text-xs text-fg-3">
          <th scope="col" className="py-1.5 text-left font-medium">Holder</th>
          <th scope="col" className="px-2 text-right font-medium">Shares</th>
          <th scope="col" className="px-2 text-right font-medium">% out</th>
          <th scope="col" className="px-2 text-right font-medium">Change</th>
          <th scope="col" className="px-2 text-right font-medium">Value</th>
          <th scope="col" className="pl-2 text-right font-medium">Reported</th>
        </tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.holder} className="border-b border-line-subtle/60">
            <th scope="row" className="py-1.5 text-left font-normal text-fg">{r.holder}</th>
            <td className="num px-2 text-right text-fg-2">{formatCompact(r.shares)}</td>
            <td className="num px-2 text-right">{pct(r.pct_held)}</td>
            <td className={cn("num px-2 text-right", Number(r.pct_change) > 0 ? "text-pos" : Number(r.pct_change) < 0 ? "text-neg" : "text-fg-3")}>{pct(r.pct_change, true)}</td>
            <td className="num px-2 text-right text-fg-2">{r.value ? formatLargeMoney(r.value, currency) : DASH}</td>
            <td className="num pl-2 text-right text-fg-3">{r.reported ? formatSessionDate(r.reported) : DASH}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

const TYPES: Record<string, string> = { IA: "Investment adviser", IV: "Investment company", BD: "Broker-dealer", BK: "Bank", HC: "Parent holding company",
  IC: "Insurance company", EP: "Benefit plan", CO: "Corporation", PN: "Partnership", IN: "Individual", FI: "Non-US institution", OO: "Other" };

function MajorHolders({ m, symbol }: { m: NonNullable<Ownership["major"]>; symbol: string }) {
  if (!m.holders) return <InlineNotice>{m.reason}</InlineNotice>;
  if (!m.holders.length)
    return <p className="text-[13px] text-fg-3">No structured Schedule 13D/13G filings (since December 2024) are listed for this issuer.</p>;
  const top = Math.max(...m.holders.map((h) => Number(h.percent ?? 0)), 5);
  return (
    <ul className="space-y-2.5" aria-label={`Holders above 5% of ${symbol}`}>
      {m.holders.map((h) => (
        <li key={h.holder + h.filed} className="text-[13px]">
          <div className="flex items-baseline justify-between gap-3">
            <span className="min-w-0 truncate text-fg" title={h.holder}>{h.holder}</span>
            <span className={cn("num shrink-0 font-semibold", h.below_threshold ? "text-fg-3" : "text-fg")}>
              {h.percent !== null ? formatPercent(Number(h.percent), { signed: false }) : DASH}
            </span>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-elevated" aria-hidden>
            <span className={cn("block h-full rounded-full transition-[width] duration-700", h.below_threshold ? "bg-fg-3/50" : "bg-info")}
              style={{ width: `${(Number(h.percent ?? 0) / top) * 100}%` }} />
          </div>
          <div className="mt-0.5 text-xs text-fg-3">
            {formatCompact(h.shares)} shares · {h.kind === "13D" ? "13D (active)" : "13G (passive)"}
            {h.type ? ` · ${TYPES[h.type] ?? h.type}` : ""}
            {h.below_threshold ? " · reported falling below 5%" : ""} · as of {h.event_date ? formatSessionDate(h.event_date) : formatSessionDate(h.filed)} ·{" "}
            {h.url ? <a href={h.url} target="_blank" rel="noopener noreferrer" className="underline decoration-fg-3/40 underline-offset-2 hover:text-fg-2">{h.form} filed {formatSessionDate(h.filed)} <ExternalLink className="inline size-3" aria-hidden /></a> : h.form}
          </div>
        </li>
      ))}
    </ul>
  );
}

function InsiderHoldings({ rows, symbol }: { rows: Holding[]; symbol: string }) {
  if (!rows.length) return <p className="text-[13px] text-fg-3">No direct holdings reported in the latest Form 4 filings.</p>;
  return (
    <div tabIndex={0} className="scroll-x scrollbar-thin max-h-[24rem] overflow-auto">
      <table className="w-full min-w-[26rem] text-[13px]" aria-label={`Insider holdings in ${symbol}`}>
        <thead className="sticky top-0 bg-panel"><tr className="border-b border-line-subtle text-xs text-fg-3">
          <th scope="col" className="py-1.5 text-left font-medium">Insider</th>
          <th scope="col" className="px-2 text-right font-medium">Shares held (direct)</th>
          <th scope="col" className="pl-2 text-right font-medium">As of</th>
        </tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.insider} className="border-b border-line-subtle/60 align-top">
            <th scope="row" className="py-1.5 text-left font-normal"><span className="text-fg">{r.insider}</span><span className="block text-xs text-fg-3">{r.roles.join(", ") || "—"}</span></th>
            <td className="num px-2 text-right">{formatCompact(r.shares)}</td>
            <td className="num pl-2 text-right text-fg-3">{r.url ? <a href={r.url} target="_blank" rel="noopener noreferrer" className="underline decoration-fg-3/40 underline-offset-2 hover:text-fg-2">{r.as_of ? formatSessionDate(r.as_of) : "filing"}</a> : r.as_of ? formatSessionDate(r.as_of) : DASH}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

/** Terminal T3: who owns the company and what insiders have been doing. */
export function HoldersTab({ symbol, currency }: { symbol: string; currency: string | null }) {
  const q = useQuery({
    queryKey: ["terminal", "ownership", symbol],
    queryFn: ({ signal }) => api.get<Ownership>("/api/terminal/ownership", { symbol }, signal),
    staleTime: 30 * 60_000,
    retry: false,
  });
  const d = q.data;
  if (q.isLoading) return <Panel title="Ownership" titleId="own-title" className="lg:col-span-12"><SkeletonRows rows={8} /></Panel>;
  if (q.isError || !d) return <Panel title="Ownership" titleId="own-title" className="lg:col-span-12"><ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} /></Panel>;
  const h = d.holders, ins = d.insiders;
  return (
    <>
      <div className="space-y-4 lg:col-span-5 lg:self-start">
        {d.major && d.major.status !== "not_applicable" && (
          <Panel title="Holders above 5%" titleId="major-title" refreshing={q.isFetching} meta={d.major.source} wrapHeader>
            <MajorHolders m={d.major} symbol={symbol} />
            {d.major.note && <p className="mt-3 text-xs leading-4 text-fg-3">{d.major.note}</p>}
          </Panel>
        )}
        <Panel title="Ownership summary" titleId="own-title" refreshing={q.isFetching}
          meta={h.source ? `${h.source}${h.fetched_at ? ` · fetched ${formatRelative(h.fetched_at)}` : ""}` : undefined}>
          {h.reason && !h.source ? <InlineNotice>{h.reason}</InlineNotice> : <Breakdown h={h} />}
          {d.notes.map((n) => <p key={n} className="mt-3 text-xs text-fg-3">{n}</p>)}
        </Panel>
        {ins.holdings && (
          <Panel title="Insider holdings" titleId="insh-title" meta="SEC Form 4 · shares held after each insider's latest reported trade" wrapHeader>
            <InsiderHoldings rows={ins.holdings} symbol={symbol} />
          </Panel>
        )}
      </div>
      <Panel title="Insider transactions" titleId="ins-title" className="lg:col-span-7" meta={ins.source} wrapHeader>
        {!ins.transactions ? (
          <InlineNotice>{ins.reason}</InlineNotice>
        ) : (
          <div className="space-y-3">
            {ins.summary && (
              <div className="grid grid-cols-2 gap-3 text-[13px]">
                {ins.summary.map((s) => (
                  <div key={s.days} className="rounded-[var(--radius-control)] border border-line-subtle p-2.5">
                    <div className="text-xs text-fg-3">Open-market trades, last {s.days === 90 ? "90 days" : "12 months"}</div>
                    <div className="mt-1 flex justify-between"><span className="text-pos">▲ Buys {s.buys.count}</span><span className="num">{formatLargeMoney(s.buys.value, currency)}</span></div>
                    <div className="flex justify-between"><span className="text-neg">▼ Sales {s.sales.count}</span><span className="num">{formatLargeMoney(s.sales.value, currency)}</span></div>
                  </div>
                ))}
              </div>
            )}
            {ins.transactions.length === 0 ? <p className="text-[13px] text-fg-3">No non-derivative transactions in the latest Form 4 filings.</p> : (
              <div tabIndex={0} className="scroll-x scrollbar-thin max-h-[30rem] overflow-auto">
                <table className="w-full min-w-[40rem] text-[13px]" aria-label={`Insider transactions in ${symbol}`}>
                  <thead className="sticky top-0 bg-panel"><tr className="border-b border-line-subtle text-xs text-fg-3">
                    <th scope="col" className="py-1.5 text-left font-medium">Date</th>
                    <th scope="col" className="px-2 text-left font-medium">Insider</th>
                    <th scope="col" className="px-2 text-left font-medium">Transaction</th>
                    <th scope="col" className="px-2 text-right font-medium">Shares</th>
                    <th scope="col" className="px-2 text-right font-medium">Price</th>
                    <th scope="col" className="px-2 text-right font-medium">Value</th>
                    <th scope="col" className="pl-2 text-right font-medium">Held after</th>
                  </tr></thead>
                  <tbody>{ins.transactions.map((t, i) => (
                    <tr key={i} className="border-b border-line-subtle/60 align-top">
                      <td className="num py-1.5 text-fg-2">{t.date ? formatSessionDate(t.date) : DASH}</td>
                      <td className="px-2"><span className="text-fg">{t.insider}</span><span className="block text-xs text-fg-3">{t.roles.join(", ") || "—"}</span></td>
                      <td className="px-2">
                        <span className={cn(t.code === "P" ? "text-pos" : t.code === "S" ? "text-neg" : "text-fg-2")}>{t.action}</span>
                        <span className="block text-xs text-fg-3">
                          {t.direct ? "direct" : "indirect"}{t.plan_10b5_1 ? " · 10b5-1 plan" : ""} ·{" "}
                          {t.url ? <a href={t.url} target="_blank" rel="noopener noreferrer" className="underline decoration-fg-3/40 underline-offset-2 hover:text-fg-2">Form {t.form} filed {formatSessionDate(t.filed)} <ExternalLink className="inline size-3" aria-hidden /></a> : `filed ${t.filed}`}
                        </span>
                      </td>
                      <td className="num px-2 text-right">{t.acquired === false ? "−" : t.acquired ? "+" : ""}{formatCompact(t.shares)}</td>
                      <td className="num px-2 text-right">{t.price && Number(t.price) > 0 ? formatMoney(t.price, currency) : DASH}</td>
                      <td className="num px-2 text-right">{t.value ? formatLargeMoney(t.value, currency) : DASH}</td>
                      <td className="num pl-2 text-right text-fg-2">{formatCompact(t.owned_after)}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
            <p className="text-xs leading-4 text-fg-3">{ins.note} {ins.filings_failed ? `${ins.filings_failed} filing(s) could not be read.` : ""}</p>
          </div>
        )}
      </Panel>
      {h.institutions && (
        <Panel title="Top institutional holders" titleId="inst-title" className="lg:col-span-6">
          <HolderTable rows={h.institutions} label={`Top institutional holders of ${symbol}`} currency={currency} />
        </Panel>
      )}
      {h.funds && (
        <Panel title="Top fund holders" titleId="fund-title" className="lg:col-span-6">
          <HolderTable rows={h.funds} label={`Top fund holders of ${symbol}`} currency={currency} />
        </Panel>
      )}
    </>
  );
}
