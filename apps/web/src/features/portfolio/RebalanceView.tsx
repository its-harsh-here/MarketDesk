import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Form";
import { Panel } from "@/components/ui/Panel";
import { EmptyState, ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { errorMessage, type Holding } from "@/lib/api/client";
import { DASH, formatMoney, formatPercent, formatQuantity } from "@/lib/format";
import { cn } from "@/lib/cn";
import { useSession } from "@/features/settings/api";
import { useSaveTargets, useSimulate, useTargets, type Simulation } from "./riskApi";

const NUM = /^\d+(\.\d+)?$/;

/** Targets per holding and an editable, hypothetical rebalance. Nothing here places or records an order. */
export function RebalanceView({ account, holdings }: { account: "INR" | "USD"; holdings: Holding[] }) {
  const targets = useTargets(account);
  const save = useSaveTargets(account);
  const sim = useSimulate();
  const toast = useToast();
  const { data: session } = useSession();
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [extra, setExtra] = useState("0");
  const [whole, setWhole] = useState(true);
  const [fee, setFee] = useState("0");
  const [edits, setEdits] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!targets.data) return;
    const d: Record<string, string> = {};
    for (const h of holdings) d[h.symbol] = "";
    for (const t of targets.data.targets) d[t.symbol] = String(Number(t.target_pct));
    setDraft(d);
  }, [targets.data, holdings]);

  const sum = Object.values(draft).reduce((a, v) => a + (NUM.test(v) ? Number(v) : 0), 0);
  const invalid = Object.entries(draft).filter(([, v]) => v !== "" && (!NUM.test(v) || Number(v) > 100)).map(([k]) => k);
  const ro = Boolean(session?.read_only);

  const saveTargets = () =>
    save.mutate(
      Object.entries(draft).filter(([, v]) => v !== "").map(([symbol, v]) => ({ symbol, target_pct: v })),
      { onSuccess: () => toast("success", "Targets saved."), onError: (e) => toast("error", errorMessage(e)) },
    );
  const run = () =>
    sim.mutate(
      { account, extra_cash: NUM.test(extra) ? extra : "0", whole_shares: whole, fee_pct: NUM.test(fee) ? fee : "0" },
      { onSuccess: () => setEdits({}), onError: (e) => toast("error", errorMessage(e)) },
    );

  if (targets.isLoading) return <Panel><SkeletonRows rows={5} /></Panel>;
  if (targets.isError) return <ErrorState message={errorMessage(targets.error)} onRetry={() => targets.refetch()} />;
  if (!holdings.length) {
    return (
      <Panel title="Rebalance">
        <EmptyState title="No holdings to rebalance">Targets and simulations need at least one open position in this account.</EmptyState>
      </Panel>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-12 lg:gap-5">
      <Panel title="Allocation targets" titleId="tgt-title" className="lg:col-span-4 lg:self-start" meta={`${account} account`}>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); saveTargets(); }}>
          <p className="text-xs leading-4 text-fg-3">Target weight of each holding as a percentage of the account total (holdings + cash). Whatever is not targeted stays in cash.</p>
          <ul className="space-y-2">
            {Object.keys(draft).map((sym) => (
              <li key={sym} className="flex items-center gap-2">
                <label htmlFor={`tgt-${sym}`} className="num min-w-0 flex-1 truncate text-[13px]">{sym}</label>
                <Input id={`tgt-${sym}`} inputMode="decimal" className="num h-8 w-20 text-right" aria-invalid={invalid.includes(sym)}
                  value={draft[sym]} placeholder="—" onChange={(e) => setDraft({ ...draft, [sym]: e.target.value })} />
                <span className="text-xs text-fg-3">%</span>
              </li>
            ))}
          </ul>
          <p className={cn("num text-[13px]", sum > 100 ? "text-neg" : "text-fg-2")}>
            Targeted {formatPercent(sum, { signed: false, digits: 1 })} · cash {formatPercent(Math.max(0, 100 - sum), { signed: false, digits: 1 })}
          </p>
          {save.error && <InlineNotice tone="neg">{errorMessage(save.error)}</InlineNotice>}
          <Button type="submit" variant="primary" disabled={ro || sum > 100 || invalid.length > 0} loading={save.isPending}>Save targets</Button>
        </form>
      </Panel>
      <Panel title="Rebalance simulation" titleId="sim-title" className="lg:col-span-8" meta="Hypothetical · no orders are placed">
        <div className="space-y-3">
          <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); run(); }}>
            <Field label={`Add cash (${account})`} className="w-36">
              {({ id }) => <Input id={id} inputMode="decimal" className="num" value={extra} onChange={(e) => setExtra(e.target.value)} aria-invalid={!NUM.test(extra)} />}
            </Field>
            <Field label="Fee per trade (%)" className="w-36">
              {({ id }) => <Input id={id} inputMode="decimal" className="num" value={fee} onChange={(e) => setFee(e.target.value)} aria-invalid={!NUM.test(fee)} />}
            </Field>
            <label className="flex h-9 items-center gap-2 text-[13px] max-md:h-11">
              <input type="checkbox" checked={whole} onChange={(e) => setWhole(e.target.checked)} className="size-4 accent-[var(--accent)]" />
              Whole shares
            </label>
            <Button type="submit" loading={sim.isPending} disabled={!NUM.test(extra) || !NUM.test(fee)}>Simulate with saved targets</Button>
          </form>
          {!targets.data?.targets.length && <p className="text-xs text-fg-3">Save targets first; with none, the simulation moves everything to cash.</p>}
          {sim.data ? <SimTable s={sim.data} edits={edits} setEdits={setEdits} /> : <p className="text-[13px] text-fg-2">Run a simulation to see the trades that would move each holding to its target.</p>}
        </div>
      </Panel>
    </div>
  );
}

function SimTable({ s, edits, setEdits }: { s: Simulation; edits: Record<string, string>; setEdits: (e: Record<string, string>) => void }) {
  const feePct = useMemo(() => {
    const traded = s.rows.reduce((a, r) => a + Math.abs(Number(r.trade_value)), 0);
    return traded ? Number(s.fees) / traded : 0;
  }, [s]);
  const total = Number(s.total);
  const rows = s.rows.map((r) => {
    const sh = edits[r.symbol];
    const shares = sh !== undefined && /^-?\d+(\.\d+)?$/.test(sh) ? Number(sh) : Number(r.trade_shares);
    const tv = shares * Number(r.price);
    const newValue = Number(r.value) + tv;
    return { ...r, shares, tv, fee: Math.abs(tv) * feePct, newValue, edited: sh !== undefined };
  });
  const cashAfter = Number(s.cash_before) + Number(s.extra_cash) - rows.reduce((a, r) => a + r.tv + r.fee, 0);
  return (
    <div className="space-y-2">
      {s.warnings.map((w) => <InlineNotice key={w} tone="warn">{w}</InlineNotice>)}
      {!s.marks_complete && <InlineNotice tone="warn">Some holdings have no usable price; they are left out of the simulation.</InlineNotice>}
      <div className="scrollbar-thin relative overflow-x-auto">
        <table className="w-full min-w-[640px] text-[13px]">
          <caption className="sr-only">Hypothetical trades to reach the targets; edit the shares to try other amounts</caption>
          <thead>
            <tr className="border-b border-line-subtle text-xs text-fg-3">
              <th scope="col" className="py-1.5 text-left font-medium">Holding</th>
              <th scope="col" className="py-1.5 text-right font-medium">Now</th>
              <th scope="col" className="py-1.5 text-right font-medium">Target</th>
              <th scope="col" className="py-1.5 text-right font-medium">Trade (shares)</th>
              <th scope="col" className="py-1.5 text-right font-medium">Trade value</th>
              <th scope="col" className="py-1.5 text-right font-medium">After</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.symbol} className="border-b border-line-subtle/60">
                <th scope="row" className="num py-1.5 text-left font-normal">{r.symbol}<span className="block text-xs text-fg-3">{formatQuantity(r.quantity)} @ {formatMoney(r.price, s.currency)}</span></th>
                <td className="num py-1.5 text-right">{formatPercent(r.weight_pct, { signed: false, digits: 1 })}</td>
                <td className="num py-1.5 text-right">{formatPercent(r.target_pct, { signed: false, digits: 1 })}</td>
                <td className="py-1.5 text-right">
                  <Input aria-label={`Shares to trade for ${r.symbol} (negative sells)`} inputMode="decimal" className={cn("num h-8 w-24 text-right", r.edited && "border-accent")}
                    value={edits[r.symbol] ?? String(Number(r.trade_shares))} onChange={(e) => setEdits({ ...edits, [r.symbol]: e.target.value })} />
                </td>
                <td className={cn("num py-1.5 text-right", r.tv > 0 ? "text-pos" : r.tv < 0 ? "text-neg" : "text-fg-3")}>
                  {r.tv === 0 ? DASH : `${r.tv > 0 ? "Buy " : "Sell "}${formatMoney(Math.abs(r.tv), s.currency)}`}
                </td>
                <td className="num py-1.5 text-right">{formatPercent(total ? (r.newValue / total) * 100 : null, { signed: false, digits: 1 })}</td>
              </tr>
            ))}
            <tr>
              <th scope="row" className="py-1.5 text-left font-normal text-fg-2">Cash</th>
              <td className="num py-1.5 text-right">{formatPercent(total ? ((Number(s.cash_before) + Number(s.extra_cash)) / total) * 100 : null, { signed: false, digits: 1 })}</td>
              <td className="num py-1.5 text-right text-fg-3">{formatPercent(Math.max(0, 100 - Number(s.target_sum_pct)), { signed: false, digits: 1 })}</td>
              <td />
              <td className="num py-1.5 text-right text-fg-2">{formatMoney(cashAfter, s.currency)}</td>
              <td className={cn("num py-1.5 text-right", cashAfter < 0 && "text-neg")}>{formatPercent(total ? (cashAfter / total) * 100 : null, { signed: false, digits: 1 })}</td>
            </tr>
          </tbody>
        </table>
      </div>
      {cashAfter < 0 && <p className="text-xs text-neg">Cash after these trades would be negative: reduce buys or add cash.</p>}
      {s.targets_without_holding.length > 0 && <p className="text-xs text-fg-3">Targets for instruments you do not hold are not simulated: {s.targets_without_holding.join(", ")}.</p>}
      <p className="text-xs leading-4 text-fg-3">
        Total {formatMoney(s.total, s.currency)} (holdings at latest marks + cash + added cash). Estimated fees {formatMoney(rows.reduce((a, r) => a + r.fee, 0), s.currency)}. {s.note} Edited share counts recalculate here only.
      </p>
    </div>
  );
}
