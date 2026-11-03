import { Download, RotateCcw, SkipForward, Zap, ZapOff } from "lucide-react";
import { Panel } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Field, Select } from "@/components/ui/Form";
import { Segmented } from "@/components/ui/Segmented";
import { Pill } from "@/components/ui/Badges";
import { InlineNotice, SkeletonRows } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { errorMessage, type Prefs } from "@/lib/api/client";
import { formatInstant, formatRelative, formatSessionDate } from "@/lib/format";
import { useWatchlists } from "@/features/watchlists/api";
import { applyDensity, applyTheme, useFixture, useFixtureAction, usePatchPrefs, usePrefs, useSession, useStatus } from "./api";

const TIMEZONES = ["Asia/Kolkata", "UTC", "Asia/Singapore", "Asia/Dubai", "Europe/London", "America/New_York"];

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-line-subtle py-2 text-[13px] last:border-0">
      <dt className="text-fg-2">{label}</dt>
      <dd className="text-right text-fg">{children}</dd>
    </div>
  );
}

export function SettingsPage() {
  const { data: prefs, isLoading } = usePrefs();
  const patch = usePatchPrefs();
  const { data: lists } = useWatchlists();
  const { data: status } = useStatus();
  const { data: session } = useSession();
  const fixture = useFixture();
  const action = useFixtureAction();
  const toast = useToast();
  const readOnly = Boolean(session?.read_only);
  const tz = prefs?.display_timezone ?? "Asia/Kolkata";

  const save = (p: Partial<Prefs>, msg = "Preference saved.") =>
    patch.mutate(p, { onSuccess: () => toast("success", msg), onError: (e) => toast("error", errorMessage(e)) });

  if (isLoading || !prefs) return <div className="p-6"><SkeletonRows rows={8} /></div>;
  const health = (status?.provider_health ?? {}) as { circuit?: string; consecutive_failures?: number; last_success_at?: string | null; last_failure_at?: string | null; last_error?: { kind?: string; message?: string } | null };

  return (
    <div className="grid grid-cols-1 gap-4 p-4 md:p-6 lg:grid-cols-2 lg:gap-5">
      {readOnly && <InlineNotice tone="warn" className="lg:col-span-2">Read-only public demo: preferences and data cannot be changed. Theme switches apply to this browser only.</InlineNotice>}
      <Panel title="Appearance" titleId="s-appear">
        <div className="space-y-5">
          <div>
            <div className="mb-2 text-[13px] font-medium text-fg-2" id="theme-label">Theme</div>
            <Segmented
              label="Theme"
              size="md"
              value={prefs.theme}
              onChange={(t) => {
                applyTheme(t);
                if (!readOnly) save({ theme: t }, "Theme saved.");
              }}
              options={[{ value: "dark", label: "Dark" }, { value: "light", label: "Light" }, { value: "system", label: "System" }]}
            />
          </div>
          <div>
            <div className="mb-2 text-[13px] font-medium text-fg-2">Table density</div>
            <Segmented
              label="Table density"
              size="md"
              value={prefs.density}
              onChange={(d) => {
                applyDensity(d);
                if (!readOnly) save({ density: d });
              }}
              options={[{ value: "comfortable", label: "Comfortable" }, { value: "compact", label: "Compact" }]}
            />
          </div>
        </div>
      </Panel>

      <Panel title="Workspace" titleId="s-ws">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Default watchlist" hint="Shown on Overview and used by the star button.">
            {({ id, describedBy }) => (
              <Select id={id} aria-describedby={describedBy} disabled={readOnly || !lists?.length} value={prefs.default_watchlist_id ?? ""} onChange={(e) => save({ default_watchlist_id: Number(e.target.value) })}>
                {!lists?.length && <option value="">No watchlists</option>}
                {lists?.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </Select>
            )}
          </Field>
          <Field label="Display timezone" hint="Instants are stored in UTC; daily bars keep their exchange session date.">
            {({ id, describedBy }) => (
              <Select id={id} aria-describedby={describedBy} disabled={readOnly} value={prefs.display_timezone} onChange={(e) => save({ display_timezone: e.target.value })}>
                {Array.from(new Set([prefs.display_timezone, ...TIMEZONES])).map((t) => <option key={t} value={t}>{t}</option>)}
              </Select>
            )}
          </Field>
        </div>
        <p className="mt-3 text-xs text-fg-3">Overview chart symbol: {prefs.chart_symbol ? <span className="num text-fg-2">{prefs.chart_symbol}</span> : <span className="text-fg-2">first symbol of the default watchlist</span>} (change it from the chart header).</p>
      </Panel>

      <Panel title="Data status" titleId="s-data">
        {!status ? (
          <SkeletonRows rows={5} />
        ) : (
          <>
            <dl>
              <Row label="Provider">{status.sample_data ? <Pill tone="info">Sample dataset (fixture)</Pill> : <Pill>Yahoo Finance via yfinance</Pill>}</Row>
              {status.sample_data && <Row label="Dataset date"><span className="num">{formatSessionDate(status.dataset_date)}</span></Row>}
              <Row label="Market status">{status.market_status}</Row>
              <Row label="Provider health">{health.circuit === "closed" ? "Healthy" : health.circuit === "open" ? "Paused after repeated failures" : "Recovering"}{health.consecutive_failures ? ` · ${health.consecutive_failures} recent failure(s)` : ""}</Row>
              <Row label="Last successful fetch">{health.last_success_at ? `${formatRelative(health.last_success_at)}` : "None in this server process yet"}</Row>
              {health.last_error && <Row label="Last error"><span className="text-warn">{health.last_error.message}</span></Row>}
              <Row label="Storage">
                {status.storage.persistent ? (
                  <span>Persistent disk · <span className="num">{status.storage.path}</span></span>
                ) : status.storage.warning ? (
                  <span className="text-warn">Not persistent — see warning below</span>
                ) : (
                  <span className="num">{status.storage.path}</span>
                )}
              </Row>
              <Row label="Alert worker">{status.worker.running ? `Running · last cycle ${formatRelative(status.worker.last_cycle_at)}` : status.worker.message}</Row>
              <Row label="Server mode">{status.environment} · {status.auth_mode === "dev_bypass" ? "development auth bypass" : "owner login"}</Row>
            </dl>
            {status.storage.warning && <InlineNotice tone="warn" className="mt-3">{status.storage.message}</InlineNotice>}
            <p className="mt-3 text-xs leading-4 text-fg-3">
              Server cache defaults: quotes 5 min, history 1 h, fundamentals and search 24 h. A cached or recent fetch does not prove a fresh market quotation; always check the market time. When the provider fails, the last successful result is shown and marked stale.
            </p>
          </>
        )}
        {fixture.data?.enabled && (
          <div className="mt-4 space-y-3 rounded-[var(--radius-control)] border border-info/30 bg-info-soft p-3">
            <div className="text-[13px] font-semibold text-info">Sample data controls</div>
            <p className="text-xs leading-4 text-fg-2">
              Session {fixture.data.cursor_index + 1} of {fixture.data.sessions.length}: <span className="num text-fg">{formatSessionDate(fixture.data.cursor_date)}</span>. These controls exist only in fixture mode and help verify alerts and outage handling deterministically.
            </p>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" icon={<SkipForward className="size-3.5" aria-hidden />} disabled={readOnly || fixture.data.cursor_index >= fixture.data.sessions.length - 1} onClick={() => action.mutate({ kind: "advance" }, { onError: (e) => toast("error", errorMessage(e)) })}>
                Advance session
              </Button>
              <Button size="sm" icon={<RotateCcw className="size-3.5" aria-hidden />} disabled={readOnly} onClick={() => action.mutate({ kind: "reset" })}>
                Reset to base date
              </Button>
              <Button
                size="sm"
                variant={fixture.data.fault ? "primary" : "secondary"}
                icon={fixture.data.fault ? <Zap className="size-3.5" aria-hidden /> : <ZapOff className="size-3.5" aria-hidden />}
                disabled={readOnly}
                aria-pressed={fixture.data.fault}
                onClick={() => action.mutate({ kind: "fault", enabled: !fixture.data!.fault }, { onSuccess: (d) => toast("info", d.fault ? "Provider outage simulation on." : "Provider outage simulation off.") })}
              >
                {fixture.data.fault ? "End outage simulation" : "Simulate provider outage"}
              </Button>
            </div>
            {fixture.data.fault && <InlineNotice tone="warn">Outage simulation is on: panels show their last successful data marked stale, and alerts are not evaluated.</InlineNotice>}
          </div>
        )}
      </Panel>

      <Panel title="Export and backup" titleId="s-backup">
        <div className="flex flex-wrap gap-2">
          <a className="inline-flex h-9 items-center gap-2 rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm hover:bg-hover max-md:h-11" href="/api/portfolio/export/transactions.csv">
            <Download className="size-4" aria-hidden /> Transactions CSV
          </a>
          <a className="inline-flex h-9 items-center gap-2 rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm hover:bg-hover max-md:h-11" href="/api/portfolio/export/holdings.csv">
            <Download className="size-4" aria-hidden /> Holdings CSV
          </a>
        </div>
        <div className="mt-4 space-y-2 text-[13px] leading-5 text-fg-2">
          <p>CSV exports re-import cleanly; spreadsheet formulas in text cells are neutralised with a leading apostrophe.</p>
          <p>
            For a full backup (watchlists, transactions, alerts, journal, settings) run on the server:
          </p>
          <pre className="num overflow-x-auto rounded-[var(--radius-control)] border border-line-subtle bg-canvas px-3 py-2 text-xs text-fg">marketdesk backup /data/backups/marketdesk-$(date +%F).db</pre>
          <p className="text-xs text-fg-3">This uses SQLite's online backup API, so it is consistent while the app runs. Restore with <code className="num">marketdesk restore FILE</code> after stopping the web and worker services.</p>
        </div>
      </Panel>

      <Panel title="About" titleId="s-about" className="lg:col-span-2">
        <div className="grid gap-6 md:grid-cols-2">
          <div className="space-y-2 text-[13px] leading-5 text-fg-2">
            <p><span className="font-semibold text-fg">MarketDesk {status ? `v${status.version}` : ""}</span> — a personal market research terminal.</p>
            <p>For research and record keeping only. It does not place orders, connect to a broker, or make investment recommendations. Briefings are produced by fixed rules and never infer why a price moved.</p>
            <p>Average-cost P&amp;L is an analytical convention, not a tax computation.</p>
            {status?.sample_data && <p className="text-info">{status.dataset_disclaimer}</p>}
            {status && <p className="text-xs text-fg-3">Times shown in {tz}. Last status check {formatInstant(new Date().toISOString(), tz)}.</p>}
          </div>
          <div>
            <h3 className="mb-2 text-xs font-semibold tracking-wide text-fg-3 uppercase">Attribution and licences</h3>
            <ul className="space-y-2 text-[13px]">
              {status?.attribution.map((a) => (
                <li key={a.name as string}>
                  <a href={a.url as string} target="_blank" rel="noreferrer noopener" className="font-medium text-fg hover:text-accent-text hover:underline">{a.name as string}</a>{" "}
                  <span className="text-xs text-fg-3">· {a.license as string}</span>
                  <p className="text-xs leading-4 text-fg-3">{a.note as string}</p>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Panel>
    </div>
  );
}
