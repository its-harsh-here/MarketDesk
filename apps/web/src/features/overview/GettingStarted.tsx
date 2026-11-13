import { CheckCircle2, Circle, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { useDialogs } from "@/app/dialogs";
import { Button, IconButton } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Panel";
import { useAlerts } from "@/features/alerts/api";
import { useTransactions } from "@/features/portfolio/api";
import { useWatchlists } from "@/features/watchlists/api";
import { cn } from "@/lib/cn";

const KEY = "md-getting-started-dismissed";

/** First-run checklist built from real data: it ticks itself off and disappears once everything is done. */
export function GettingStarted() {
  const { open } = useDialogs();
  const lists = useWatchlists();
  const txns = useTransactions({});
  const alerts = useAlerts();
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem(KEY) === "1";
    } catch {
      return false;
    }
  });
  if (dismissed || lists.isLoading || txns.isLoading || alerts.isLoading) return null;
  const hasSymbols = (lists.data ?? []).some((w) => w.items.length > 0);
  const firstList = lists.data?.[0];
  const steps = [
    {
      done: hasSymbols,
      title: "Build a watchlist",
      text: "Follow the companies you research; prices, changes and trends appear on the Overview.",
      action: firstList ? (
        <Button size="sm" onClick={() => open({ kind: "add-symbol", watchlistId: firstList.id })}>Add symbol</Button>
      ) : (
        <Link to="/watchlists" className="text-[13px] text-accent-text hover:underline">Create a watchlist</Link>
      ),
    },
    {
      done: (txns.data?.total ?? 0) > 0,
      title: "Record your holdings",
      text: "Add a deposit and trades, or import a broker's trade export; holdings, cash and P&L follow.",
      action: (
        <span className="flex gap-2">
          <Button size="sm" onClick={() => open({ kind: "transaction" })}>Add transaction</Button>
          <Button size="sm" variant="ghost" onClick={() => open({ kind: "import" })}>Import CSV</Button>
        </span>
      ),
    },
    {
      done: (alerts.data ?? []).length > 0,
      title: "Set an alert",
      text: "Price, volume, filing and earnings rules arrive in the inbox (and on this device when enabled).",
      action: <Button size="sm" onClick={() => open({ kind: "alert" })}>Create alert</Button>,
    },
  ];
  const left = steps.filter((s) => !s.done).length;
  if (left === 0) return null;
  const dismiss = () => {
    setDismissed(true);
    try {
      localStorage.setItem(KEY, "1");
    } catch {
      /* per-browser convenience only */
    }
  };
  return (
    <Panel title="Getting started" titleId="gs-title" className="lg:col-span-12" meta={`${steps.length - left} of ${steps.length} done`}
      actions={<IconButton size="sm" label="Hide getting started" onClick={dismiss}><X className="size-4" aria-hidden /></IconButton>}>
      <ol className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {steps.map((s) => (
          <li key={s.title} className={cn("fx-tilt flex gap-3 rounded-[var(--radius-control)] border border-line-subtle p-3", s.done && "opacity-60")}>
            {s.done ? <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-pos" aria-label="Done" /> : <Circle className="mt-0.5 size-5 shrink-0 text-fg-3" aria-label="To do" />}
            <div className="min-w-0 space-y-1.5">
              <div className="text-[14px] font-medium text-fg">{s.title}</div>
              <p className="text-xs leading-4 text-fg-3">{s.text}</p>
              {!s.done && s.action}
            </div>
          </li>
        ))}
      </ol>
    </Panel>
  );
}
