import { ColorType, LineSeries, createChart } from "lightweight-charts";
import { Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { Pill } from "@/components/ui/Badges";
import { Button, IconButton } from "@/components/ui/Button";
import { Field, Input, Select } from "@/components/ui/Form";
import { Metric } from "@/components/ui/Metric";
import { Panel } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { EmptyState, ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { errorMessage } from "@/lib/api/client";
import { DASH, formatMoney, formatNumber, formatPercent, formatSessionDate, sourceName } from "@/lib/format";
import { cn } from "@/lib/cn";
import { useSession } from "@/features/settings/api";
import { SymbolPicker } from "@/features/search/SymbolPicker";
import { useLabMutations, usePaper, usePaperList, useReview, useRun, useRuns, type Run, type Summary } from "./api";

type Section = "test" | "runs" | "paper" | "review";
const RULE_LABEL = { buy_and_hold: "Buy and hold", sma_cross: "Moving-average cross", momentum: "Momentum" } as const;

function cssColor(value: string) {
  const name = value.match(/var\((--[^)]+)\)/)?.[1];
  return name ? getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#A7B3C4" : value;
}

const pct = (v: number | null | undefined) => (v === null || v === undefined ? DASH : formatPercent(v));

export function LabPage() {
  const [params, setParams] = useSearchParams();
  const section = (["test", "runs", "paper", "review"].includes(params.get("s") ?? "") ? params.get("s") : "test") as Section;
  const set = (s: Section) => setParams((p) => { const n = new URLSearchParams(p); if (s === "test") n.delete("s"); else n.set("s", s); return n; }, { replace: true });
  return (
    <div className="space-y-4 p-4 md:space-y-5 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Segmented<Section> label="Lab section" value={section} onChange={set}
          options={[{ value: "test", label: "Rule test" }, { value: "runs", label: "Run ledger" }, { value: "paper", label: "Paper portfolio" }, { value: "review", label: "Read me" }]} />
        <Pill tone="warn">Simulated · nothing here is a real trade</Pill>
      </div>
      {section === "test" ? <RuleTest onSaved={() => set("runs")} /> : section === "runs" ? <RunLedger /> : section === "paper" ? <PaperView /> : <Review />}
    </div>
  );
}

function RuleTest({ onSaved }: { onSaved: () => void }) {
  const m = useLabMutations();
  const toast = useToast();
  const { data: session } = useSession();
  const [f, setF] = useState({ symbol: "", rule: "sma_cross", fast: "20", slow: "50", lookback: "60", fee_pct: "0.1", slippage_bps: "5", starting_cash: "100000" });
  const run = m.run.data;
  const submit = () => {
    const params = f.rule === "sma_cross" ? { fast: Number(f.fast), slow: Number(f.slow) } : f.rule === "momentum" ? { lookback: Number(f.lookback) } : {};
    m.run.mutate({ symbol: f.symbol, rule: f.rule, params, fee_pct: f.fee_pct, slippage_bps: f.slippage_bps, starting_cash: f.starting_cash }, {
      onSuccess: () => toast("success", "Run recorded in the run ledger."),
    });
  };
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-12 lg:gap-5">
      <Panel title="Rule test" titleId="rt-title" className="lg:col-span-4 lg:self-start">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); submit(); }}>
          <Field label="Instrument" required>{({ id }) => <SymbolPicker id={id} value={f.symbol} onChange={(s) => setF({ ...f, symbol: s })} />}</Field>
          <Field label="Rule">
            {({ id }) => (
              <Select id={id} value={f.rule} onChange={(e) => setF({ ...f, rule: e.target.value })}>
                {Object.entries(RULE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </Select>
            )}
          </Field>
          {f.rule === "sma_cross" && (
            <div className="grid grid-cols-2 gap-2">
              <Field label="Fast average (sessions)">{({ id }) => <Input id={id} inputMode="numeric" className="num" value={f.fast} onChange={(e) => setF({ ...f, fast: e.target.value })} />}</Field>
              <Field label="Slow average (sessions)">{({ id }) => <Input id={id} inputMode="numeric" className="num" value={f.slow} onChange={(e) => setF({ ...f, slow: e.target.value })} />}</Field>
            </div>
          )}
          {f.rule === "momentum" && (
            <Field label="Look-back (sessions)" hint="Long while the close is above the close this many sessions ago">{({ id, describedBy }) => <Input id={id} aria-describedby={describedBy} inputMode="numeric" className="num" value={f.lookback} onChange={(e) => setF({ ...f, lookback: e.target.value })} />}</Field>
          )}
          <div className="grid grid-cols-2 gap-2">
            <Field label="Fee (% per trade)">{({ id }) => <Input id={id} inputMode="decimal" className="num" value={f.fee_pct} onChange={(e) => setF({ ...f, fee_pct: e.target.value })} />}</Field>
            <Field label="Slippage (bps)">{({ id }) => <Input id={id} inputMode="decimal" className="num" value={f.slippage_bps} onChange={(e) => setF({ ...f, slippage_bps: e.target.value })} />}</Field>
          </div>
          <Field label="Starting cash">{({ id }) => <Input id={id} inputMode="decimal" className="num" value={f.starting_cash} onChange={(e) => setF({ ...f, starting_cash: e.target.value })} />}</Field>
          {m.run.error && <InlineNotice tone="neg">{errorMessage(m.run.error)}</InlineNotice>}
          <Button type="submit" variant="primary" loading={m.run.isPending} disabled={!f.symbol || session?.read_only}>Run test</Button>
          <p className="text-xs leading-4 text-fg-3">Signals at a session's close trade at the next session's open. Long-only, whole shares, no leverage; five years of the provider's daily bars.</p>
        </form>
      </Panel>
      <Panel title="Result" titleId="rr-title" className="lg:col-span-8" meta={run ? `${run.symbol} · ${RULE_LABEL[run.rule]}` : undefined}
        actions={run ? <Button size="sm" variant="ghost" onClick={onSaved}>Open run ledger</Button> : undefined}>
        {m.run.isPending ? <SkeletonRows rows={6} /> : run ? <RunView run={run} /> : <p className="text-[13px] text-fg-2">Choose an instrument and a rule, then run the test.</p>}
      </Panel>
    </div>
  );
}

function SummaryRow({ label, s, ccy }: { label: string; s?: Summary; ccy: string | null }) {
  if (!s) return null;
  if (s.error) return <tr><th scope="row" className="py-1.5 text-left font-normal">{label}</th><td colSpan={5} className="py-1.5 text-xs text-fg-3">{s.error}</td></tr>;
  return (
    <tr className="border-b border-line-subtle/60">
      <th scope="row" className="py-1.5 pr-2 text-left font-normal">{label}</th>
      <td className="num whitespace-nowrap py-1.5 pl-2 text-right">{formatMoney(s.end_value, ccy ?? "INR", 0)}</td>
      <td className={cn("num whitespace-nowrap py-1.5 pl-2 text-right", s.total_return_pct >= 0 ? "text-pos" : "text-neg")}>{pct(s.total_return_pct)}</td>
      <td className="num hidden whitespace-nowrap py-1.5 pl-2 text-right sm:table-cell">{pct(s.cagr_pct)}</td>
      <td className="num whitespace-nowrap py-1.5 pl-2 text-right">{pct(s.max_drawdown_pct)}</td>
      <td className="num hidden whitespace-nowrap py-1.5 pl-2 text-right sm:table-cell">{s.trades ?? DASH}</td>
    </tr>
  );
}

function RunView({ run }: { run: Run }) {
  const r = run.results;
  const ccy = run.data.currency;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
        <Metric label="Rule return" value={pct(run.summary.strategy.total_return_pct)} caption={`${formatSessionDate(run.data.first)} – ${formatSessionDate(run.data.last)}`} />
        <Metric label="Buy and hold" value={pct(run.summary.buy_and_hold.total_return_pct)} caption="Same costs" />
        <Metric label="Time invested" value={run.summary.strategy.exposure_pct !== undefined ? formatPercent(run.summary.strategy.exposure_pct, { signed: false, digits: 0 }) : DASH} caption={`${run.summary.strategy.trades ?? 0} trades`} />
        <Metric label="Fees paid" value={run.summary.strategy.fees ? formatMoney(run.summary.strategy.fees, ccy ?? "INR", 0) : DASH} caption={`${run.costs.fee_pct}% + ${run.costs.slippage_bps} bps`} />
      </div>
      <table className="w-full text-[13px]">
        <caption className="sr-only">Results of the rule, buy and hold and the benchmark over the same dates</caption>
        <thead>
          <tr className="border-b border-line-subtle text-xs text-fg-3">
            <th scope="col" className="py-1.5 text-left font-medium" />
            <th scope="col" className="py-1.5 pl-2 text-right font-medium">End value</th>
            <th scope="col" className="py-1.5 pl-2 text-right font-medium">Return</th>
            <th scope="col" className="hidden py-1.5 pl-2 text-right font-medium sm:table-cell">A year</th>
            <th scope="col" className="py-1.5 pl-2 text-right font-medium">Max drawdown</th>
            <th scope="col" className="hidden py-1.5 pl-2 text-right font-medium sm:table-cell">Trades</th>
          </tr>
        </thead>
        <tbody>
          <SummaryRow label={RULE_LABEL[run.rule]} s={run.summary.strategy} ccy={ccy} />
          <SummaryRow label="Buy and hold" s={run.summary.buy_and_hold} ccy={ccy} />
          <SummaryRow label={`Benchmark ${run.summary.benchmark?.symbol ?? ""}`} s={run.summary.benchmark} ccy={ccy} />
        </tbody>
      </table>
      {r && <EquityChart run={run} />}
      {r && r.trades.length > 0 && (
        <details className="text-[13px]">
          <summary className="cursor-pointer text-xs text-fg-2">Last {r.trades.length} trades (signal day → execution)</summary>
          <div tabIndex={0} className="scroll-x scrollbar-thin mt-2 max-h-64 overflow-auto">
            <table className="w-full text-[12px]">
              <caption className="sr-only">Simulated trades</caption>
              <thead><tr className="text-fg-3"><th scope="col" className="text-left font-medium">Signal</th><th scope="col" className="text-left font-medium">Executed</th><th scope="col" className="text-left font-medium">Side</th><th scope="col" className="text-right font-medium">Shares</th><th scope="col" className="text-right font-medium">Price</th><th scope="col" className="text-right font-medium">Fee</th></tr></thead>
              <tbody>
                {r.trades.map((t, i) => (
                  <tr key={i}><td className="num">{t.signal_day}</td><td className="num">{t.day}</td><td>{t.side}</td><td className="num text-right">{formatNumber(t.qty, 0)}</td><td className="num text-right">{formatNumber(t.price, 2)}</td><td className="num text-right">{formatNumber(t.fee, 2)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
      <p className="text-xs leading-4 text-fg-3">
        Data: {sourceName(run.data.provider)}, {run.data.bars} completed daily sessions{run.data.unfinished_session_excluded ? ` (the unfinished ${run.data.unfinished_session_excluded} session is left out)` : ""}, {run.data.dividends} dividend(s) in the period, credited only while held · {run.data.adjustment} · fingerprint <span className="num">{run.data.hash.slice(0, 12)}</span>. {run.label}
      </p>
    </div>
  );
}

function EquityChart({ run }: { run: Run }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || !run.results) return;
    const chart = createChart(ref.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: cssColor("var(--chart-text)"), fontFamily: "JetBrains Mono, ui-monospace, monospace", fontSize: 11, attributionLogo: true },
      grid: { vertLines: { color: cssColor("var(--chart-grid)") }, horzLines: { color: cssColor("var(--chart-grid)") } },
      rightPriceScale: { borderColor: cssColor("var(--border)") },
      timeScale: { borderColor: cssColor("var(--border)") },
    });
    const a = chart.addSeries(LineSeries, { color: cssColor("var(--chart-line)"), lineWidth: 2, priceLineVisible: false, title: "Rule", priceFormat: { type: "price", precision: 0, minMove: 1 } });
    a.setData(run.results.equity.map(([d, v]) => ({ time: d, value: Number(v) })));
    const b = chart.addSeries(LineSeries, { color: cssColor("var(--info)"), lineWidth: 1, priceLineVisible: false, title: "Hold", priceFormat: { type: "price", precision: 0, minMove: 1 } });
    b.setData(run.results.hold_equity.map(([d, v]) => ({ time: d, value: Number(v) })));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [run]);
  return (
    <figure className="m-0" aria-label={`Simulated account value of the rule and of buy and hold for ${run.symbol}`}>
      <figcaption className="text-xs text-fg-3">Simulated account value · rule vs buy and hold <span className="sr-only">(the results table lists the end values)</span></figcaption>
      <div ref={ref} className="h-[240px] w-full" />
    </figure>
  );
}

function RunLedger() {
  const runs = useRuns();
  const [open, setOpen] = useState<number | null>(null);
  const one = useRun(open);
  const m = useLabMutations();
  const toast = useToast();
  const { data: session } = useSession();
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-12 lg:gap-5">
      <Panel title="Run ledger" titleId="rl-title" className="lg:col-span-5 lg:self-start">
        {runs.isLoading ? <SkeletonRows rows={4} /> : runs.isError ? <ErrorState message={errorMessage(runs.error)} onRetry={() => runs.refetch()} /> : !runs.data?.length ? (
          <EmptyState title="No runs yet">Every rule test is recorded here with its parameters, costs and a fingerprint of the data it used.</EmptyState>
        ) : (
          <ul className="divide-y divide-line-subtle text-[13px]">
            {runs.data.map((r) => (
              <li key={r.id} className={cn("flex items-center gap-2 py-2", open === r.id && "text-accent-text")}>
                <button type="button" className="min-w-0 flex-1 text-left" onClick={() => setOpen(r.id)}>
                  <span className="num">#{r.id} {r.symbol}</span> · {RULE_LABEL[r.rule]} {Object.values(r.params).join("/")}
                  <span className="block text-xs text-fg-3">{formatSessionDate(r.created_at.slice(0, 10))} · {pct(r.summary.strategy.total_return_pct)} vs hold {pct(r.summary.buy_and_hold.total_return_pct)}</span>
                </button>
                <Button size="sm" variant="ghost" loading={m.reproduce.isPending && m.reproduce.variables === r.id}
                  onClick={() => m.reproduce.mutate(r.id, { onSuccess: (x) => toast(x.same_data && x.same_results ? "success" : "error", x.explanation), onError: (e) => toast("error", errorMessage(e)) })}>Reproduce</Button>
                <IconButton label={`Delete run ${r.id}`} size="sm" disabled={session?.read_only} onClick={() => m.removeRun.mutate(r.id)}><Trash2 className="size-3.5" aria-hidden /></IconButton>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <Panel title="Run detail" titleId="rd-title" className="lg:col-span-7">
        {open === null ? <p className="text-[13px] text-fg-2">Choose a run to see its results, data and trades.</p> : one.isLoading ? <SkeletonRows rows={5} /> : one.data ? (
          <div className="space-y-3">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
              <dt className="text-fg-3">Parameters</dt><dd className="num">{JSON.stringify(one.data.params)}</dd>
              <dt className="text-fg-3">Costs</dt><dd className="num">{one.data.costs.fee_pct}% fee · {one.data.costs.slippage_bps} bps · cash {one.data.costs.starting_cash}</dd>
              <dt className="text-fg-3">Data</dt><dd className="num">{one.data.data.first} → {one.data.data.last} · {one.data.data.bars} bars</dd>
              <dt className="text-fg-3">Fingerprint</dt><dd className="num break-all">{one.data.data.hash}</dd>
            </dl>
            <RunView run={one.data} />
          </div>
        ) : null}
      </Panel>
    </div>
  );
}

function PaperView() {
  const list = usePaperList();
  const [pid, setPid] = useState<number | null>(null);
  const current = pid ?? list.data?.[0]?.id ?? null;
  const p = usePaper(current);
  const m = useLabMutations();
  const toast = useToast();
  const { data: session } = useSession();
  const ro = Boolean(session?.read_only);
  const [name, setName] = useState("");
  const [o, setO] = useState({ side: "BUY", symbol: "", quantity: "" });
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-12 lg:gap-5">
      <Panel title="Paper portfolios" titleId="pp-title" className="lg:col-span-4 lg:self-start">
        <div className="space-y-3">
          {list.data?.length ? (
            <Select aria-label="Paper portfolio" value={current ?? ""} onChange={(e) => setPid(Number(e.target.value))}>
              {list.data.map((x) => <option key={x.id} value={x.id}>{x.name} ({x.currency})</option>)}
            </Select>
          ) : <p className="text-[13px] text-fg-2">No paper portfolio yet.</p>}
          <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); m.createPaper.mutate({ name, starting_cash: "100000" }, { onSuccess: (x) => { setPid(x.id); setName(""); }, onError: (err) => toast("error", errorMessage(err)) }); }}>
            <Field label="New paper portfolio (₹1,00,000)" className="min-w-0 flex-1">{({ id }) => <Input id={id} maxLength={60} value={name} onChange={(e) => setName(e.target.value)} />}</Field>
            <Button type="submit" disabled={!name.trim() || ro} loading={m.createPaper.isPending}>Create</Button>
          </form>
          {p.data && (
            <form className="space-y-2 border-t border-line-subtle pt-3" onSubmit={(e) => { e.preventDefault(); m.order.mutate({ id: p.data!.id, ...o }, { onSuccess: () => { toast("success", "Simulated order placed; it fills at the next session's open."); setO({ ...o, quantity: "" }); }, onError: (err) => toast("error", errorMessage(err)) }); }}>
              <Field label="Instrument">{({ id }) => <SymbolPicker id={id} value={o.symbol} onChange={(s) => setO({ ...o, symbol: s })} />}</Field>
              <div className="flex items-end gap-2">
                <Segmented label="Side" value={o.side} onChange={(s) => setO({ ...o, side: s })} options={[{ value: "BUY", label: "Buy" }, { value: "SELL", label: "Sell" }]} />
                <Field label="Shares" className="w-28">{({ id }) => <Input id={id} inputMode="numeric" className="num" value={o.quantity} onChange={(e) => setO({ ...o, quantity: e.target.value })} />}</Field>
                <Button type="submit" variant="primary" disabled={!o.symbol || !/^\d+$/.test(o.quantity) || ro} loading={m.order.isPending}>Place</Button>
              </div>
            </form>
          )}
        </div>
      </Panel>
      <Panel title="Simulated holdings" titleId="ph-title" className="lg:col-span-8" meta={p.data ? `${p.data.name} · ${p.data.currency}` : undefined}>
        {current === null ? <EmptyState title="Create a paper portfolio to start">It is separate from your real ledger.</EmptyState> : p.isLoading ? <SkeletonRows rows={4} /> : p.isError ? <ErrorState message={errorMessage(p.error)} onRetry={() => p.refetch()} /> : p.data ? (
          <div className="space-y-3 text-[13px]">
            <div className="grid grid-cols-3 gap-4">
              <Metric label="Simulated value" value={formatMoney(p.data.value, p.data.currency, 0)} caption={`Started with ${formatMoney(p.data.starting_cash, p.data.currency, 0)}`} />
              <Metric label="Return" value={formatPercent(p.data.return_pct)} caption="Price only" />
              <Metric label="Cash" value={formatMoney(p.data.cash, p.data.currency, 0)} />
            </div>
            {p.data.positions.length > 0 && (
              <table className="w-full">
                <caption className="sr-only">Simulated positions</caption>
                <thead><tr className="border-b border-line-subtle text-xs text-fg-3"><th scope="col" className="py-1 text-left font-medium">Instrument</th><th scope="col" className="py-1 text-right font-medium">Shares</th><th scope="col" className="py-1 text-right font-medium">Last close</th><th scope="col" className="py-1 text-right font-medium">Value</th></tr></thead>
                <tbody>{p.data.positions.map((x) => <tr key={x.symbol} className="border-b border-line-subtle/60"><td className="num py-1">{x.symbol}</td><td className="num py-1 text-right">{formatNumber(x.quantity, 0)}</td><td className="num py-1 text-right" title={`as of ${x.as_of}`}>{formatNumber(x.last_close, 2)}</td><td className="num py-1 text-right">{formatMoney(x.market_value, p.data!.currency, 0)}</td></tr>)}</tbody>
              </table>
            )}
            <h3 className="text-xs font-medium text-fg-2">Orders</h3>
            {p.data.orders.length === 0 ? <p className="text-fg-3">No orders yet.</p> : (
              <ul className="divide-y divide-line-subtle">
                {p.data.orders.map((x) => (
                  <li key={x.id} className="flex items-center gap-2 py-1.5">
                    <span className="min-w-0 flex-1"><span className="num">{x.side} {formatNumber(x.quantity, 0)} {x.symbol}</span> <span className="text-xs text-fg-3">after {x.placed_session}</span>
                      <span className="block text-xs text-fg-2">{x.status === "filled" ? `Filled ${x.fill_day} at ${formatNumber(x.fill_price, 2)} (fee ${formatNumber(x.fee, 2)})` : x.reason}</span></span>
                    <Pill tone={x.status === "filled" ? "pos" : x.status === "rejected" ? "neg" : "info"}>{x.status}</Pill>
                    {x.status === "pending" && <Button size="sm" variant="ghost" disabled={ro} onClick={() => m.cancel.mutate({ id: p.data!.id, oid: x.id })}>Cancel</Button>}
                  </li>
                ))}
              </ul>
            )}
            <p className="text-xs leading-4 text-fg-3">{p.data.method} {p.data.label}</p>
          </div>
        ) : null}
      </Panel>
    </div>
  );
}

function Review() {
  const q = useReview();
  return (
    <Panel title="Read me before trusting a test" titleId="rv-title">
      <ul className="grid gap-4 text-[13px] md:grid-cols-2">
        {(q.data?.items ?? []).map((i) => (
          <li key={i.title}><h3 className="font-medium">{i.title}</h3><p className="mt-1 leading-5 text-fg-2">{i.text}</p></li>
        ))}
      </ul>
    </Panel>
  );
}
