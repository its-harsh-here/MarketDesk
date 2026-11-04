import { Pencil, Plus, RotateCcw, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { Button, IconButton } from "@/components/ui/Button";
import { Field } from "@/components/ui/Form";
import { Panel } from "@/components/ui/Panel";
import { EmptyState, ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { errorMessage } from "@/lib/api/client";
import { DASH, formatInstant, formatRelative } from "@/lib/format";
import { cn } from "@/lib/cn";
import { useSession } from "@/features/settings/api";
import { SymbolPicker } from "@/features/search/SymbolPicker";
import { useCatalog, usePeerMutations, usePeers, type MetricDef } from "./api";
import { MetricValue } from "./cells";

const PEER_METRICS = [
  "last_price", "change_1d_pct", "return_1y_pct", "market_cap", "pe_ratio", "price_to_book", "dividend_yield_pct",
  "revenue_growth_pct", "net_margin_pct", "roe_pct", "debt_to_equity", "volatility_1y_pct",
];

/** Side-by-side comparison of an instrument with up to five peers the owner chooses (or suggestions to start). */
export function PeersTab({ symbol }: { symbol: string }) {
  const q = usePeers(symbol);
  const catalog = useCatalog();
  const m = usePeerMutations(symbol);
  const toast = useToast();
  const { data: session } = useSession();
  const [editing, setEditing] = useState<string[] | null>(null);
  const [pick, setPick] = useState("");
  const p = q.data;
  const defs = new Map((catalog.data?.metrics ?? []).map((d) => [d.key, d]));
  const metrics = PEER_METRICS.map((k) => defs.get(k)).filter((d): d is MetricDef => Boolean(d));
  const ro = Boolean(session?.read_only);

  const save = (symbols: string[]) =>
    m.save.mutate(symbols, {
      onSuccess: () => {
        setEditing(null);
        toast("success", "Peer group saved.");
      },
    });

  return (
    <Panel title="Peers" titleId="peers-title" className="lg:col-span-12" refreshing={q.isFetching && !q.isLoading} wrapHeader
      meta={p ? (p.source === "saved" ? "Your peer group" : "Suggested peers") : undefined}
      actions={
        p && !editing ? (
          <div className="flex gap-2">
            <Button size="sm" icon={<Pencil className="size-4" aria-hidden />} disabled={ro} onClick={() => setEditing(p.peers.map((x) => x.symbol))}>Edit peers</Button>
            {p.source === "saved" && (
              <Button size="sm" variant="ghost" icon={<RotateCcw className="size-4" aria-hidden />} disabled={ro} loading={m.reset.isPending}
                onClick={() => m.reset.mutate(undefined, { onError: (e) => toast("error", errorMessage(e)) })}>Reset to suggestions</Button>
            )}
          </div>
        ) : undefined
      }
    >
      {q.isLoading || !catalog.data ? (
        <SkeletonRows rows={6} />
      ) : q.isError && !p ? (
        <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
      ) : p ? (
        <div className="space-y-3">
          <p className="text-xs leading-4 text-fg-3">{p.note}</p>
          {editing && (
            <div className="space-y-2 rounded-[var(--radius-control)] border border-line-subtle bg-canvas/40 p-3">
              <ul className="flex flex-wrap gap-1.5" aria-label="Chosen peers">
                {editing.map((s) => (
                  <li key={s} className="flex items-center gap-1 rounded-full border border-line px-2.5 py-1 text-xs">
                    <span className="num">{s}</span>
                    <IconButton label={`Remove ${s}`} size="sm" className="size-5" onClick={() => setEditing(editing.filter((x) => x !== s))}>
                      <X className="size-3" aria-hidden />
                    </IconButton>
                  </li>
                ))}
                {editing.length === 0 && <li className="text-xs text-fg-3">No peers chosen.</li>}
              </ul>
              {editing.length < 5 ? (
                <div className="flex items-end gap-2">
                  <Field label="Add a peer" className="min-w-0 flex-1 sm:max-w-sm" hint="Up to five; each is verified with the data provider">
                    {({ id, describedBy }) => (
                      <SymbolPicker id={id} describedBy={describedBy} value={pick} onChange={(s) => {
                        setPick("");
                        if (s && s !== symbol && !editing.includes(s)) setEditing([...editing, s]);
                      }} />
                    )}
                  </Field>
                  <Plus className="mb-2.5 size-4 text-fg-3" aria-hidden />
                </div>
              ) : (
                <p className="text-xs text-fg-3">Five peers is the limit; remove one to add another.</p>
              )}
              {m.save.error && <InlineNotice tone="neg">{errorMessage(m.save.error)}</InlineNotice>}
              <div className="flex gap-2">
                <Button size="sm" variant="primary" loading={m.save.isPending} onClick={() => save(editing)}>Save peers</Button>
                <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
              </div>
            </div>
          )}
          {p.rows.length <= 1 ? (
            <EmptyState title={p.source === "saved" ? "No peers chosen" : "No suggestions yet"}>
              Suggestions come from instruments with loaded data in your watchlists, holdings and screening lists that share this
              company’s industry or sector. Use “Edit peers” to choose your own, or load data on the{" "}
              <Link to="/screener" className="text-accent-text hover:underline">Screener</Link>.
            </EmptyState>
          ) : (
            <div className="scrollbar-thin relative overflow-x-auto">
              <table className="w-full text-[13px]" style={{ minWidth: 220 + 116 * p.rows.length }}>
                <caption className="sr-only">{symbol} compared with its peers</caption>
                <thead>
                  <tr className="border-b border-line-subtle text-xs text-fg-3">
                    <th scope="col" className="py-1.5 pr-3 text-left font-medium">Metric</th>
                    {p.rows.map((r, i) => (
                      <th key={r.symbol} scope="col" className={cn("px-2 py-1.5 text-right font-medium", i === 0 && "text-fg")}>
                        {i === 0 ? (
                          <span className="num">{r.symbol}</span>
                        ) : (
                          <Link to={`/instrument/${encodeURIComponent(r.symbol)}?tab=peers`} className="num hover:text-accent-text">{r.symbol}</Link>
                        )}
                        <span className="block truncate font-normal" title={r.name ?? undefined}>{r.name ?? DASH}</span>
                        {i > 0 && <span className="block text-[11px] font-normal text-fg-3">{p.peers.find((x) => x.symbol === r.symbol)?.reason}</span>}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  <tr className="border-b border-line-subtle/60">
                    <th scope="row" className="py-1.5 pr-3 text-left font-normal text-fg-2">Sector · industry</th>
                    {p.rows.map((r) => <td key={r.symbol} className="px-2 py-1.5 text-right text-xs text-fg-2">{r.sector ?? DASH}{r.industry ? ` · ${r.industry}` : ""}</td>)}
                  </tr>
                  {metrics.map((def) => (
                    <tr key={def.key} className="border-b border-line-subtle/60">
                      <th scope="row" className="py-1.5 pr-3 text-left font-normal text-fg-2" title={def.formula}>{def.label}</th>
                      {p.rows.map((r) => (
                        <td key={r.symbol} className="px-2 py-1.5 text-right">
                          {r.metrics ? <MetricValue def={def} cell={r.metrics[def.key]} currency={r.currency} /> : <span className="text-xs text-fg-3">not loaded</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                  <tr>
                    <th scope="row" className="py-1.5 pr-3 text-left text-xs font-normal text-fg-3">Snapshot</th>
                    {p.rows.map((r) => <td key={r.symbol} className="px-2 py-1.5 text-right text-xs text-fg-3" title={formatInstant(r.computed_at)}>{r.computed_at ? formatRelative(r.computed_at) : DASH}</td>)}
                  </tr>
                </tbody>
              </table>
            </div>
          )}
          <p className="text-xs leading-4 text-fg-3">
            Values are in each listing’s own currency; ratios are computed from the provider’s annual statements. Hover a value
            for its period and source.
            {p.fx?.rate ? ` Suggestions rank market caps at USD/INR ${Number(p.fx.rate).toFixed(4)}.` : ""}
          </p>
        </div>
      ) : null}
    </Panel>
  );
}
