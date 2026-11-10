import { Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { Pill } from "@/components/ui/Badges";
import { Button, IconButton } from "@/components/ui/Button";
import { ChangeText } from "@/components/ui/Change";
import { Field, Input, Select } from "@/components/ui/Form";
import { Panel } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { Sparkline } from "@/components/ui/Sparkline";
import { EmptyState, ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { errorMessage } from "@/lib/api/client";
import { DASH, formatNumber, formatPercent, formatSessionDate, formatInstant } from "@/lib/format";
import { cn } from "@/lib/cn";
import { useSession } from "@/features/settings/api";
import { SymbolPicker } from "@/features/search/SymbolPicker";
import { parseSpec, specKey, useUniverses, type UniverseSpec } from "@/features/screener/api";
import { useLinkMutations, useLinks, useSectorRelative, useWatchboard, type Change, type MacroSeries, type Window } from "./api";
import { ConverterPanel } from "./ConverterPanel";

const WINDOWS: { value: Window; label: string }[] = [
  { value: "1w", label: "1W" },
  { value: "1m", label: "1M" },
  { value: "3m", label: "3M" },
  { value: "1y", label: "1Y" },
];
const DIRECTION = { up_helps: "A rise helps", up_hurts: "A rise hurts", unclear: "Unclear" } as const;
const RELATION = ["cost", "revenue", "rates", "fx", "demand", "other"] as const;

function ChangeValue({ c }: { c: Change | null | undefined }) {
  if (!c || c.value === null) return <span className="num text-fg-3">{DASH}</span>;
  if (c.unit === "pp") {
    const n = Number(c.value);
    return <span className={cn("num", n > 0 ? "text-pos" : n < 0 ? "text-neg" : "text-fg-2")}>{n > 0 ? "+" : ""}{formatNumber(n, 2)} pp</span>;
  }
  return <ChangeText percent={c.value} showAmount={false} />;
}

export function MacroPage() {
  const [window, setWindow] = useState<Window>("1w");
  const q = useWatchboard(window);
  const w = q.data;
  const groups = useMemo(() => {
    const g = new Map<string, MacroSeries[]>();
    for (const s of w?.series ?? []) g.set(s.group, [...(g.get(s.group) ?? []), s]);
    return [...g.entries()];
  }, [w]);
  return (
    <div className="grid grid-cols-1 gap-4 p-4 md:p-6 lg:grid-cols-12 lg:gap-5">
      <Panel title="Macro watchboard" titleId="mw-title" className="lg:col-span-12" refreshing={q.isFetching && !q.isLoading} meta={w ? `${w.provider} · daily market series` : undefined}>
        {q.isLoading ? (
          <SkeletonRows rows={6} />
        ) : q.isError ? (
          <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
        ) : w ? (
          <div className="space-y-4">
            {groups.map(([g, items]) => (
              <section key={g} aria-label={g}>
                <h3 className="mb-2 text-xs font-medium tracking-wide text-fg-3 uppercase">{g}</h3>
                <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                  {items.map((s) => <SeriesCard key={s.symbol} s={s} />)}
                </ul>
              </section>
            ))}
            <p className="text-xs leading-4 text-fg-3">{w.note}</p>
          </div>
        ) : null}
      </Panel>
      <ConverterPanel className="lg:col-span-12 lg:order-last" />
      <Panel title="What moved" titleId="mb-title" className="lg:col-span-7" actions={<Segmented label="Window" value={window} onChange={setWindow} options={WINDOWS} />}>
        {w ? (
          w.briefing.items.length ? (
            <div className="space-y-2">
              <ol className="space-y-2 text-[13px]">
                {w.briefing.items.map((i) => (
                  <li key={i.series}>
                    <p>{i.text}</p>
                    {i.linked.map((l) => (
                      <p key={l.symbol} className="mt-0.5 text-xs text-fg-2">
                        Your link: <Link to={`/instrument/${encodeURIComponent(l.symbol)}`} className="num hover:text-accent-text">{l.symbol}</Link> · {l.relation} · {DIRECTION[l.direction as keyof typeof DIRECTION]}{l.note ? ` — “${l.note}”` : ""}
                      </p>
                    ))}
                  </li>
                ))}
              </ol>
              <p className="text-xs leading-4 text-fg-3">{w.briefing.note}</p>
            </div>
          ) : (
            <EmptyState title="No changes to report for this window" />
          )
        ) : (
          <SkeletonRows rows={4} />
        )}
      </Panel>
      <Panel title="Official statistics and release calendar" titleId="mo-title" className="lg:col-span-5">
        <ul className="space-y-3 text-[13px]">
          {(w?.not_configured ?? []).map((n) => (
            <li key={n.name}>
              <p className="font-medium">{n.name} <Pill tone="neutral" className="py-0">{n.status}</Pill></p>
              <p className="text-xs text-fg-2">{n.source}</p>
              <p className="text-xs text-fg-3">{n.why}</p>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs leading-4 text-fg-3">Release dates and revisions are shown only from a source that publishes them; nothing is estimated here.</p>
      </Panel>
      <SectorRelativePanel />
      <ExposurePanel series={w?.series ?? []} />
    </div>
  );
}

function SeriesCard({ s }: { s: MacroSeries }) {
  return (
    <li className="rounded-[var(--radius-control)] border border-line-subtle p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-[13px] font-medium" title={s.name}>{s.name}</p>
          <p className="num text-xs text-fg-3">{s.symbol}</p>
        </div>
        {s.spark.length > 1 && <Sparkline points={s.spark.map(([date, close]) => ({ date, close }))} width={72} height={24} label={`${s.name}, last 60 sessions`} />}
      </div>
      {s.value === null ? (
        <p className="mt-2 text-xs text-fg-3">{s.message ?? "No data from the provider."}</p>
      ) : (
        <>
          <p className="mt-1.5 flex items-baseline gap-2">
            <span className="num text-lg font-semibold">{formatNumber(s.value, 2)}</span>
            <span className="text-xs text-fg-3">{s.unit}</span>
          </p>
          <p className="text-[13px]"><ChangeValue c={s.change_1d} /> <span className="text-xs text-fg-3">1D</span></p>
          <dl className="mt-1 grid grid-cols-4 gap-1 text-[11px]">
            {WINDOWS.map((wnd) => (
              <div key={wnd.value} title={s.changes[wnd.value]?.from ? `since ${s.changes[wnd.value]!.from}` : "no value that far back"}>
                <dt className="text-fg-3">{wnd.label}</dt>
                <dd><ChangeValue c={s.changes[wnd.value]} /></dd>
              </div>
            ))}
          </dl>
          <p className="mt-1.5 text-[11px] leading-4 text-fg-3">
            {s.provider} · {s.frequency} · as of {s.session_date ? formatSessionDate(s.session_date) : DASH}
            {s.observed && s.observed.length > 10 ? ` (${formatInstant(s.observed)})` : ""} · {s.revision}
            {s.status === "stale" ? <span className="text-warn"> · stale</span> : null}
          </p>
        </>
      )}
    </li>
  );
}

function SectorRelativePanel() {
  const universes = useUniverses();
  const [spec, setSpec] = useState<UniverseSpec | null>(null);
  const [metric, setMetric] = useState("return_3m_pct");
  const u = spec ?? (universes.data?.options.length ? { kind: "watchlists" as const } : null);
  const q = useSectorRelative(u, metric);
  return (
    <Panel title="Sector-relative performance" titleId="sr-title" className="lg:col-span-7" wrapHeader
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Select aria-label="Universe" className="h-8 w-48" value={u ? specKey(u) : ""} onChange={(e) => setSpec(parseSpec(e.target.value))}>
            {(universes.data?.options ?? []).map((o) => <option key={specKey(o)} value={specKey(o)}>{o.label}</option>)}
          </Select>
          <Segmented label="Return window" value={metric} onChange={setMetric}
            options={[{ value: "return_1m_pct", label: "1M" }, { value: "return_3m_pct", label: "3M" }, { value: "return_1y_pct", label: "1Y" }]} />
        </div>
      }
    >
      {q.isLoading ? (
        <SkeletonRows rows={5} />
      ) : q.isError ? (
        <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
      ) : !q.data?.rows.length ? (
        <EmptyState title="No members with data">Load data for this universe on the <Link to="/screener" className="text-accent-text underline decoration-accent/40 underline-offset-2 hover:decoration-accent">Screener</Link>.</EmptyState>
      ) : (
        <div className="space-y-2">
          <div tabIndex={0} className="scroll-x scrollbar-thin relative overflow-x-auto">
            <table className="w-full min-w-[560px] text-[13px]">
              <caption className="sr-only">Return against the sector average and the market benchmark</caption>
              <thead>
                <tr className="border-b border-line-subtle text-xs text-fg-3">
                  <th scope="col" className="py-1.5 text-left font-medium">Instrument</th>
                  <th scope="col" className="py-1.5 text-left font-medium">Sector</th>
                  <th scope="col" className="py-1.5 text-right font-medium">Return</th>
                  <th scope="col" className="py-1.5 text-right font-medium">vs sector</th>
                  <th scope="col" className="py-1.5 text-right font-medium">vs benchmark</th>
                </tr>
              </thead>
              <tbody>
                {q.data.rows.map((r) => (
                  <tr key={r.symbol} className="border-b border-line-subtle/60">
                    <td className="py-1.5"><Link to={`/instrument/${encodeURIComponent(r.symbol)}`} className="num hover:text-accent-text">{r.symbol}</Link></td>
                    <td className="py-1.5 text-xs text-fg-2">{r.sector} <span className="text-fg-3">({r.sector_n})</span></td>
                    <td className="num py-1.5 text-right" title={r.why ?? undefined}>{r.return_pct === null ? DASH : formatPercent(r.return_pct)}</td>
                    <td className="py-1.5 text-right" title={r.sector_avg_pct ? `Sector average ${formatPercent(r.sector_avg_pct)}` : "Needs two or more members in the sector"}>
                      <ChangeValue c={r.vs_sector_pp === null ? null : { value: r.vs_sector_pp, unit: "pp" }} />
                    </td>
                    <td className="py-1.5 text-right" title={r.benchmark_pct ? `Benchmark ${formatPercent(r.benchmark_pct)}` : "No benchmark series for this market"}>
                      <ChangeValue c={r.vs_benchmark_pp === null ? null : { value: r.vs_benchmark_pp, unit: "pp" }} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs leading-4 text-fg-3">{q.data.method}</p>
        </div>
      )}
    </Panel>
  );
}

function ExposurePanel({ series }: { series: MacroSeries[] }) {
  const q = useLinks();
  const m = useLinkMutations();
  const toast = useToast();
  const { data: session } = useSession();
  const [form, setForm] = useState({ symbol: "", series_symbol: "", relation: "cost", direction: "unclear", note: "" });
  const ro = Boolean(session?.read_only);
  const seriesName = (sym: string) => series.find((s) => s.symbol === sym)?.name ?? sym;
  return (
    <Panel title="Exposure map" titleId="ex-title" className="lg:col-span-5" meta="Your links only">
      <div className="space-y-3">
        {q.isLoading ? (
          <SkeletonRows rows={3} />
        ) : q.isError ? (
          <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
        ) : q.data?.links.length ? (
          <ul className="divide-y divide-line-subtle text-[13px]">
            {q.data.links.map((l) => (
              <li key={l.id} className="flex items-start gap-2 py-2">
                <div className="min-w-0 flex-1">
                  <p><Link to={`/instrument/${encodeURIComponent(l.symbol)}`} className="num hover:text-accent-text">{l.symbol}</Link> ↔ {seriesName(l.series_symbol)}</p>
                  <p className="text-xs text-fg-2">{l.relation} · {DIRECTION[l.direction]}{l.note ? ` — “${l.note}”` : ""}</p>
                  <p className="text-xs text-fg-3">
                    {l.correlation?.r != null ? `Correlation ${l.correlation.r} (${l.correlation.method}, n = ${l.correlation.n})` : `Correlation not shown: ${l.correlation?.why ?? "unavailable"}`}
                  </p>
                </div>
                <IconButton label={`Remove link ${l.symbol} to ${l.series_symbol}`} size="sm" disabled={ro}
                  onClick={() => m.remove.mutate(l.id, { onError: (e) => toast("error", errorMessage(e)) })}>
                  <Trash2 className="size-3.5" aria-hidden />
                </IconButton>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-fg-2">No links yet. Link a company to a series it depends on (an input cost, a currency, rates) with your reasoning.</p>
        )}
        {!ro && (
          <form className="grid grid-cols-2 gap-2" onSubmit={(e) => {
            e.preventDefault();
            m.add.mutate({ ...form, direction: form.direction as "unclear" }, {
              onSuccess: () => { setForm({ ...form, symbol: "", note: "" }); toast("success", "Link added."); },
            });
          }}>
            <Field label="Company" className="col-span-2">{({ id }) => <SymbolPicker id={id} value={form.symbol} onChange={(s) => setForm({ ...form, symbol: s })} />}</Field>
            <Field label="Series">
              {({ id }) => (
                <Select id={id} value={form.series_symbol} onChange={(e) => setForm({ ...form, series_symbol: e.target.value })}>
                  <option value="">Choose…</option>
                  {series.map((s) => <option key={s.symbol} value={s.symbol}>{s.name}</option>)}
                </Select>
              )}
            </Field>
            <Field label="Relation">
              {({ id }) => (
                <Select id={id} value={form.relation} onChange={(e) => setForm({ ...form, relation: e.target.value })}>
                  {RELATION.map((r) => <option key={r} value={r}>{r}</option>)}
                </Select>
              )}
            </Field>
            <Field label="A rise in the series…" className="col-span-2">
              {({ id }) => (
                <Select id={id} value={form.direction} onChange={(e) => setForm({ ...form, direction: e.target.value })}>
                  {Object.entries(DIRECTION).map(([k, v]) => <option key={k} value={k}>{v.replace("A rise ", "")}</option>)}
                </Select>
              )}
            </Field>
            <Field label="Why (your note)" className="col-span-2">{({ id }) => <Input id={id} maxLength={1000} value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />}</Field>
            {m.add.error && <InlineNotice tone="neg" className="col-span-2">{errorMessage(m.add.error)}</InlineNotice>}
            <Button type="submit" size="sm" variant="primary" className="col-span-2 justify-self-start" disabled={!form.symbol || !form.series_symbol} loading={m.add.isPending}>Add link</Button>
          </form>
        )}
        {q.data && <p className="text-xs leading-4 text-fg-3">{q.data.note}</p>}
      </div>
    </Panel>
  );
}
