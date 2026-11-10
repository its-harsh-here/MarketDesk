import { useEffect } from "react";
import { Link, useLocation } from "react-router";
import { ExternalLink } from "lucide-react";
import { Panel } from "@/components/ui/Panel";
import { Pill } from "@/components/ui/Badges";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/States";
import { errorMessage } from "@/lib/api/client";
import { DASH, formatInstant, formatMoney, formatRelative, formatSessionDate } from "@/lib/format";
import { REGION_LABEL } from "@/lib/markets";
import { SECURITY_CODES } from "@/lib/codes";
import { ChartPanel } from "@/features/market/ChartPanel";
import { useActions } from "@/features/market/api";
import { useEarnings } from "@/features/earnings/api";
import { useFilings } from "@/features/research/api";
import { usePeers } from "@/features/screener/api";
import { MetricValue } from "@/features/screener/cells";
import { usePrefs } from "@/features/settings/api";
import { useDescription, type CoverageStatus, type Description } from "./api";
import { PerformancePanel } from "./PerformancePanel";

const STATUS: Record<CoverageStatus, { label: string; tone: "pos" | "neutral" | "warn" | "info" }> = {
  available: { label: "Available", tone: "pos" },
  estimated: { label: "Estimated", tone: "info" },
  missing: { label: "Missing", tone: "warn" },
  not_available: { label: "No source", tone: "neutral" },
  not_configured: { label: "Not configured", tone: "neutral" },
  planned: { label: "Planned", tone: "info" },
  licensed: { label: "Licensed data", tone: "neutral" },
};

function SourceLine({ children }: { children: React.ReactNode }) {
  return <p className="mt-3 text-xs leading-4 text-fg-3">{children}</p>;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-line-subtle/60 py-1.5 text-[13px] last:border-0">
      <dt className="shrink-0 text-fg-2">{label}</dt>
      <dd className="min-w-0 text-right break-words text-fg">{children}</dd>
    </div>
  );
}

/** Terminal T1: the landing view of a security. Every tile names its source and date; gaps say why. */
export function DescriptionTab({ symbol, currency }: { symbol: string; currency: string | null }) {
  const q = useDescription(symbol);
  const { data: prefs } = usePrefs();
  const tz = prefs?.display_timezone ?? "Asia/Kolkata";
  const loc = useLocation();
  const d = q.data;
  useEffect(() => {
    if (d && loc.hash === "#coverage") document.getElementById("coverage-title")?.scrollIntoView({ block: "start" });
  }, [d, loc.hash]);
  return (
    <>
      <ChartPanel symbol={symbol} currency={currency} title="Price history" className="lg:col-span-8" height={320} defaultRange="1Y" />
      <KeyStats q={q} currency={currency} tz={tz} />
      <BusinessSummary q={q} tz={tz} />
      <Identity q={q} tz={tz} />
      <PerformancePanel symbol={symbol} currency={currency} className="lg:col-span-4" />
      <NextEvents symbol={symbol} currency={currency} />
      <LatestFilings symbol={symbol} />
      <PeersStrip symbol={symbol} />
      <Coverage q={q} symbol={symbol} />
    </>
  );
}

type Q = ReturnType<typeof useDescription>;

function Loading({ q }: { q: Q }) {
  return q.isLoading ? <SkeletonRows rows={6} /> : <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />;
}

function KeyStats({ q, currency, tz }: { q: Q; currency: string | null; tz: string }) {
  const d = q.data;
  const groups = d?.metric_groups ?? [];
  return (
    <Panel title="Key statistics" titleId="ks-title" className="lg:col-span-4" refreshing={q.isFetching && !q.isLoading}>
      {!d ? (
        <Loading q={q} />
      ) : (
        <>
          {groups.map((g) => (
            <section key={g} aria-label={g} className="mb-2 last:mb-0">
              <h3 className="mt-1 mb-0.5 text-[11px] font-medium tracking-wider text-fg-3 uppercase">{g}</h3>
              <dl>
                {d.key_stats.stats.filter((s) => s.group === g).map((s) => (
                  <div key={s.key} className="flex items-baseline justify-between gap-3 py-1 text-[13px]">
                    <dt className="text-fg-2" title={s.formula}>{s.label}</dt>
                    <dd className="text-right">
                      <MetricValue def={s} cell={{ v: s.value, why: s.why, as_of: s.as_of }} currency={currency} />
                      {s.value !== null && s.as_of && <span className="ml-1.5 text-[11px] text-fg-3">{formatSessionDate(s.as_of.slice(0, 10))}</span>}
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
          <SourceLine>
            Snapshot {d.key_stats.computed_at ? `computed ${formatInstant(d.key_stats.computed_at, tz)} (${formatRelative(d.key_stats.computed_at)})` : "not computed"} from {d.key_stats.provider} quote, history, fundamentals and statements; each value shows its as-of date. Hover a label for its formula.
          </SourceLine>
        </>
      )}
    </Panel>
  );
}

function BusinessSummary({ q, tz }: { q: Q; tz: string }) {
  const s = q.data?.summary;
  return (
    <Panel title="Business" titleId="biz-title" className="lg:col-span-8">
      {!q.data ? (
        <Loading q={q} />
      ) : s?.status === "available" ? (
        <>
          <div className="max-w-[75ch] space-y-3 text-[14px] leading-6 text-fg">
            {s.text.split("\n\n").map((p, i) => <p key={i}>{p}</p>)}
          </div>
          <SourceLine>
            {s.kind === "filing" ? "Quoted from " : ""}
            {s.source}
            {s.as_of && <> · filed {formatSessionDate(s.as_of)}</>}
            {"period" in s && s.period && <> · period ending {formatSessionDate(s.period)}</>}
            {s.fetched_at && <> · retrieved {formatInstant(s.fetched_at, tz)}</>}
            {s.url && (
              <>
                {" · "}
                <a href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-info underline decoration-info/40 underline-offset-2 hover:decoration-info">
                  Open the filing <ExternalLink className="size-3" aria-hidden />
                </a>
              </>
            )}
          </SourceLine>
        </>
      ) : (
        <EmptyState title="No business description">{s?.reason}</EmptyState>
      )}
    </Panel>
  );
}

function Identity({ q, tz }: { q: Q; tz: string }) {
  const i = q.data?.identity;
  return (
    <Panel title="Identity" titleId="id-title" className="lg:col-span-4">
      {!i ? (
        <Loading q={q} />
      ) : (
        <>
          <dl>
            <Row label="Name">{i.sec?.name ?? i.name ?? DASH}</Row>
            <Row label="Listing"><span className="num">{i.symbol}</span>{i.exchange ? ` · ${i.exchange}` : ""}{i.mic ? ` (${i.mic})` : ""}</Row>
            <Row label="Country · currency">{i.country ? (REGION_LABEL[i.country] ?? i.country) : DASH} · {i.currency ?? DASH}</Row>
            <Row label="Type · time zone">{i.kind ?? DASH} · {i.timezone ?? DASH}</Row>
            <Row label="Sector">{i.sector ?? DASH}</Row>
            <Row label="Industry">{i.industry ?? DASH}</Row>
            {i.sec?.industry && <Row label="SEC industry (SIC)">{i.sec.industry}{i.sec.sic ? ` (${i.sec.sic})` : ""}</Row>}
            <Row label="Fiscal year end">{i.sec?.fiscal_year_end ? `${i.sec.fiscal_year_end} (month-day, SEC)` : i.last_fiscal_year_end ? formatSessionDate(i.last_fiscal_year_end) : DASH}</Row>
            {i.cik !== null && <Row label="SEC CIK"><span className="num">{i.cik}</span></Row>}
            {i.identifiers.map((x) => (
              <Row key={x.scheme} label={["CIK", "ISIN", "FIGI", "CUSIP"].includes(x.scheme.toUpperCase()) ? x.scheme.toUpperCase() : `${x.scheme[0].toUpperCase()}${x.scheme.slice(1)} symbol`}><span className="num">{x.value}</span></Row>
            ))}
            {i.sec && i.sec.tickers.length > 0 && (
              <Row label="All listings (SEC)">{i.sec.tickers.map((t, k) => `${t}${i.sec?.exchanges[k] ? ` (${i.sec.exchanges[k]})` : ""}`).join(", ")}</Row>
            )}
            {i.related_listings.length > 0 && (
              <Row label="Related in MarketDesk">
                {i.related_listings.map((r) => <Link key={r.symbol} to={`/instrument/${encodeURIComponent(r.symbol)}`} className="num mr-2 text-info underline decoration-info/40 underline-offset-2 hover:decoration-info">{r.symbol}</Link>)}
              </Row>
            )}
          </dl>
          <SourceLine>
            Listing identity: {i.identity_source ?? "provider"}
            {i.identity_verified_at && `, verified ${formatInstant(i.identity_verified_at, tz)}`}. Classification: {i.classification_source ?? "not reported"}
            {i.fetched_at && `, retrieved ${formatInstant(i.fetched_at, tz)}`}
            {i.sec?.fetched_at && `. SEC profile retrieved ${formatInstant(i.sec.fetched_at, tz)}`}.
          </SourceLine>
        </>
      )}
    </Panel>
  );
}

function NextEvents({ symbol, currency }: { symbol: string; currency: string | null }) {
  const e = useEarnings(symbol);
  const a = useActions(symbol);
  const cal = e.data?.calendar;
  const lastAction = a.data?.actions[0];
  return (
    <Panel title="Events" titleId="ev-title" className="lg:col-span-4" actions={<Link to={`?tab=earnings`} className="text-xs text-fg-2 hover:text-fg">Earnings</Link>}>
      {e.isLoading ? (
        <SkeletonRows rows={3} />
      ) : (
        <>
          <dl>
            <Row label="Next results">
              {cal?.next ? (
                <>
                  {formatSessionDate(cal.next.date)} <Pill tone="info">{cal.next.basis === "deadline" ? "deadline" : "estimate"}</Pill>
                </>
              ) : DASH}
            </Row>
            <Row label="Last results">{cal?.past[0] ? (cal.past[0].url ? <a href={cal.past[0].url} target="_blank" rel="noreferrer" className="text-info underline decoration-info/40 underline-offset-2 hover:decoration-info">{formatSessionDate(cal.past[0].date)}</a> : formatSessionDate(cal.past[0].date)) : DASH}</Row>
            <Row label="Last dividend or split">
              {lastAction ? `${formatSessionDate(lastAction.date)} · ${lastAction.kind === "SPLIT" ? `split ${lastAction.value}:1` : `dividend ${formatMoney(lastAction.value, currency)}`}` : DASH}
            </Row>
          </dl>
          <SourceLine>
            {cal?.next?.explanation ?? cal?.note ?? ""} {cal?.source ? `Results: ${cal.source}.` : ""} Dividends and splits: {a.data?.meta.source ?? "provider"}. No date here is an announced date unless the source says so.
          </SourceLine>
        </>
      )}
    </Panel>
  );
}

function LatestFilings({ symbol }: { symbol: string }) {
  const f = useFilings(symbol);
  const env = f.data;
  return (
    <Panel title="Latest filings" titleId="lf-title" className="lg:col-span-4" actions={<Link to={`?tab=filings`} className="text-xs text-fg-2 hover:text-fg">All filings</Link>}>
      {f.isLoading ? (
        <SkeletonRows rows={3} />
      ) : env?.data && env.data.length > 0 ? (
        <>
          <ul className="divide-y divide-line-subtle text-[13px]">
            {env.data.slice(0, 3).map((r) => (
              <li key={r.accession} className="flex items-baseline gap-3 py-2">
                <span className="num shrink-0 text-fg-2">{formatSessionDate(r.filing_date)}</span>
                <span className="num shrink-0 text-fg">{r.form}</span>
                <a href={r.document_url ?? r.index_url} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate text-info underline decoration-info/40 underline-offset-2 hover:decoration-info">{r.description}</a>
              </li>
            ))}
          </ul>
          <SourceLine>SEC EDGAR{env.fetched_at ? `, retrieved ${formatRelative(env.fetched_at)}` : ""}.</SourceLine>
        </>
      ) : (
        <p className="text-[13px] text-fg-3">{env?.reason ?? (f.isError ? errorMessage(f.error) : "No filings listed.")}</p>
      )}
    </Panel>
  );
}

function PeersStrip({ symbol }: { symbol: string }) {
  const p = usePeers(symbol);
  const rows = (p.data?.rows ?? []).filter((r) => r.symbol !== symbol).slice(0, 5);
  return (
    <Panel title="Peers" titleId="pe-title" className="lg:col-span-12" actions={<Link to={`?tab=peers`} className="text-xs text-fg-2 hover:text-fg">Compare peers</Link>}>
      {p.isLoading ? (
        <SkeletonRows rows={3} />
      ) : rows.length === 0 ? (
        <p className="text-[13px] text-fg-3">{p.data?.note || (p.isError ? errorMessage(p.error) : "No peers yet: add instruments with the same sector to a watchlist, or choose peers on the Peers tab.")}</p>
      ) : (
        <>
          <ul className="divide-y divide-line-subtle text-[13px]">
            {rows.map((r) => {
              const ch = r.metrics?.change_1d_pct?.v;
              return (
                <li key={r.symbol} className="flex items-baseline gap-3 py-1.5">
                  <Link to={`/instrument/${encodeURIComponent(r.symbol)}`} className="num shrink-0 text-info underline decoration-info/40 underline-offset-2 hover:decoration-info">{r.symbol}</Link>
                  <span className="min-w-0 flex-1 truncate text-fg-3">{r.name}</span>
                  <span className={`num shrink-0 ${ch == null ? "text-fg-3" : Number(ch) >= 0 ? "text-pos" : "text-neg"}`}>{ch == null ? DASH : `${Number(ch) >= 0 ? "+" : ""}${Number(ch).toFixed(2)}%`}</span>
                </li>
              );
            })}
          </ul>
          <SourceLine>{p.data?.source === "saved" ? "Your saved peers" : "Suggested from your universes (same industry, then sector)"} · 1-day change from each snapshot.</SourceLine>
        </>
      )}
    </Panel>
  );
}

function Coverage({ q, symbol }: { q: Q; symbol: string }) {
  const d: Description | undefined = q.data;
  return (
    <Panel title="Coverage for this listing" titleId="coverage-title" className="lg:col-span-12">
      {!d ? (
        <Loading q={q} />
      ) : (
        <>
        <ul className="divide-y divide-line-subtle md:hidden" aria-label={`Data coverage for ${symbol}`}>
          {d.coverage.map((c) => {
            const code = SECURITY_CODES.find((x) => x.code === c.code);
            return (
              <li key={c.domain} className="py-2 text-[13px]">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-fg">{c.domain}</span>
                  <span className="flex shrink-0 items-center gap-2">
                    <Pill tone={STATUS[c.status].tone}>{STATUS[c.status].label}</Pill>
                    {code && c.tab && <Link to={c.tab === "description" ? "?" : `?tab=${c.tab}`} className="num text-info underline decoration-info/40 underline-offset-2 hover:decoration-info" aria-label={`${code.code}: ${code.label}`}>{code.code}</Link>}
                  </span>
                </div>
                {(c.source || c.note) && <p className="mt-0.5 text-xs text-fg-3">{[c.source, c.note].filter(Boolean).join(" · ")}</p>}
              </li>
            );
          })}
        </ul>
        <div tabIndex={0} className="scroll-x scrollbar-thin overflow-x-auto max-md:hidden">
          <table className="w-full text-[13px]">
            <caption className="sr-only">Which kinds of data are available for {symbol}, from which source, and why others are not</caption>
            <thead>
              <tr className="border-b border-line-subtle text-xs text-fg-3">
                <th scope="col" className="py-1.5 text-left font-medium">Data</th>
                <th scope="col" className="py-1.5 pl-3 text-left font-medium">Status</th>
                <th scope="col" className="py-1.5 pl-3 text-left font-medium">Source</th>
                <th scope="col" className="py-1.5 pl-3 text-left font-medium">Note</th>
                <th scope="col" className="py-1.5 pl-3 text-left font-medium">Code</th>
              </tr>
            </thead>
            <tbody>
              {d.coverage.map((c) => {
                const code = SECURITY_CODES.find((x) => x.code === c.code);
                return (
                  <tr key={c.domain} className="border-b border-line-subtle/60 align-top">
                    <th scope="row" className="py-1.5 pr-2 text-left font-normal text-fg">{c.domain}</th>
                    <td className="py-1.5 pl-3"><Pill tone={STATUS[c.status].tone}>{STATUS[c.status].label}</Pill></td>
                    <td className="py-1.5 pl-3 text-fg-2">{c.source ?? DASH}</td>
                    <td className="py-1.5 pl-3 text-xs text-fg-3">{c.note ?? ""}</td>
                    <td className="num py-1.5 pl-3">
                      {code && c.tab ? <Link to={c.tab === "description" ? "?" : `?tab=${c.tab}`} className="text-info underline decoration-info/40 underline-offset-2 hover:decoration-info" aria-label={`${code.code}: ${code.label}`}>{code.code}</Link> : (c.code ?? "")}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        </>
      )}
    </Panel>
  );
}
