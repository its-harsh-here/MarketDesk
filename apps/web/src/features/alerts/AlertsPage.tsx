import { Bell, ExternalLink, Newspaper, Pause, Pencil, Play, Plus, RotateCcw, SkipForward, Trash } from "lucide-react";
import { useState } from "react";
import { UpcomingResultsPanel } from "@/features/earnings/EarningsTab";
import { useDialogs } from "@/app/dialogs";
import { Panel } from "@/components/ui/Panel";
import { Button, IconButton } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { InstrumentBadge, Pill } from "@/components/ui/Badges";
import { Segmented } from "@/components/ui/Segmented";
import { EmptyState, ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { errorMessage, type Alert, type InboxItem } from "@/lib/api/client";
import { DASH, formatInstant, formatMoney, formatPercent, formatRelative, formatSessionDate, toNumber } from "@/lib/format";
import { useFixture, useFixtureAction, usePrefs, useSession, useStatus } from "@/features/settings/api";
import { BriefingItems } from "@/features/briefing/BriefingItems";
import { useAlertMutations, useAlerts, useInbox, useInboxCounts, useSampleBriefing, type InboxFilters } from "./api";
function WorkerPanel() {
  const { data: status } = useStatus();
  const { data: prefs } = usePrefs();
  const fixture = useFixture();
  const action = useFixtureAction();
  const { data: session } = useSession();
  const toast = useToast();
  const briefing = useSampleBriefing();
  if (!status) return null;
  const w = status.worker;
  const health = status.provider_health as { circuit?: string; last_error?: { message?: string } | null };
  const tz = prefs?.display_timezone;
  const atEnd = fixture.data?.enabled && fixture.data.cursor_index >= fixture.data.sessions.length - 1;
  return (
    <Panel title="Evaluation status" titleId="worker-title" className="lg:col-span-4">
      <dl className="space-y-2.5 text-[13px]">
        <div className="flex items-center justify-between gap-2">
          <dt className="text-fg-2">Worker</dt>
          <dd><Pill tone={w.running ? "pos" : "warn"}>{w.running ? "Running" : w.cycles ? "Heartbeat overdue" : "Not reporting"}</Pill></dd>
        </div>
        <div className="flex justify-between gap-2"><dt className="text-fg-2">Last evaluation</dt><dd className="num text-right">{w.last_cycle_at ? `${formatRelative(w.last_cycle_at)}` : DASH}</dd></div>
        <div className="flex justify-between gap-2"><dt className="text-fg-2">Polling interval</dt><dd className="num">{w.poll_seconds}s</dd></div>
        <div className="flex justify-between gap-2"><dt className="text-fg-2">Provider</dt><dd>{status.sample_data ? "Sample dataset" : "Yahoo (yfinance)"} · {health.circuit === "closed" ? "healthy" : health.circuit}</dd></div>
        {w.last_error && <div className="text-xs text-warn">{w.last_error}</div>}
      </dl>
      <p className="mt-3 text-xs leading-4 text-fg-3">
        {w.message} Detection is sampled at each poll, not tick-by-tick; a price that crosses and returns between polls is not seen. Each observation is evaluated once, and an alert fires once per arm.
        {w.last_cycle_at && ` Last cycle ${formatInstant(w.last_cycle_at, tz)}.`}
      </p>
      {fixture.data?.enabled && (
        <div className="mt-4 rounded-[var(--radius-control)] border border-info/30 bg-info-soft p-3">
          <div className="text-xs font-semibold text-info">Sample replay (fixture mode)</div>
          <p className="mt-1 text-xs leading-4 text-fg-2">
            Scheduled briefings follow real exchange calendars and are not written from the fixed sample dataset; “Write sample briefing” writes the end-of-session briefing for the current sample session instead.
          </p>
          <p className="mt-1 text-xs leading-4 text-fg-2">
            Current sample session: <span className="num text-fg">{formatSessionDate(fixture.data.cursor_date)}</span>. Advancing moves the fixed dataset to its next session so the worker sees a new observation — a deterministic way to test alerts. Timestamps stay historical.
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              size="sm"
              icon={<SkipForward className="size-3.5" aria-hidden />}
              disabled={session?.read_only || atEnd}
              title={atEnd ? "End of sample dataset" : session?.read_only ? "Read-only demo" : undefined}
              loading={action.isPending}
              onClick={() => action.mutate({ kind: "advance" }, { onSuccess: (d) => toast("info", `Sample session advanced to ${formatSessionDate(d.cursor_date)}.`), onError: (e) => toast("error", errorMessage(e)) })}
            >
              Advance sample session
            </Button>
            <Button size="sm" variant="ghost" icon={<RotateCcw className="size-3.5" aria-hidden />} disabled={session?.read_only || fixture.data.cursor_index === 0} onClick={() => action.mutate({ kind: "reset" })}>
              Reset
            </Button>
            <Button
              size="sm"
              variant="ghost"
              icon={<Newspaper className="size-3.5" aria-hidden />}
              disabled={session?.read_only}
              loading={briefing.isPending}
              onClick={() => briefing.mutate(undefined, { onSuccess: (b) => toast("info", `Sample briefing written for ${formatSessionDate(b.session_date)}.`), onError: (e) => toast("error", errorMessage(e)) })}
            >
              Write sample briefing
            </Button>
          </div>
        </div>
      )}
    </Panel>
  );
}

/** When the alert next becomes active again, in words. */
export function alertState(a: Alert, now = Date.now()): { label: string; tone: "pos" | "accent" | "neutral" | "info" } {
  if (a.active) return { label: a.rule === "FILING" || a.rule === "EARNINGS" ? "Watching" : "Armed", tone: "pos" };
  if (a.rearm_at) {
    const mins = Math.max(1, Math.round((new Date(a.rearm_at).getTime() - now) / 60000));
    return { label: `Rearms in ${mins < 90 ? `${mins} min` : `${Math.round(mins / 60)} h`}`, tone: "info" };
  }
  if (a.events.length && a.events[0].arm_seq === a.arm_seq) return { label: "Triggered", tone: "accent" };
  return { label: "Paused", tone: "neutral" };
}

function lastObserved(a: Alert, tz?: string) {
  if (a.rule === "FILING") return <span className="text-xs text-fg-3">SEC filings</span>;
  if (a.rule === "EARNINGS") return <span className="text-xs text-fg-3">Results calendar</span>;
  if (a.rule === "VOLUME" || a.rule === "VOLATILITY")
    return <span className="text-xs text-fg-2">{a.last_observed_market_time ? `Session ${formatSessionDate(a.last_observed_market_time)}` : "No session yet"}</span>;
  return (
    <span className="inline-flex flex-col items-end">
      <span className="num">{formatMoney(a.last_observed_price, a.instrument.currency)}</span>
      {a.last_observed_market_time && <span className="text-xs text-fg-3">{formatInstant(a.last_observed_market_time, tz)}</span>}
    </span>
  );
}

function DeliveryPills({ item }: { item: NonNullable<InboxItem["alert"]> }) {
  return (
    <span className="inline-flex flex-wrap gap-1.5">
      {item.deliveries.map((d) => (
        <Pill key={d.channel} tone={d.status === "failed" ? "neg" : "neutral"}>
          {d.channel === "in_app" ? "In-app" : d.channel}: {d.status}
          {d.status === "failed" && d.last_error ? ` (${d.last_error})` : ""}
        </Pill>
      ))}
    </span>
  );
}

function InboxRow({ item, tz, readOnly }: { item: InboxItem; tz?: string; readOnly: boolean }) {
  const m = useAlertMutations();
  const [expanded, setExpanded] = useState(false);
  const unread = !item.read_at;
  const b = item.briefing;
  const lines = b?.items ?? [];
  const shown = expanded ? lines : lines.slice(0, 3);
  return (
    <li className="flex gap-3 px-[var(--panel-pad)] py-3">
      <span className={unread ? "text-accent-text" : "text-fg-3"} aria-hidden>
        {item.type === "alert" ? <Bell className="mt-0.5 size-4" /> : <Newspaper className="mt-0.5 size-4" />}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <h3 className="text-[13px] font-semibold text-fg">{item.title}</h3>
          {unread && <Pill tone="accent">New</Pill>}
          {b?.data_status === "sample" && <Pill tone="info">Sample data</Pill>}
          {b?.data_status === "stale" && <Pill tone="warn">Includes stale data</Pill>}
        </div>
        <p className="mt-0.5 text-xs text-fg-3">
          {item.type === "alert" ? "Detected" : "Generated"} <span className="num">{formatInstant(item.at, tz)}</span>
          {item.alert?.observed_market_time && (
            <>
              {" "}· {item.alert.rule === "VOLUME" || item.alert.rule === "VOLATILITY" ? "session" : item.alert.rule === "FILING" ? "filed" : item.alert.rule === "EARNINGS" ? "reminded" : "market time"}{" "}
              <span className="num">
                {item.alert.rule === "PRICE" || item.alert.rule === "CROSS" ? formatInstant(item.alert.observed_market_time, tz) : formatSessionDate(item.alert.observed_market_time)}
              </span>
            </>
          )}
          {b && <> · session <span className="num">{formatSessionDate(b.session_date)}</span></>}
        </p>
        {item.alert && (
          <>
            {item.alert.explanation && <p className="mt-1.5 text-[13px] leading-5 text-fg-2">{item.alert.explanation}</p>}
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <DeliveryPills item={item.alert} />
              {item.alert.link && (
                <a href={item.alert.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-accent-text hover:underline">
                  Open source document <ExternalLink className="size-3" aria-hidden />
                </a>
              )}
            </div>
          </>
        )}
        {b && (
          <div className="mt-2">
            <BriefingItems items={shown} />
            {lines.length > 3 && (
              <button type="button" aria-expanded={expanded} className="mt-2 text-xs text-accent-text hover:underline" onClick={() => setExpanded((x) => !x)}>
                {expanded ? "Show fewer lines" : `Show all ${lines.length} lines`}
              </button>
            )}
            {expanded && <p className="mt-2 text-xs leading-4 text-fg-3">{b.method}</p>}
          </div>
        )}
      </div>
      {unread && !readOnly && (
        <Button size="sm" variant="ghost" className="self-start" onClick={() => m.read.mutate({ type: item.type, id: item.id })} aria-label={`Mark read: ${item.title}`}>
          Mark read
        </Button>
      )}
    </li>
  );
}

function InboxPanel({ readOnly, tz }: { readOnly: boolean; tz?: string }) {
  const [type, setType] = useState<"all" | "alert" | "briefing">("all");
  const [market, setMarket] = useState<"all" | "IN" | "US">("all");
  const [unread, setUnread] = useState(false);
  const filters: InboxFilters = { ...(type !== "all" && { type }), ...(market !== "all" && { market }), ...(unread && { unread }) };
  const q = useInbox(filters);
  const counts = useInboxCounts();
  const m = useAlertMutations();
  const toast = useToast();
  const held = counts.data?.held ?? 0;
  return (
    <Panel
      title="Inbox"
      titleId="inbox-title"
      className="lg:col-span-12"
      bodyClassName="p-0"
      refreshing={q.isFetching && !q.isLoading}
      meta={counts.data ? `${counts.data.total} unread` : undefined}
      actions={
        !readOnly && (counts.data?.total ?? 0) > 0 && (
          <Button size="sm" variant="ghost" onClick={() => m.read.mutate(undefined, { onSuccess: (r) => toast("success", `${r.updated} marked read.`), onError: (e) => toast("error", errorMessage(e)) })}>
            Mark all read
          </Button>
        )
      }
    >
      <div className="flex flex-wrap items-center gap-2 border-b border-line-subtle px-[var(--panel-pad)] py-2.5">
        <Segmented label="Inbox item type" value={type} onChange={setType} options={[{ value: "all", label: "All" }, { value: "alert", label: "Alerts" }, { value: "briefing", label: "Briefings" }]} />
        <Segmented label="Market" value={market} onChange={setMarket} options={[{ value: "all", label: "All markets" }, { value: "IN", label: "India" }, { value: "US", label: "US" }]} />
        <label className="inline-flex min-h-8 items-center gap-2 text-[13px] text-fg-2">
          <input type="checkbox" className="size-4 accent-[var(--accent)]" checked={unread} onChange={(e) => setUnread(e.target.checked)} />
          Unread only
        </label>
      </div>
      {held > 0 && (
        <InlineNotice className="mx-[var(--panel-pad)] mt-3">
          {held} alert notice{held > 1 ? "s are" : " is"} held by quiet hours and will appear when the window ends.
        </InlineNotice>
      )}
      {q.isLoading ? (
        <SkeletonRows rows={3} className="p-4" />
      ) : q.isError ? (
        <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
      ) : !q.data!.length ? (
        <p className="px-[var(--panel-pad)] py-6 text-center text-[13px] text-fg-3">
          {unread || type !== "all" || market !== "all"
            ? "Nothing matches these filters."
            : "No alerts or briefings yet. Briefings are written before each session opens and after it closes, by exchange calendar, for markets with symbols on your watchlists."}
        </p>
      ) : (
        <ul aria-label="Inbox items" className="divide-y divide-line-subtle">
          {q.data!.map((it) => <InboxRow key={`${it.type}-${it.id}`} item={it} tz={tz} readOnly={readOnly} />)}
        </ul>
      )}
    </Panel>
  );
}

export function AlertsPage() {
  const alerts = useAlerts();
  const { data: session } = useSession();
  const { data: prefs } = usePrefs();
  const { open } = useDialogs();
  const m = useAlertMutations();
  const toast = useToast();
  const [deleting, setDeleting] = useState<Alert | null>(null);
  const readOnly = Boolean(session?.read_only);
  const tz = prefs?.display_timezone;

  const distance = (a: Alert) => {
    if (a.rule !== "PRICE" && a.rule !== "CROSS") return null;
    const p = toNumber(a.last_observed_price);
    const t = toNumber(a.target_price);
    if (p === null || t === null || p === 0) return null;
    return ((t - p) / p) * 100;
  };

  const cols: Column<Alert>[] = [
    { key: "inst", header: "Instrument", render: (a) => <InstrumentBadge symbol={a.symbol} name={a.instrument.name} /> },
    {
      key: "cond",
      header: "Condition",
      render: (a) => (
        <span className="inline-flex min-w-44 flex-col">
          <span className="text-fg">{a.description}</span>
          {(a.quiet_start || a.cooldown_minutes) && (
            <span className="text-xs text-fg-3">
              {[a.cooldown_minutes ? `auto-rearm ${a.cooldown_minutes >= 60 ? `${a.cooldown_minutes / 60} h` : `${a.cooldown_minutes} min`}` : null, a.quiet_start ? `quiet ${a.quiet_start}–${a.quiet_end}` : null].filter(Boolean).join(" · ")}
            </span>
          )}
        </span>
      ),
    },
    { key: "last", header: "Last observed", align: "right", render: (a) => lastObserved(a, tz) },
    { key: "dist", header: "Distance", align: "right", hideBelow: "lg", render: (a) => <span className="num text-fg-2">{distance(a) === null ? DASH : formatPercent(distance(a))}</span> },
    { key: "state", header: "State", render: (a) => <Pill tone={alertState(a).tone}>{alertState(a).label}</Pill> },
    {
      key: "eval",
      header: "Last evaluated",
      hideBelow: "xl",
      render: (a) => (
        <span className="inline-flex max-w-64 flex-col">
          <span className="text-xs text-fg-3">{a.last_evaluated_at ? formatRelative(a.last_evaluated_at) : "Not yet"}</span>
          {a.last_skip_reason && <span className="text-xs text-warn">{a.last_skip_reason}</span>}
        </span>
      ),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      render: (a) =>
        readOnly ? null : (
          <span className="inline-flex gap-0.5">
            {!a.active && (
              <Button size="sm" variant="ghost" icon={a.events.length ? <RotateCcw className="size-3.5" aria-hidden /> : <Play className="size-3.5" aria-hidden />} onClick={() => m.rearm.mutate(a.id, { onSuccess: () => toast("success", `Alert for ${a.symbol} rearmed.`), onError: (e) => toast("error", errorMessage(e)) })}>
                {a.events.length ? "Rearm" : "Resume"}
              </Button>
            )}
            {a.active && (
              <IconButton size="sm" label={`Pause alert for ${a.symbol}`} onClick={() => m.update.mutate({ id: a.id, patch: { active: false } })}>
                <Pause className="size-3.5" aria-hidden />
              </IconButton>
            )}
            <IconButton size="sm" label={`Edit alert for ${a.symbol}`} onClick={() => open({ kind: "alert", editing: a })}>
              <Pencil className="size-3.5" aria-hidden />
            </IconButton>
            <IconButton size="sm" label={`Delete alert for ${a.symbol}`} onClick={() => setDeleting(a)}>
              <Trash className="size-3.5" aria-hidden />
            </IconButton>
          </span>
        ),
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 p-4 md:p-6 lg:grid-cols-12 lg:gap-5">
      <Panel
        title="Alert rules"
        titleId="alerts-title"
        className="lg:col-span-8"
        bodyClassName="p-0"
        refreshing={alerts.isFetching && !alerts.isLoading}
        actions={!readOnly && <Button size="sm" variant="primary" icon={<Plus className="size-3.5" aria-hidden />} onClick={() => open({ kind: "alert" })}>New alert</Button>}
      >
        {alerts.isLoading ? (
          <SkeletonRows rows={4} className="p-4" />
        ) : alerts.isError ? (
          <ErrorState message={errorMessage(alerts.error)} onRetry={() => alerts.refetch()} />
        ) : !alerts.data!.length ? (
          <EmptyState icon={<Bell aria-hidden />} title="No alerts" actions={!readOnly && <Button variant="primary" onClick={() => open({ kind: "alert" })}>Create alert</Button>}>
            Watch a price level, a crossing, unusual volume or moves in completed sessions, or new SEC filings. The worker records each event once and shows it in your inbox.
          </EmptyState>
        ) : (
          <DataTable
            caption="Alert rules"
            columns={cols}
            rows={alerts.data!}
            rowKey={(a) => String(a.id)}
            mobileDetailKeys={["last", "dist", "eval", "actions"]}
            mobileSummary={(a) => (
              <div className="flex items-center gap-3">
                <div className="min-w-0 flex-1">
                  <div className="num text-[13px] font-semibold">{a.symbol}</div>
                  <div className="text-xs text-fg-2">{a.description}</div>
                </div>
                <Pill tone={alertState(a).tone}>{alertState(a).label}</Pill>
              </div>
            )}
          />
        )}
      </Panel>
      <div className="space-y-4 lg:col-span-4 lg:space-y-5">
        <WorkerPanel />
        <UpcomingResultsPanel />
      </div>
      <InboxPanel readOnly={readOnly} tz={tz} />
      {!readOnly && <InlineNotice className="lg:col-span-12">Only in-app notices are available. Email, Telegram and background push are not configured.</InlineNotice>}
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={`Delete alert for ${deleting?.symbol}?`}
        body="The alert and its triggered history are removed. This cannot be undone."
        confirmLabel="Delete alert"
        onConfirm={async () => {
          if (deleting) await m.remove.mutateAsync(deleting.id);
          toast("success", "Alert deleted.");
        }}
      />
    </div>
  );
}
