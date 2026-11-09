import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { PnlText } from "@/components/ui/Change";
import { Field, Input } from "@/components/ui/Form";
import { Panel } from "@/components/ui/Panel";
import { EmptyState, InlineNotice } from "@/components/ui/States";
import { errorMessage } from "@/lib/api/client";
import { formatMoney, formatPercent } from "@/lib/format";
import { useStress } from "@/features/valuation/api";
import type { PerfAccount } from "./riskApi";

const PRESETS: { label: string; shocks: { IN: string; US: string; USD: string } }[] = [
  { label: "India −10%", shocks: { IN: "-10", US: "0", USD: "0" } },
  { label: "US −15%, rupee weaker (USD/INR +5%)", shocks: { IN: "0", US: "-15", USD: "5" } },
  { label: "Broad sell-off −30%", shocks: { IN: "-30", US: "-30", USD: "0" } },
  { label: "Rupee stronger (USD/INR −8%)", shocks: { IN: "0", US: "0", USD: "-8" } },
];
const NUM = /^-?\d+(\.\d+)?$/;

/** What-if: instant price and exchange-rate shocks applied to today's holdings. Not a forecast. */
export function StressPanel({ account }: { account: PerfAccount }) {
  const [shocks, setShocks] = useState({ IN: "-10", US: "-10", USD: "0" });
  const m = useStress();
  const r = m.data;
  const valid = Object.values(shocks).every((v) => NUM.test(v));
  const run = (s = shocks) =>
    m.mutate({ account, market_shocks: { IN: s.IN, US: s.US }, fx_shocks: account === "INR" ? {} : { USD: s.USD } });
  return (
    <Panel title="Stress test" titleId="stress-title" className="lg:col-span-12" meta="Hypothetical shocks to today's holdings">
      <div className="space-y-3">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Preset scenarios">
          {PRESETS.map((p) => (
            <Button key={p.label} size="sm" variant="secondary" onClick={() => { setShocks(p.shocks); run(p.shocks); }}>{p.label}</Button>
          ))}
        </div>
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); run(); }}>
          <Field label="Indian stocks (%)" className="w-36">{({ id }) => <Input id={id} inputMode="decimal" className="num" value={shocks.IN} aria-invalid={!NUM.test(shocks.IN)} onChange={(e) => setShocks({ ...shocks, IN: e.target.value })} />}</Field>
          <Field label="US stocks (%)" className="w-36">{({ id }) => <Input id={id} inputMode="decimal" className="num" value={shocks.US} aria-invalid={!NUM.test(shocks.US)} onChange={(e) => setShocks({ ...shocks, US: e.target.value })} />}</Field>
          {account !== "INR" && (
            <Field label="USD/INR (%)" className="w-36" hint="+ = rupee weaker">{({ id, describedBy }) => <Input id={id} aria-describedby={describedBy} inputMode="decimal" className="num" value={shocks.USD} aria-invalid={!NUM.test(shocks.USD)} onChange={(e) => setShocks({ ...shocks, USD: e.target.value })} />}</Field>
          )}
          <Button type="submit" loading={m.isPending} disabled={!valid}>Apply</Button>
        </form>
        {m.isError && <InlineNotice tone="neg">{errorMessage(m.error)}</InlineNotice>}
        {r && !r.available ? (
          <EmptyState title="Nothing to stress yet">{r.reason}</EmptyState>
        ) : r ? (
          <>
            <p className="text-[13px]">
              Value {formatMoney(r.before, r.base)} → {formatMoney(r.after, r.base)}: <PnlText value={r.change} currency={r.base} />{" "}
              <span className="num text-fg-2">({formatPercent(r.change_pct)})</span>
            </p>
            <div tabIndex={0} className="scroll-x scrollbar-thin relative overflow-x-auto">
              <table className="w-full min-w-[520px] text-[13px]">
                <caption className="sr-only">Effect of the shocks on each holding, in {r.base}</caption>
                <thead>
                  <tr className="border-b border-line-subtle text-xs text-fg-3">
                    <th scope="col" className="py-1.5 text-left font-medium">Holding</th>
                    <th scope="col" className="py-1.5 text-right font-medium">Price shock</th>
                    <th scope="col" className="py-1.5 text-right font-medium">FX shock</th>
                    <th scope="col" className="py-1.5 text-right font-medium">Before</th>
                    <th scope="col" className="py-1.5 text-right font-medium">After</th>
                    <th scope="col" className="py-1.5 text-right font-medium">Change</th>
                  </tr>
                </thead>
                <tbody>
                  {r.rows.map((x) => (
                    <tr key={x.symbol} className="border-b border-line-subtle/60">
                      <td className="num py-1">{x.symbol} <span className="text-xs text-fg-3">{x.market} · {x.currency}</span></td>
                      <td className="num py-1 text-right">{formatPercent(x.price_shock_pct, { digits: 1 })}</td>
                      <td className="num py-1 text-right">{x.currency === r.base ? "—" : formatPercent(x.fx_shock_pct, { digits: 1 })}</td>
                      <td className="num py-1 text-right">{formatMoney(x.before, r.base, 0)}</td>
                      <td className="num py-1 text-right">{formatMoney(x.after, r.base, 0)}</td>
                      <td className="py-1 text-right"><PnlText value={x.change} currency={r.base} /></td>
                    </tr>
                  ))}
                  {r.cash.map((c) => (
                    <tr key={c.currency} className="border-b border-line-subtle/60 text-fg-2">
                      <td className="py-1">Cash ({c.currency})</td>
                      <td className="py-1 text-right">—</td>
                      <td className="num py-1 text-right">{c.currency === r.base ? "—" : formatPercent(c.fx_shock_pct, { digits: 1 })}</td>
                      <td className="num py-1 text-right">{formatMoney(c.before, r.base, 0)}</td>
                      <td className="num py-1 text-right">{formatMoney(c.after, r.base, 0)}</td>
                      <td className="py-1 text-right"><PnlText value={c.change} currency={r.base} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {r.unpriced.length > 0 && <p className="text-xs text-warn">Left out (no usable mark): {r.unpriced.join(", ")}.</p>}
            <p className="text-xs leading-4 text-fg-3">{r.method} {r.hypothetical}</p>
          </>
        ) : (
          <p className="text-[13px] text-fg-2">Choose a preset or enter shocks to see the effect on today's holdings.</p>
        )}
      </div>
    </Panel>
  );
}
