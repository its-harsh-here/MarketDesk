import { Sparkles, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useDialogs } from "@/app/dialogs";
import { Button, IconButton } from "@/components/ui/Button";
import { Field, Input, Select, Textarea } from "@/components/ui/Form";
import { Metric } from "@/components/ui/Metric";
import { Panel } from "@/components/ui/Panel";
import { EmptyState, ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { ApiError, errorMessage } from "@/lib/api/client";
import { DASH, formatLargeMoney, formatMoney, formatNumber, formatPercent, formatVolume } from "@/lib/format";
import { cn } from "@/lib/cn";
import { useSession } from "@/features/settings/api";
import {
  FIELDS,
  useDcf,
  useMultiples,
  useScenarioMutations,
  useScenarios,
  useValuationInputs,
  type Axis,
  type DcfResult,
  type DcfValues,
  type Field as F,
  type Multiples,
  type Scenario,
  type ValuationInputs,
} from "./api";

const AXIS_LABEL: Record<Axis, string> = { discount_pct: "Discount rate", terminal_growth_pct: "Terminal growth", growth_pct: "Forecast growth" };
const UNIT: Record<F, string> = { fcf0: "amount", years: "years", growth_pct: "% a year", terminal_growth_pct: "% a year", discount_pct: "%", shares: "shares" };

/** "= ₹1,888.60 Cr · " for large raw numbers, so the typed figure is easy to check. */
function readable(f: F, raw: string, ccy: string): string {
  const n = Number(raw.replace(/,/g, ""));
  if (!Number.isFinite(n) || raw.trim() === "") return "";
  if (f === "fcf0" && Math.abs(n) >= 1e5) return `= ${formatLargeMoney(n, ccy)} · `;
  if (f === "shares" && n >= 1e5) return `= ${formatVolume(n)} shares · `;
  return "";
}

function money(v: string | null | undefined, ccy: string) {
  if (v === null || v === undefined) return DASH;
  return Math.abs(Number(v)) >= (ccy === "INR" ? 1e7 : 1e6) ? formatLargeMoney(v, ccy) : formatMoney(v, ccy);
}

export function ValuationTab({ symbol }: { symbol: string }) {
  const q = useValuationInputs(symbol);
  const v = q.data;
  return (
    <>
      <InlineNotice tone="info" className="lg:col-span-12">
        {v?.hypothetical ?? "Hypothetical: these values follow from the assumptions you enter. They are not fair values, forecasts or recommendations."}
      </InlineNotice>
      {q.isLoading ? (
        <Panel className="lg:col-span-12"><SkeletonRows rows={6} /></Panel>
      ) : q.isError ? (
        <ErrorState className="lg:col-span-12" message={errorMessage(q.error)} onRetry={() => q.refetch()} />
      ) : v ? (
        v.dcf_applicable ? <DcfPanel v={v} /> : (
          <Panel title="Discounted cash flow" titleId="dcf-title" className="lg:col-span-12">
            <EmptyState title="Not applied to this company">{v.dcf_reason}</EmptyState>
          </Panel>
        )
      ) : null}
      <MultiplesPanel symbol={symbol} />
    </>
  );
}

function DcfPanel({ v }: { v: ValuationInputs }) {
  const dcf = useDcf();
  const scenarios = useScenarios(v.symbol);
  const sm = useScenarioMutations(v.symbol);
  const { open } = useDialogs();
  const toast = useToast();
  const { data: session } = useSession();
  const initial = useMemo(() => Object.fromEntries(FIELDS.map((f) => [f, v.defaults[f].value ?? ""])) as DcfValues, [v]);
  const [values, setValues] = useState<DcfValues>(initial);
  const [axes, setAxes] = useState<{ rows: Axis; cols: Axis }>({ rows: "discount_pct", cols: "terminal_growth_pct" });
  const [loaded, setLoaded] = useState<Scenario | null>(null);
  const [saveAs, setSaveAs] = useState<{ name: string; case: Scenario["case"]; notes: string } | null>(null);
  const ro = Boolean(session?.read_only);
  const err = dcf.error instanceof ApiError ? dcf.error : null;
  const errField = (err?.details as { field?: string } | undefined)?.field;

  const run = (vals = values, ax = axes) => dcf.mutate({ symbol: v.symbol, inputs: vals, rows_axis: ax.rows, cols_axis: ax.cols });
  useEffect(() => {
    setValues(initial);
    if (FIELDS.every((f) => initial[f] !== "") && Number(initial.fcf0) > 0) run(initial);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial]);

  const load = (s: Scenario) => {
    const vals = Object.fromEntries(FIELDS.map((f) => [f, String(s.inputs[f])])) as DcfValues;
    setValues(vals);
    setLoaded(s);
    run(vals);
  };
  const r = dcf.data;
  const question = (s: { name: string } | null) =>
    `Under the "${s?.name ?? "current"}" scenario I assume free cash flow of ${values.fcf0} ${v.currency} growing ${values.growth_pct}% a year for ${values.years} years, then ${values.terminal_growth_pct}%, discounted at ${values.discount_pct}%. What in the reported results supports or contradicts these assumptions?`.slice(0, 500);

  return (
    <>
      <Panel title="Discounted cash flow" titleId="dcf-title" className="lg:col-span-5 lg:self-start" meta={`${v.currency} · price ${v.price ? formatMoney(v.price, v.currency) : DASH}`}>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); run(); }}>
          <p className="text-xs leading-4 text-fg-3">{v.cash_flow_definition}</p>
          {FIELDS.map((f) => (
            <Field key={f} label={`${v.labels[f]} (${f === "fcf0" ? v.currency : UNIT[f]})`}
              hint={`${readable(f, values[f], v.currency)}${v.defaults[f].warning ?? v.defaults[f].source}`}
              error={errField === f ? err?.message : undefined}>
              {({ id, describedBy, invalid }) => (
                <Input id={id} aria-describedby={describedBy} aria-invalid={invalid} inputMode="decimal" className="num"
                  value={values[f]} onChange={(e) => setValues({ ...values, [f]: e.target.value })} />
              )}
            </Field>
          ))}
          {err && !errField && <InlineNotice tone="neg">{err.message}</InlineNotice>}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="primary" loading={dcf.isPending}>Calculate</Button>
            <Button variant="ghost" onClick={() => { setValues(initial); setLoaded(null); run(initial); }}>Reset to defaults</Button>
          </div>
          {v.notes.map((n) => <p key={n} className="text-xs leading-4 text-fg-3">{n}</p>)}
        </form>
        <div className="mt-4 space-y-2 border-t border-line-subtle pt-3">
          <h3 className="text-xs font-medium text-fg-2">Saved scenarios</h3>
          {scenarios.data?.length ? (
            <ul className="space-y-1.5">
              {scenarios.data.map((s) => (
                <li key={s.id} className={cn("flex items-center gap-2 rounded-[var(--radius-control)] border px-2 py-1.5", loaded?.id === s.id ? "border-accent" : "border-line-subtle")}>
                  <button type="button" className="min-w-0 flex-1 text-left" onClick={() => load(s)} title={s.notes || undefined}>
                    <span className="text-[13px] font-medium">{s.name}</span>
                    <span className="ml-2 text-xs text-fg-3">{s.case} · {String(s.inputs.growth_pct)}% → {String(s.inputs.terminal_growth_pct)}% at {String(s.inputs.discount_pct)}%</span>
                  </button>
                  <IconButton label={`Ask AI about scenario ${s.name}`} size="sm" onClick={() => open({ kind: "ai", symbol: v.symbol, question: question(s) })}>
                    <Sparkles className="size-3.5" aria-hidden />
                  </IconButton>
                  <IconButton label={`Delete scenario ${s.name}`} size="sm" disabled={ro} onClick={() => sm.remove.mutate(s.id, {
                    onSuccess: () => { toast("success", `Deleted “${s.name}”.`); if (loaded?.id === s.id) setLoaded(null); },
                    onError: (e) => toast("error", errorMessage(e)),
                  })}>
                    <Trash2 className="size-3.5" aria-hidden />
                  </IconButton>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-fg-3">None yet. Save bear, base and bull cases to compare them later.</p>
          )}
          {saveAs ? (
            <form className="space-y-2" onSubmit={(e) => {
              e.preventDefault();
              sm.create.mutate({ name: saveAs.name, case: saveAs.case, notes: saveAs.notes, inputs: values }, {
                onSuccess: (s) => { setSaveAs(null); setLoaded(s); toast("success", `Saved “${s.name}”.`); },
              });
            }}>
              <div className="flex gap-2">
                <Field label="Name" className="min-w-0 flex-1">{({ id }) => <Input id={id} maxLength={40} value={saveAs.name} onChange={(e) => setSaveAs({ ...saveAs, name: e.target.value })} autoFocus />}</Field>
                <Field label="Case" className="w-28">
                  {({ id }) => (
                    <Select id={id} value={saveAs.case} onChange={(e) => setSaveAs({ ...saveAs, case: e.target.value as Scenario["case"] })}>
                      {["bear", "base", "bull", "custom"].map((c) => <option key={c} value={c}>{c}</option>)}
                    </Select>
                  )}
                </Field>
              </div>
              <Field label="Why these assumptions (optional)">{({ id }) => <Textarea id={id} rows={2} maxLength={4000} value={saveAs.notes} onChange={(e) => setSaveAs({ ...saveAs, notes: e.target.value })} />}</Field>
              {sm.create.error && <InlineNotice tone="neg">{errorMessage(sm.create.error)}</InlineNotice>}
              <div className="flex gap-2">
                <Button type="submit" size="sm" variant="primary" disabled={!saveAs.name.trim()} loading={sm.create.isPending}>Save scenario</Button>
                <Button size="sm" variant="ghost" onClick={() => setSaveAs(null)}>Cancel</Button>
              </div>
            </form>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" disabled={ro} onClick={() => setSaveAs({ name: "", case: "base", notes: "" })}>Save as scenario</Button>
              {loaded && (
                <Button size="sm" variant="ghost" disabled={ro} loading={sm.update.isPending} onClick={() => sm.update.mutate({ id: loaded.id, name: loaded.name, case: loaded.case, notes: loaded.notes, inputs: values }, {
                  onSuccess: () => toast("success", `Updated “${loaded.name}”.`),
                  onError: (e) => toast("error", errorMessage(e)),
                })}>Update “{loaded.name}”</Button>
              )}
              <Button size="sm" variant="ghost" icon={<Sparkles className="size-3.5" aria-hidden />} onClick={() => open({ kind: "ai", symbol: v.symbol, question: question(loaded) })}>
                Ask AI about these assumptions
              </Button>
            </div>
          )}
        </div>
      </Panel>
      <Panel title="Result" titleId="dcf-res-title" className="lg:col-span-7" refreshing={dcf.isPending && Boolean(r)} meta="Hypothetical value per share from the assumptions">
        {!r ? (
          dcf.isPending ? <SkeletonRows rows={6} /> : <p className="text-[13px] text-fg-2">Enter positive free cash flow and shares, then Calculate.</p>
        ) : (
          <DcfResultView r={r} currency={v.currency} axes={axes} onAxes={(ax) => { setAxes(ax); run(values, ax); }} />
        )}
      </Panel>
    </>
  );
}

function DcfResultView({ r, currency, axes, onAxes }: { r: DcfResult; currency: string; axes: { rows: Axis; cols: Axis }; onAxes: (a: { rows: Axis; cols: Axis }) => void }) {
  const res = r.result;
  const price = r.price ? Number(r.price) : null;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
        <Metric size="lg" label="Value per share" value={formatMoney(res.per_share, currency)} caption="Hypothetical" />
        <Metric label="vs last price" value={res.vs_price_pct ? formatPercent(res.vs_price_pct) : DASH} caption={r.price ? `Price ${formatMoney(r.price, currency)}` : "No price"} />
        <Metric label="Equity value" value={money(res.equity_value, currency)} caption={`PV forecast ${money(res.pv_forecast, currency)}`} />
        <Metric label="From terminal value" value={formatPercent(res.terminal_share_pct, { signed: false, digits: 1 })} caption={`PV ${money(res.pv_terminal, currency)}`} title="Share of the equity value that comes after the explicit forecast" />
      </div>
      <table className="w-full text-[13px]">
        <caption className="sr-only">Forecast free cash flow, discount factor and present value by year</caption>
        <thead>
          <tr className="border-b border-line-subtle text-xs text-fg-3">
            <th scope="col" className="py-1.5 text-left font-medium">Year</th>
            <th scope="col" className="py-1.5 text-right font-medium">Free cash flow</th>
            <th scope="col" className="py-1.5 text-right font-medium">Discount factor</th>
            <th scope="col" className="py-1.5 text-right font-medium">Present value</th>
          </tr>
        </thead>
        <tbody>
          {res.rows.map((y) => (
            <tr key={y.year} className="border-b border-line-subtle/60">
              <td className="num py-1">{y.year}</td>
              <td className="num py-1 text-right">{money(y.fcf, currency)}</td>
              <td className="num py-1 text-right">{formatNumber(y.discount_factor, 4)}</td>
              <td className="num py-1 text-right">{money(y.pv, currency)}</td>
            </tr>
          ))}
          <tr>
            <td className="py-1 text-fg-2">Terminal</td>
            <td className="num py-1 text-right">{money(res.terminal_value, currency)}</td>
            <td />
            <td className="num py-1 text-right">{money(res.pv_terminal, currency)}</td>
          </tr>
        </tbody>
      </table>
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2 text-xs text-fg-3">
          <span>Sensitivity of value per share:</span>
          <Select aria-label="Rows" className="h-8 w-40" value={axes.rows} onChange={(e) => onAxes({ ...axes, rows: e.target.value as Axis })}>
            {Object.entries(AXIS_LABEL).map(([k, l]) => <option key={k} value={k} disabled={k === axes.cols}>{l}</option>)}
          </Select>
          <span>×</span>
          <Select aria-label="Columns" className="h-8 w-40" value={axes.cols} onChange={(e) => onAxes({ ...axes, cols: e.target.value as Axis })}>
            {Object.entries(AXIS_LABEL).map(([k, l]) => <option key={k} value={k} disabled={k === axes.rows}>{l}</option>)}
          </Select>
        </div>
        <div className="scrollbar-thin relative overflow-x-auto">
          <table className="text-[12px]">
            <caption className="sr-only">Value per share by {AXIS_LABEL[r.sensitivity.rows_axis]} (rows) and {AXIS_LABEL[r.sensitivity.cols_axis]} (columns); the centre is your inputs</caption>
            <thead>
              <tr>
                <th scope="col" className="px-2 py-1 text-left font-medium text-fg-3">{AXIS_LABEL[r.sensitivity.rows_axis]} ↓ / {AXIS_LABEL[r.sensitivity.cols_axis]} →</th>
                {r.sensitivity.cols.map((c) => <th key={c} scope="col" className="num px-2 py-1 text-right font-medium text-fg-3">{formatNumber(c, 1)}%</th>)}
              </tr>
            </thead>
            <tbody>
              {r.sensitivity.grid.map((row, i) => (
                <tr key={r.sensitivity.rows[i]}>
                  <th scope="row" className="num px-2 py-1 text-left font-medium text-fg-3">{formatNumber(r.sensitivity.rows[i], 1)}%</th>
                  {row.map((cell, j) => {
                    const centre = i === 2 && j === 2;
                    const n = cell.value === null ? null : Number(cell.value);
                    const tint = n === null || price === null ? undefined : n >= price ? "var(--positive)" : "var(--negative)";
                    return (
                      <td key={j} title={cell.why ?? undefined} className={cn("num min-w-20 px-2 py-1 text-right", centre && "outline outline-2 -outline-offset-2 outline-accent", n === null && "text-fg-3")}
                        style={tint ? { background: `color-mix(in oklab, ${tint} 14%, var(--panel))` } : undefined}>
                        {n === null ? "n/a" : formatMoney(n, currency, 0)}
                        {cell.why && <span className="sr-only">: {cell.why}</span>}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-fg-3">Shaded green at or above the last price, red below; the outlined cell is your inputs; n/a where the terminal growth is not at least 0.5 points below the discount rate.</p>
      </div>
      <details className="text-xs text-fg-3">
        <summary className="cursor-pointer text-fg-2 hover:text-fg">Formulas</summary>
        <pre className="mt-2 whitespace-pre-wrap font-sans leading-5">{r.formula}</pre>
      </details>
    </div>
  );
}

function MultiplesPanel({ symbol }: { symbol: string }) {
  const q = useMultiples(symbol);
  const m = q.data;
  return (
    <Panel title="Peer multiples" titleId="mult-title" className="lg:col-span-12" refreshing={q.isFetching && !q.isLoading} meta={m ? `${m.peer_source} · ${m.peers.length} peer(s)` : undefined}>
      {q.isLoading ? (
        <SkeletonRows rows={4} />
      ) : q.isError ? (
        <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
      ) : !m ? null : m.peers.length === 0 ? (
        <EmptyState title="No peers yet">Choose peers on the Peers tab (or load watchlist data on the Screener) to see multiple-based ranges.</EmptyState>
      ) : (
        <div className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-2">
            {(["pe_ratio", "price_to_book"] as const).map((k) => <RangeBar key={k} m={m} k={k} />)}
          </div>
          <table className="w-full text-[13px]">
            <caption className="sr-only">Peer multiples used</caption>
            <thead>
              <tr className="border-b border-line-subtle text-xs text-fg-3">
                <th scope="col" className="py-1.5 text-left font-medium">Peer</th>
                <th scope="col" className="py-1.5 text-right font-medium">P/E</th>
                <th scope="col" className="py-1.5 text-right font-medium">P/B</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-line-subtle/60 text-fg-2">
                <td className="num py-1">{m.symbol} (this company)</td>
                <td className="num py-1 text-right">{m.own.pe_ratio ? `${formatNumber(m.own.pe_ratio, 2)}×` : DASH}</td>
                <td className="num py-1 text-right">{m.own.price_to_book ? `${formatNumber(m.own.price_to_book, 2)}×` : DASH}</td>
              </tr>
              {m.peers.map((p) => (
                <tr key={p.symbol} className="border-b border-line-subtle/60">
                  <td className="num py-1">{p.symbol} <span className="text-xs text-fg-3 max-sm:hidden">{p.name}</span></td>
                  <td className="num py-1 text-right">{p.pe_ratio ? `${formatNumber(p.pe_ratio, 2)}×` : DASH}</td>
                  <td className="num py-1 text-right">{p.price_to_book ? `${formatNumber(p.price_to_book, 2)}×` : DASH}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs leading-4 text-fg-3">{m.method} {m.hypothetical}</p>
        </div>
      )}
    </Panel>
  );
}

function RangeBar({ m, k }: { m: Multiples; k: "pe_ratio" | "price_to_book" }) {
  const r = m.ranges[k];
  const title = k === "pe_ratio" ? "Implied by peer P/E" : "Implied by peer P/B";
  if (!r.available || !r.implied) {
    return (
      <div>
        <h3 className="text-xs font-medium text-fg-2">{title}</h3>
        <p className="mt-1 text-[13px] text-fg-3">{r.why}</p>
      </div>
    );
  }
  const ccy = m.currency ?? "INR";
  const price = m.price ? Number(m.price) : null;
  const lo = Math.min(Number(r.implied.min), price ?? Infinity);
  const hi = Math.max(Number(r.implied.max), price ?? -Infinity);
  const pos = (x: number) => `${((x - lo) / (hi - lo || 1)) * 100}%`;
  return (
    <div>
      <h3 className="text-xs font-medium text-fg-2">{title} <span className="font-normal text-fg-3">· {r.n} peers · {r.label}</span></h3>
      <div className="relative mt-3 h-6" aria-hidden>
        <div className="absolute top-2.5 h-1 rounded bg-line" style={{ left: pos(Number(r.implied.min)), right: `calc(100% - ${pos(Number(r.implied.max))})` }} />
        <div className="absolute top-1 h-4 rounded bg-info/40" style={{ left: pos(Number(r.implied.p25)), right: `calc(100% - ${pos(Number(r.implied.p75))})` }} />
        <div className="absolute top-0 h-6 w-0.5 bg-info" style={{ left: pos(Number(r.implied.median)) }} />
        {price !== null && <div className="absolute -top-1 h-8 w-0.5 bg-accent" style={{ left: pos(price) }} />}
      </div>
      <p className="num mt-1 text-xs text-fg-2">
        {formatMoney(r.implied.min, ccy, 0)} – {formatMoney(r.implied.max, ccy, 0)} · quartiles {formatMoney(r.implied.p25, ccy, 0)}–{formatMoney(r.implied.p75, ccy, 0)} · median {formatMoney(r.implied.median, ccy, 0)}
        {price !== null ? <> · <span className="text-accent-text">price {formatMoney(price, ccy)}</span></> : null}
      </p>
    </div>
  );
}
