import { Bell, Pause, Pencil, Play, Plus, RotateCcw, SkipForward, Trash } from "lucide-react";
import { useState } from "react";
import { useDialogs } from "@/app/dialogs";
import { Panel } from "@/components/ui/Panel";
import { Button, IconButton } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { InstrumentBadge, Pill } from "@/components/ui/Badges";
import { EmptyState, ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { errorMessage, type Alert, type AlertEvent } from "@/lib/api/client";
import { DASH, formatInstant, formatMoney, formatPercent, formatRelative, formatSessionDate, toNumber } from "@/lib/format";
import { useFixture, useFixtureAction, usePrefs, useSession, useStatus } from "@/features/settings/api";
import { useAlertEvents, useAlertMutations, useAlerts } from "./api";

function WorkerPanel() {
  const { data: status } = useStatus();
  const { data: prefs } = usePrefs();
  const fixture = useFixture();
  const action = useFixtureAction();
  const { data: session } = useSession();
  const toast = useToast();
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
          </div>
        </div>
      )}
    </Panel>
  );
}

export function AlertsPage() {
  const alerts = useAlerts();
  const events = useAlertEvents(false);
  const { data: session } = useSession();
  const { data: prefs } = usePrefs();
  const { open } = useDialogs();
  const m = useAlertMutations();
  const toast = useToast();
  const [deleting, setDeleting] = useState<Alert | null>(null);
  const readOnly = Boolean(session?.read_only);
  const tz = prefs?.display_timezone;

  const distance = (a: Alert) => {
    const p = toNumber(a.last_observed_price);
    const t = toNumber(a.target_price);
    if (p === null || t === null || p === 0) return null;
    return ((t - p) / p) * 100;
  };

  const cols: Column<Alert>[] = [
    { key: "inst", header: "Instrument", render: (a) => <InstrumentBadge symbol={a.symbol} name={a.instrument.name} /> },
    { key: "cond", header: "Condition", render: (a) => <span className="text-fg">{a.direction === "ABOVE" ? "≥" : "≤"} <span className="num">{formatMoney(a.target_price, a.instrument.currency)}</span></span> },
    {
      key: "last",
      header: "Last observed",
      align: "right",
      render: (a) => (
        <span className="inline-flex flex-col items-end">
          <span className="num">{formatMoney(a.last_observed_price, a.instrument.currency)}</span>
          {a.last_observed_market_time && <span className="text-xs text-fg-3">{formatInstant(a.last_observed_market_time, tz)}</span>}
        </span>
      ),
    },
    { key: "dist", header: "Distance", align: "right", hideBelow: "lg", render: (a) => <span className="num text-fg-2">{distance(a) === null ? DASH : formatPercent(distance(a))}</span> },
    {
      key: "state",
      header: "State",
      render: (a) => <Pill tone={a.active ? "pos" : a.events.length && a.events[0].arm_seq === a.arm_seq ? "accent" : "neutral"}>{a.active ? "Armed" : a.events.length && a.events[0].arm_seq === a.arm_seq ? "Triggered" : "Paused"}</Pill>,
    },
    { key: "eval", header: "Last evaluated", hideBelow: "xl", render: (a) => <span className="text-xs text-fg-3">{a.last_evaluated_at ? formatRelative(a.last_evaluated_at) : "Not yet"}</span> },
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

  const evCols: Column<AlertEvent>[] = [
    { key: "t", header: "Detected", render: (e) => <span className="num text-fg-2">{formatInstant(e.triggered_at, tz)}</span> },
    { key: "s", header: "Instrument", render: (e) => <InstrumentBadge symbol={e.symbol} /> },
    { key: "c", header: "Condition", render: (e) => <span>{e.direction === "ABOVE" ? "≥" : "≤"} <span className="num">{formatMoney(e.target_price)}</span></span> },
    { key: "p", header: "Observed", align: "right", render: (e) => <span className="num">{formatMoney(e.observed_price)}</span> },
    { key: "m", header: "Market time", hideBelow: "lg", render: (e) => <span className="text-xs text-fg-3">{formatInstant(e.observed_market_time, tz)}</span> },
    { key: "r", header: "Status", render: (e) => (e.read_at ? <span className="text-xs text-fg-3">Read</span> : <Pill tone="accent">New</Pill>) },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 p-4 md:p-6 lg:grid-cols-12 lg:gap-5">
      <Panel
        title="Price alerts"
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
            Set a price level for any instrument. The worker records an event the first time it observes the price at or beyond your level.
          </EmptyState>
        ) : (
          <DataTable
            caption="Price alerts"
            columns={cols}
            rows={alerts.data!}
            rowKey={(a) => String(a.id)}
            mobileDetailKeys={["last", "dist", "eval", "actions"]}
            mobileSummary={(a) => (
              <div className="flex items-center gap-3">
                <div className="min-w-0 flex-1">
                  <div className="num text-[13px] font-semibold">{a.symbol}</div>
                  <div className="text-xs text-fg-2">{a.direction === "ABOVE" ? "At or above" : "At or below"} {formatMoney(a.target_price, a.instrument.currency)}</div>
                </div>
                <Pill tone={a.active ? "pos" : "neutral"}>{a.active ? "Armed" : a.events.length ? "Triggered" : "Paused"}</Pill>
              </div>
            )}
          />
        )}
      </Panel>
      <WorkerPanel />
      <Panel
        title="Triggered history"
        titleId="events-title"
        className="lg:col-span-12"
        bodyClassName="p-0"
        actions={!readOnly && events.data?.some((e) => !e.read_at) && <Button size="sm" variant="ghost" onClick={() => m.readAll.mutate()}>Mark all read</Button>}
      >
        {events.isLoading ? (
          <SkeletonRows rows={3} className="p-4" />
        ) : events.isError ? (
          <ErrorState message={errorMessage(events.error)} onRetry={() => events.refetch()} />
        ) : !events.data!.length ? (
          <p className="px-[var(--panel-pad)] py-6 text-center text-[13px] text-fg-3">No alert has triggered yet.</p>
        ) : (
          <DataTable caption="Triggered alert events" columns={evCols} rows={events.data!} rowKey={(e) => String(e.id)} mobileDetailKeys={["c", "m", "r"]}
            mobileSummary={(e) => (
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="num text-[13px] font-semibold">{e.symbol}</div>
                  <div className="text-xs text-fg-3">{formatInstant(e.triggered_at, tz)}</div>
                </div>
                <span className="num text-[13px]">{formatMoney(e.observed_price)}</span>
              </div>
            )}
          />
        )}
      </Panel>
      {!readOnly && <InlineNotice className="lg:col-span-12">Only in-app notifications are available. Email, Telegram and background push are not configured.</InlineNotice>}
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
