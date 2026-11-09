import { useEffect, useState } from "react";
import { Panel } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { Field, Input, Select } from "@/components/ui/Form";
import { Pill } from "@/components/ui/Badges";
import { InlineNotice, SkeletonRows } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { errorMessage, type Prefs } from "@/lib/api/client";
import { formatInstant, formatRelative } from "@/lib/format";
import { useWatchlists } from "@/features/watchlists/api";
import { usePatchPrefs, usePrefs, useSession } from "@/features/settings/api";
import { offlineEnabled, readSnapshot, setOfflineEnabled, syncSnapshot } from "@/lib/offline";
import { useSetQuotas, useUsage, useWorkspaceMutations, useWorkspaces, type Workspace } from "./api";
import { useSwitchWorkspace } from "./WorkspaceMenu";

const BLANK: Omit<Workspace, "id"> = { name: "", start: "/", density: "comfortable", default_watchlist_id: null, chart_symbol: null };

function WorkspaceForm({ initial, onSubmit, onCancel, busy, submitLabel, capture }: {
  initial: Omit<Workspace, "id">;
  onSubmit: (w: Omit<Workspace, "id">) => void;
  onCancel?: () => void;
  busy: boolean;
  submitLabel: string;
  capture?: boolean;
}) {
  const [w, setW] = useState(initial);
  const { data: ws } = useWorkspaces();
  const { data: lists } = useWatchlists();
  return (
    <form
      className="grid gap-3 sm:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({ ...w, chart_symbol: w.chart_symbol?.trim() || null });
      }}
    >
      <Field label="Name">{({ id }) => <Input id={id} value={w.name} maxLength={40} required onChange={(e) => setW({ ...w, name: e.target.value })} />}</Field>
      <Field label="Start page">
        {({ id }) => (
          <Select id={id} value={w.start} onChange={(e) => setW({ ...w, start: e.target.value })}>
            {ws?.start_pages.map((p) => <option key={p.path} value={p.path}>{p.label}</option>)}
          </Select>
        )}
      </Field>
      {!capture && (
        <>
          <Field label="Density">
            {({ id }) => (
              <Select id={id} value={w.density} onChange={(e) => setW({ ...w, density: e.target.value as Workspace["density"] })}>
                <option value="comfortable">Comfortable</option>
                <option value="compact">Compact</option>
              </Select>
            )}
          </Field>
          <Field label="Default watchlist">
            {({ id }) => (
              <Select id={id} value={w.default_watchlist_id ?? ""} onChange={(e) => setW({ ...w, default_watchlist_id: e.target.value ? Number(e.target.value) : null })}>
                <option value="">Keep the current one</option>
                {lists?.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </Select>
            )}
          </Field>
          <Field label="Overview chart symbol" hint="Blank keeps the current chart symbol" className="sm:col-span-2">
            {({ id, describedBy }) => <Input id={id} aria-describedby={describedBy} className="num" value={w.chart_symbol ?? ""} maxLength={32} onChange={(e) => setW({ ...w, chart_symbol: e.target.value })} />}
          </Field>
        </>
      )}
      <div className="flex gap-2 sm:col-span-2">
        <Button type="submit" variant="primary" size="sm" loading={busy}>{submitLabel}</Button>
        {onCancel && <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>}
      </div>
    </form>
  );
}

export function WorkspacesPanel() {
  const { data, isLoading } = useWorkspaces();
  const { data: lists } = useWatchlists();
  const { data: session } = useSession();
  const m = useWorkspaceMutations();
  const switchTo = useSwitchWorkspace();
  const toast = useToast();
  const [editing, setEditing] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Workspace | null>(null);
  const [formKey, setFormKey] = useState(0);
  const readOnly = Boolean(session?.read_only);
  const label = (path: string) => data?.start_pages.find((p) => p.path === path)?.label ?? path;
  return (
    <Panel title="Workspaces" titleId="s-workspaces" className="lg:col-span-2">
      {isLoading || !data ? (
        <SkeletonRows rows={3} />
      ) : (
        <div className="space-y-4">
          <p className="text-xs text-fg-3">A workspace opens its start page and applies its density, default watchlist and chart symbol. Saved on the server, so it survives reloads and other devices. Switch from the label above the page title, the More menu on phones, or the command palette.</p>
          <ul className="divide-y divide-line-subtle">
            {data.items.map((w) => (
              <li key={w.id} className="py-2.5">
                {editing === w.id ? (
                  <WorkspaceForm
                    initial={w}
                    busy={m.replace.isPending}
                    submitLabel="Save workspace"
                    onCancel={() => setEditing(null)}
                    onSubmit={(v) => m.replace.mutate({ id: w.id, ...v }, { onSuccess: () => { setEditing(null); toast("success", "Workspace saved."); }, onError: (e) => toast("error", errorMessage(e)) })}
                  />
                ) : (
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                    <span className="min-w-0 flex-1">
                      <span className="text-[14px] font-medium text-fg">{w.name}</span>
                      {w.id === data.active && <Pill tone="accent" className="ml-2">Active</Pill>}
                      <span className="block text-xs text-fg-3">
                        {label(w.start)} · {w.density} · {w.default_watchlist_id ? (lists?.find((l) => l.id === w.default_watchlist_id)?.name ?? "deleted watchlist") : "current watchlist"} · chart {w.chart_symbol ?? "unchanged"}
                      </span>
                    </span>
                    <Button size="sm" disabled={readOnly} onClick={() => switchTo(w.id)}>Apply</Button>
                    <Button size="sm" variant="ghost" disabled={readOnly} onClick={() => setEditing(w.id)}>Edit</Button>
                    <Button size="sm" variant="ghost" disabled={readOnly || data.items.length <= 1} onClick={() => setDeleting(w)} aria-label={`Delete workspace ${w.name}`}>Delete</Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
          {!readOnly && (
            <div className="rounded-[var(--radius-control)] border border-line-subtle p-3">
              <div className="mb-2 text-[13px] font-medium text-fg-2">Save the current layout as a workspace</div>
              <p className="mb-3 text-xs text-fg-3">Takes the current density, default watchlist and chart symbol.</p>
              <WorkspaceForm
                key={formKey}
                capture
                initial={BLANK}
                busy={m.create.isPending}
                submitLabel="Save as workspace"
                onSubmit={(v) => m.create.mutate({ ...v, capture: true }, { onSuccess: () => { setFormKey((k) => k + 1); toast("success", "Workspace saved."); }, onError: (e) => toast("error", errorMessage(e)) })}
              />
            </div>
          )}
        </div>
      )}
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={`Delete workspace ${deleting?.name ?? ""}?`}
        body="Only the preset is removed; watchlists and preferences stay as they are."
        onConfirm={async () => {
          if (!deleting) return;
          await m.remove.mutateAsync(deleting.id);
          setDeleting(null);
          toast("success", "Workspace deleted.");
        }}
      />
    </Panel>
  );
}

const REFRESH: { value: Prefs["quote_refresh_seconds"]; label: string }[] = [
  { value: 30, label: "Every 30 seconds" },
  { value: 60, label: "Every minute" },
  { value: 120, label: "Every 2 minutes" },
  { value: 300, label: "Every 5 minutes" },
  { value: 0, label: "Manual only" },
];

export function UsagePanel() {
  const { data: u, isLoading } = useUsage();
  const { data: prefs } = usePrefs();
  const patch = usePatchPrefs();
  const setQuotas = useSetQuotas();
  const { data: session } = useSession();
  const toast = useToast();
  const [q, setQ] = useState<{ requests: string; tokens: string; usd: string } | null>(null);
  const readOnly = Boolean(session?.read_only);
  useEffect(() => {
    if (u && q === null) setQ({ requests: u.ai.owner_quotas.requests?.toString() ?? "", tokens: u.ai.owner_quotas.tokens?.toString() ?? "", usd: u.ai.owner_quotas.usd ?? "" });
  }, [u, q]);
  if (isLoading || !u || !prefs) return <Panel title="Usage, quotas and refresh" titleId="s-usage" className="lg:col-span-2"><SkeletonRows rows={5} /></Panel>;
  const kinds = Object.entries(u.provider.by_kind);
  const ttl = u.provider.cache_ttl_seconds;
  const mins = (s: number) => (s >= 3600 ? `${Math.round(s / 3600)} h` : s >= 60 ? `${Math.round(s / 60)} min` : `${s} s`);
  return (
    <Panel title="Usage, quotas and refresh" titleId="s-usage" className="lg:col-span-2">
      <div className="grid gap-6 lg:grid-cols-2">
        <section aria-labelledby="u-prov">
          <h3 id="u-prov" className="mb-2 text-[13px] font-medium text-fg-2">
            Market data · {u.provider.provider}{" "}
            <Pill tone={u.provider.circuit === "closed" ? "pos" : "neg"}>{u.provider.circuit === "closed" ? "healthy" : `paused (${u.provider.circuit})`}</Pill>
          </h3>
          <div tabIndex={0} className="scroll-x scrollbar-thin overflow-x-auto">
            <table className="w-full text-[13px]">
              <caption className="sr-only">Provider requests by data kind since the server process started</caption>
              <thead>
                <tr className="border-b border-line-subtle text-xs text-fg-3">
                  <th scope="col" className="py-1 text-left font-medium">Kind</th>
                  <th scope="col" className="py-1 pl-2 text-right font-medium">Asked</th>
                  <th scope="col" className="py-1 pl-2 text-right font-medium">From cache</th>
                  <th scope="col" className="py-1 pl-2 text-right font-medium">Upstream</th>
                  <th scope="col" className="py-1 pl-2 text-right font-medium">Failed</th>
                  <th scope="col" className="py-1 pl-2 text-right font-medium">Cache life</th>
                </tr>
              </thead>
              <tbody>
                {kinds.length === 0 && <tr><td colSpan={6} className="py-2 text-xs text-fg-3">No requests since the server started.</td></tr>}
                {kinds.map(([k, c]) => (
                  <tr key={k} className="border-b border-line-subtle/60">
                    <th scope="row" className="py-1 text-left font-normal">{k}</th>
                    <td className="num py-1 pl-2 text-right">{c.requests}</td>
                    <td className="num py-1 pl-2 text-right">{c.cache_hits}</td>
                    <td className="num py-1 pl-2 text-right">{c.upstream_calls}</td>
                    <td className="num py-1 pl-2 text-right">{c.upstream_failures}{c.stale_served ? ` (${c.stale_served} stale shown)` : ""}</td>
                    <td className="num py-1 pl-2 text-right">{ttl[k] ? mins(ttl[k]) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-fg-3">Since {formatInstant(u.provider.since, prefs.display_timezone)} ({formatRelative(u.provider.since)}). {u.provider.note} SEC EDGAR: {u.sec.enabled ? `on, ≤ ${u.sec.max_requests_per_second} requests/s (fair-access limit 10/s)` : `off — ${(u.sec.reason ?? "not configured").replace(/\.$/, "")}`}.</p>
        </section>

        <section aria-labelledby="u-ai" className="space-y-3">
          <h3 id="u-ai" className="text-[13px] font-medium text-fg-2">
            AI research · {u.ai.enabled ? `${u.ai.provider_label} (${u.ai.model})` : "off"}
          </h3>
          <dl className="space-y-1.5 text-[13px]">
            <div className="flex justify-between gap-2"><dt className="text-fg-2">Answers today (UTC)</dt><dd className="num">{u.ai.budget.requests_used} of {u.ai.budget.requests_limit}</dd></div>
            {u.ai.free_tier ? (
              <div className="flex justify-between gap-2"><dt className="text-fg-2">Tokens today</dt><dd className="num">{u.ai.budget.tokens_used.toLocaleString()} of {(u.ai.budget.tokens_limit ?? 0).toLocaleString()}</dd></div>
            ) : (
              <div className="flex justify-between gap-2"><dt className="text-fg-2">Spend today</dt><dd className="num">${Number(u.ai.budget.spent_usd).toFixed(4)} of ${Number(u.ai.budget.limit_usd ?? 0).toFixed(2)}</dd></div>
            )}
          </dl>
          {!u.ai.enabled && <p className="text-xs text-fg-3">{u.ai.reason}</p>}
          {q && (
            <form
              className="grid grid-cols-2 gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                const n = (s: string) => (s.trim() === "" ? null : Number(s));
                setQuotas.mutate(
                  { requests: n(q.requests), tokens: n(q.tokens), usd: q.usd.trim() === "" ? null : q.usd.trim() },
                  { onSuccess: () => toast("success", "Quotas saved."), onError: (err) => toast("error", errorMessage(err)) },
                );
              }}
            >
              <Field label="My daily answer limit" hint={`Blank = server cap (${u.ai.server_caps.requests})`}>
                {({ id, describedBy }) => <Input id={id} aria-describedby={describedBy} inputMode="numeric" className="num" disabled={readOnly} value={q.requests} onChange={(e) => setQ({ ...q, requests: e.target.value })} />}
              </Field>
              {u.ai.free_tier ? (
                <Field label="My daily token limit" hint={`Blank = server cap (${u.ai.server_caps.tokens.toLocaleString()})`}>
                  {({ id, describedBy }) => <Input id={id} aria-describedby={describedBy} inputMode="numeric" className="num" disabled={readOnly} value={q.tokens} onChange={(e) => setQ({ ...q, tokens: e.target.value })} />}
                </Field>
              ) : (
                <Field label="My daily spend limit (USD)" hint={`Blank = server cap ($${u.ai.server_caps.usd})`}>
                  {({ id, describedBy }) => <Input id={id} aria-describedby={describedBy} inputMode="decimal" className="num" disabled={readOnly} value={q.usd} onChange={(e) => setQ({ ...q, usd: e.target.value })} />}
                </Field>
              )}
              <div className="col-span-2 flex items-center gap-3">
                <Button type="submit" size="sm" variant="primary" disabled={readOnly} loading={setQuotas.isPending}>Save quotas</Button>
                <span className="text-xs text-fg-3">A quota can only lower the server's cap; it is enforced on the server before each request.</span>
              </div>
            </form>
          )}
        </section>

        <section aria-labelledby="u-refresh" className="lg:col-span-2">
          <h3 id="u-refresh" className="mb-2 text-[13px] font-medium text-fg-2">Refresh</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Quotes and valuations in the browser" hint={`The server keeps a quote for ${mins(ttl.quote ?? 300)}; refreshing more often shows the same observation. Polling pauses while the tab is hidden.`}>
              {({ id, describedBy }) => (
                <Select
                  id={id}
                  aria-describedby={describedBy}
                  disabled={readOnly}
                  value={prefs.quote_refresh_seconds}
                  onChange={(e) => patch.mutate({ quote_refresh_seconds: Number(e.target.value) as Prefs["quote_refresh_seconds"] }, { onSuccess: () => toast("success", "Refresh preference saved."), onError: (err) => toast("error", errorMessage(err)) })}
                >
                  {REFRESH.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                </Select>
              )}
            </Field>
            <InlineNotice className="self-start">Alerts are checked by the worker every {mins(u.refresh.worker_poll_seconds)} (server setting ALERT_POLL_SECONDS), independent of this page.</InlineNotice>
          </div>
        </section>
      </div>
    </Panel>
  );
}

export function OfflinePanel() {
  const { data: prefs } = usePrefs();
  const toast = useToast();
  const [on, setOn] = useState(offlineEnabled());
  const [snap, setSnap] = useState(readSnapshot());
  const [busy, setBusy] = useState(false);
  const tz = prefs?.display_timezone ?? "Asia/Kolkata";
  const sync = async () => {
    setBusy(true);
    try {
      const s = await syncSnapshot(tz);
      setSnap(s);
      toast(s ? "success" : "error", s ? "Offline copy updated." : "The offline copy could not be saved in this browser.");
    } catch (e) {
      toast("error", errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Panel title="Offline copy and app install" titleId="s-offline">
      <div className="space-y-3 text-[13px]">
        <label className="flex cursor-pointer items-start gap-3">
          <input
            type="checkbox"
            className="mt-0.5 size-4 accent-[var(--accent)]"
            checked={on}
            onChange={(e) => {
              setOfflineEnabled(e.target.checked);
              setOn(e.target.checked);
              if (e.target.checked) void sync();
              else {
                setSnap(null);
                toast("success", "Offline copy erased from this device.");
              }
            }}
          />
          <span>
            <span className="text-fg">Keep a read-only offline copy on this device</span>
            <span className="block text-xs text-fg-3">
              Stores your first five watchlists with their last observed prices and your holdings in this browser, refreshed every 10 minutes while MarketDesk is open. When the server cannot be reached it is shown with its sync time, labelled "not live". Erased when you sign out, when the session ends, or when you turn this off. Off by default.
            </span>
          </span>
        </label>
        {on && (
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-fg-2">Last synced: {snap ? <span className="num">{formatInstant(snap.synced_at, tz)}</span> : "not yet"}</span>
            <Button size="sm" loading={busy} onClick={sync}>Sync now</Button>
          </div>
        )}
        <p className="text-xs text-fg-3">
          Install: use your browser's "Install app" or "Add to Home Screen". The installed app caches only its own code and icons; market data and your ledger always come from the server, apart from the opt-in copy above.
        </p>
      </div>
    </Panel>
  );
}
