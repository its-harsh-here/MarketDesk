import * as DM from "@radix-ui/react-dropdown-menu";
import * as RD from "@radix-ui/react-dialog";
import { Bell, BookOpen, Flame, LayoutGrid, Briefcase, Ellipsis, FlaskConical, Funnel, Globe, Keyboard, LayoutDashboard, ListChecks, LogOut, Moon, Search, Settings, Sun, UserRound } from "lucide-react";
import { useEffect, useId, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { useDialogs } from "./dialogs";
import { MOD } from "@/features/search/ShortcutsDialog";
import { useAlertMutations, useInbox, useInboxCounts } from "@/features/alerts/api";
import { applyTheme, usePatchPrefs, usePrefs, useSession, useStatus } from "@/features/settings/api";
import { useBenchmarks, useSessions } from "@/features/market/api";
import { REGION_LABEL, sessionText } from "@/lib/markets";
import { ChangeText } from "@/components/ui/Change";
import { FreshnessBadge, Pill } from "@/components/ui/Badges";
import { Tooltip } from "@/components/ui/Tooltip";
import { IconButton } from "@/components/ui/Button";
import { api } from "@/lib/api/client";
import { formatInstant, formatMoney, formatRelative, formatSessionDate } from "@/lib/format";
import { isTypingTarget, useGlobalKeys } from "@/lib/hooks";
import { cn } from "@/lib/cn";
import { usePageEnter, withReveal } from "@/lib/fx";
import { useSwitchWorkspace, WorkspaceMenu } from "@/features/workspace/WorkspaceMenu";
import { useWorkspaces } from "@/features/workspace/api";
import { OfflineBanner } from "@/features/workspace/OfflineView";
import { clearOffline, syncSnapshot } from "@/lib/offline";
import { clearRecents } from "@/lib/recent";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/watchlists", label: "Watchlists", icon: ListChecks },
  { to: "/screener", label: "Screener", icon: Funnel },
  { to: "/movers", label: "Movers", icon: Flame },
  { to: "/desk", label: "Desk", icon: LayoutGrid },
  { to: "/macro", label: "Macro", icon: Globe },
  { to: "/portfolio", label: "Portfolio", icon: Briefcase },
  { to: "/alerts", label: "Alerts", icon: Bell },
  { to: "/journal", label: "Journal", icon: BookOpen },
  { to: "/lab", label: "Lab", icon: FlaskConical },
];

function Logo({ compact }: { compact?: boolean }) {
  const gid = useId(); // two logos exist (sidebar and phone header); a gradient inside a hidden svg does not paint
  return (
    <Link to="/" className="md-logo flex items-center gap-2.5 rounded-md" aria-label="MarketDesk overview">
      <svg viewBox="0 0 32 32" className="md-logo-mark size-7 shrink-0" aria-hidden>
        <defs>
          <linearGradient id={gid} x1="0" y1="1" x2="1" y2="0">
            <stop offset="0" stopColor="var(--accent)" />
            <stop offset="1" stopColor="var(--accent-2)" />
          </linearGradient>
        </defs>
        <rect width="32" height="32" rx="9" fill="var(--elevated)" stroke={`url(#${gid})`} strokeOpacity="0.6" />
        <path d="M7 21.5 12.5 15l4 3.5L25 9.5" fill="none" stroke={`url(#${gid})`} strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="25" cy="9.5" r="1.6" fill="var(--accent-2)" />
      </svg>
      {!compact && <span className="md-title md-fade text-[15px] font-semibold tracking-tight">MarketDesk</span>}
    </Link>
  );
}

/** Icon rail that expands over the page on hover or keyboard focus (labels fade in); 64px in the layout. */
function Sidebar() {
  const { data: status } = useStatus();
  // Opens when the pointer moves onto the rail (after a short intent delay), not because a page loaded under a
  // resting cursor; keyboard focus opens it through CSS (:focus-within).
  const [open, setOpen] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const enter = (e: ReactPointerEvent) => {
    if (e.pointerType !== "mouse") return; // touch: a tap navigates, no hover state
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(true), 90);
  };
  const leave = () => {
    window.clearTimeout(timer.current);
    setOpen(false);
  };
  const item = "md-nav group flex h-10 items-center gap-3 rounded-[var(--radius-control)] px-4 text-[13px] font-medium";
  return (
    <div className="relative hidden w-16 shrink-0 md:block">
      <nav aria-label="Primary" data-open={open || undefined} onPointerEnter={enter} onPointerLeave={leave}
        className="md-sidebar md-rail fixed top-0 left-0 z-40 flex h-dvh flex-col overflow-hidden border-r border-line-subtle">
        <div className="flex h-16 items-center px-[18px]">
          <Logo />
        </div>
        <ul className="flex flex-col gap-0.5 px-2 pt-2">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <li key={to}>
              <NavLink
                to={to}
                end={end}
                title={label}
                className={({ isActive }) => cn(item, isActive ? "text-fg" : "text-fg-2 hover:bg-hover/60 hover:text-fg")}
              >
                {({ isActive }) => (
                  <>
                    <Icon aria-hidden className={cn("size-4 shrink-0", isActive ? "text-accent-text" : "text-fg-3 group-hover:text-fg-2")} />
                    <span className="md-fade">{label}</span>
                  </>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
        <div className="mt-auto space-y-1 px-2 pb-4">
          <NavLink
            to="/settings"
            title="Settings"
            className={({ isActive }) => cn(item, isActive ? "text-fg" : "text-fg-2 hover:bg-hover/60 hover:text-fg")}
          >
            <Settings aria-hidden className="size-4 shrink-0 text-fg-3" />
            <span className="md-fade">Settings</span>
          </NavLink>
          {status && (
            <div className="md-fade w-48 px-4 pt-2 text-[11px] leading-4 !whitespace-normal text-fg-3">
              {status.sample_data ? "Synthetic test harness" : "Data: Yahoo Finance via yfinance"}
              <br />v{status.version}
            </div>
          )}
        </div>
      </nav>
    </div>
  );
}

function ProviderStatus() {
  const { data: status } = useStatus();
  const { data: prefs } = usePrefs();
  if (!status) return <span className="skeleton h-6 w-28" />;
  const h = status.provider_health as { circuit?: string; last_error?: { message?: string } | null };
  if (status.sample_data) {
    return (
      <Tooltip content={<span>{status.dataset_disclaimer} Dataset date {formatSessionDate(status.dataset_date)}. Prices never update to the present.</span>}>
        <button type="button" className="inline-flex" aria-label={`Sample data, dataset date ${formatSessionDate(status.dataset_date)}`}>
          <Pill tone="info" className="gap-1.5">
            <span className="fx-live size-1.5 rounded-full bg-info" aria-hidden />
            Sample data
            <span className="num font-normal text-fg-2 max-sm:hidden">· {formatSessionDate(status.dataset_date)}</span>
          </Pill>
        </button>
      </Tooltip>
    );
  }
  const degraded = h.circuit && h.circuit !== "closed";
  return (
    <Tooltip
      content={
        <span>
          Yahoo Finance via yfinance (unofficial). {status.market_status}.{" "}
          {degraded ? `Provider requests paused after failures: ${h.last_error?.message ?? ""}` : "Provider reachable at last request."}
          {status.worker.last_cycle_at && ` Worker last ran ${formatInstant(status.worker.last_cycle_at, prefs?.display_timezone)}.`}
        </span>
      }
    >
      <button type="button" className="inline-flex" aria-label="Provider status">
        <Pill tone={degraded ? "warn" : "neutral"} className="gap-1.5">
          <span className={cn("fx-live size-1.5 rounded-full", degraded ? "bg-warn" : "bg-pos")} aria-hidden />
          Yahoo
          <span className="font-normal text-fg-3 max-sm:hidden">· {degraded ? "degraded" : "connected"}</span>
        </Pill>
      </button>
    </Tooltip>
  );
}

function NotificationsMenu() {
  const { data: unread } = useInbox({ unread: true }, 6);
  const { data: counts } = useInboxCounts();
  const { read } = useAlertMutations();
  const navigate = useNavigate();
  const { data: session } = useSession();
  const count = counts?.total ?? 0;
  return (
    <DM.Root>
      <DM.Trigger asChild>
        <IconButton label={count ? `Inbox: ${count} unread` : "Inbox"} className="relative">
          <Bell className="size-4" aria-hidden />
          {count > 0 && (
            <span className="num absolute top-1 right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-bold text-accent-fg">{count > 99 ? "99+" : count}</span>
          )}
        </IconButton>
      </DM.Trigger>
      <DM.Portal>
        <DM.Content align="end" sideOffset={6} className="anim-pop z-50 w-80 rounded-[var(--radius-control)] border border-line bg-elevated p-1 shadow-[var(--shadow-pop)]">
          <div className="flex items-center justify-between px-2.5 py-2">
            <span className="text-[13px] font-semibold">Inbox</span>
            {count > 0 && !session?.read_only && (
              <button type="button" className="text-xs text-accent-text hover:underline" onClick={() => read.mutate(undefined)}>
                Mark all read
              </button>
            )}
          </div>
          {count === 0 && <p className="px-2.5 pb-3 text-[13px] text-fg-3">Nothing unread. Alerts and briefings are written by the worker process.</p>}
          {unread?.map((it) => (
            <DM.Item key={`${it.type}-${it.id}`} onSelect={() => navigate("/alerts")} className="cursor-pointer rounded-md px-2.5 py-2 text-[13px] outline-none data-[highlighted]:bg-hover">
              <div className="font-semibold text-fg">{it.title}</div>
              <div className="line-clamp-2 text-fg-2">
                {it.alert?.explanation ?? it.briefing?.items.find((x) => x.kind === "move")?.text ?? it.briefing?.items[0]?.text}
              </div>
              <div className="num mt-0.5 text-xs text-fg-3">{formatRelative(it.at)}</div>
            </DM.Item>
          ))}
          <DM.Separator className="my-1 h-px bg-line-subtle" />
          <DM.Item onSelect={() => navigate("/alerts")} className="cursor-pointer rounded-md px-2.5 py-2 text-[13px] text-fg-2 outline-none data-[highlighted]:bg-hover">
            Open inbox
          </DM.Item>
        </DM.Content>
      </DM.Portal>
    </DM.Root>
  );
}

function UserMenu() {
  const { data: session } = useSession();
  const { data: prefs } = usePrefs();
  const patch = usePatchPrefs();
  const { open } = useDialogs();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const isLight = prefs?.theme === "light";
  const item = "flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-[13px] text-fg-2 outline-none data-[highlighted]:bg-hover data-[highlighted]:text-fg";
  return (
    <DM.Root>
      <DM.Trigger asChild>
        <IconButton label="Account and settings menu">
          <UserRound className="size-4" aria-hidden />
        </IconButton>
      </DM.Trigger>
      <DM.Portal>
        <DM.Content align="end" sideOffset={6} className="anim-pop z-50 w-60 rounded-[var(--radius-control)] border border-line bg-elevated p-1 shadow-[var(--shadow-pop)]">
          <div className="px-2.5 py-2 text-xs text-fg-3">
            {session?.mode === "dev_bypass" ? "Local development (auth bypass)" : `Signed in as ${session?.username}`}
          </div>
          <DM.Item
            className={item}
            onSelect={() => {
              const next = isLight ? "dark" : "light";
              withReveal(() => applyTheme(next));
              if (!session?.read_only) patch.mutate({ theme: next });
            }}
          >
            {isLight ? <Moon className="size-4" aria-hidden /> : <Sun className="size-4" aria-hidden />}
            {isLight ? "Dark theme" : "Light theme"}
          </DM.Item>
          <DM.Item className={item} onSelect={() => open({ kind: "shortcuts" })}>
            <Keyboard className="size-4" aria-hidden /> Keyboard shortcuts
          </DM.Item>
          <DM.Item className={item} onSelect={() => navigate("/settings")}>
            <Settings className="size-4" aria-hidden /> Settings
          </DM.Item>
          {session?.mode === "owner" && (
            <DM.Item
              className={item}
              onSelect={async () => {
                await api.post("/api/auth/logout").catch(() => undefined);
                clearOffline();
                clearRecents();
                qc.clear();
                window.location.assign("/");
              }}
            >
              <LogOut className="size-4" aria-hidden /> Sign out
            </DM.Item>
          )}
        </DM.Content>
      </DM.Portal>
    </DM.Root>
  );
}

function Topbar() {
  const { open } = useDialogs();
  const loc = useLocation();
  const title = NAV.find((n) => (n.end ? loc.pathname === n.to : loc.pathname.startsWith(n.to)))?.label ??
    (loc.pathname.startsWith("/instrument") ? "Instrument" : loc.pathname.startsWith("/settings") ? "Settings" : "");
  return (
    <header className="md-topbar safe-top sticky top-0 z-30 border-b border-line-subtle">
      <div className="flex h-14 items-center gap-2 px-4 md:h-16 md:gap-3 md:px-6">
        <span className="md:hidden"><Logo compact /></span>
        <div className="min-w-0 shrink-0 max-md:hidden">
          <WorkspaceMenu />
          <div key={title} className="fx-reveal truncate text-[15px] font-semibold text-fg">{title}</div>
        </div>
        <button
          type="button"
          onClick={() => open({ kind: "palette" })}
          className="md-search mx-auto flex h-9 w-full max-w-md min-w-0 items-center gap-2.5 rounded-full border border-line-subtle px-4 text-[13px] text-fg-3 hover:text-fg-2 max-md:h-10"
          aria-label={`Search symbols, pages and actions (${MOD}+K)`}
        >
          <Search aria-hidden className="size-4 shrink-0" />
          <span className="truncate">Search symbol, company or action</span>
          <kbd className="num ml-auto shrink-0 rounded border border-line px-1.5 text-[11px] text-fg-3 max-sm:hidden">{MOD} K</kbd>
        </button>
        <div className="flex shrink-0 items-center gap-1 md:gap-2">
          <ProviderStatus />
          <NotificationsMenu />
          <span className="max-md:hidden"><UserMenu /></span>
        </div>
      </div>
    </header>
  );
}

export function MarketStrip() {
  const { data, isLoading, isError } = useBenchmarks();
  return (
    <div className="md-strip scrollbar-thin relative flex items-stretch gap-0 overflow-x-auto border-b border-line-subtle px-4 md:px-6" aria-label="Market benchmarks" role="region">
      {isLoading && <div className="flex h-11 items-center gap-6">{[0, 1, 2].map((i) => <span key={i} className="skeleton h-4 w-40" />)}</div>}
      {isError && <div className="flex h-11 items-center text-xs text-fg-3">Benchmarks unavailable.</div>}
      <SessionPills />
      {data?.map((s) => (
        <Link
          key={s.symbol}
          to={`/instrument/${encodeURIComponent(s.symbol)}`}
          className="flex h-11 shrink-0 items-center gap-2.5 border-r border-line-subtle pr-5 pl-0 text-[13px] last:border-r-0 [&:not(:first-child)]:pl-5"
        >
          <span className="max-w-52 truncate text-fg-2">{s.instrument.name ?? s.symbol}</span>
          <span className="num font-medium text-fg">{s.quote ? formatMoney(s.quote.last_price, null) : "—"}</span>
          {s.quote ? <ChangeText percent={s.quote.change_percent} className="text-xs" /> : <span className="text-xs text-fg-3">{s.meta.message ?? "No quote"}</span>}
          <FreshnessBadge meta={s.meta} compact />
        </Link>
      ))}
    </div>
  );
}

/** Exchange schedule state per market, from published calendars (not a live exchange feed). */
function SessionPills() {
  const { data } = useSessions();
  if (!data?.length) return null;
  return (
    <div className="flex h-11 shrink-0 items-center gap-3 border-r border-line-subtle pr-5 text-xs" aria-label="Market sessions">
      {data.map((m) => (
        <span key={m.market} className="flex items-center gap-1.5 whitespace-nowrap" title={`${m.name}: ${sessionText(m)}. Source: ${m.source} calendar.`}>
          <span
            aria-hidden
            className={cn("size-1.5 rounded-full", m.state === "open" ? "fx-live bg-pos" : m.state === "closed" ? "bg-fg-3" : "bg-warn")}
          />
          <span className="text-fg-2">{REGION_LABEL[m.market] ?? m.market}</span>
          <span className={cn(m.state === "open" ? "text-pos" : m.state === "closed" ? "text-fg-3" : "text-warn")}>
            {m.state === "open" ? "open" : m.state === "closed" ? "closed" : "status unknown"}
          </span>
          <span className="sr-only">: {sessionText(m)}</span>
        </span>
      ))}
    </div>
  );
}

function BottomNav() {
  const items = NAV.filter((n) => ["/", "/watchlists", "/portfolio"].includes(n.to));
  return (
    <nav aria-label="Primary" className="md-bottomnav md-sidebar safe-bottom fixed inset-x-0 bottom-0 z-30 border-t border-line-subtle md:hidden">
      <ul className="grid grid-cols-4">
        {items.map(({ to, label, icon: Icon, end }) => (
          <li key={to}>
            <NavLink to={to} end={end} className={({ isActive }) => cn("flex h-14 flex-col items-center justify-center gap-1 text-[11px] font-medium", isActive ? "text-accent-text" : "text-fg-3")}>
              <Icon aria-hidden className="size-5" />
              {label}
            </NavLink>
          </li>
        ))}
        <li>
          <MoreSheet />
        </li>
      </ul>
    </nav>
  );
}

function MoreSheet() {
  const closeRef = useRef<HTMLButtonElement>(null);
  const loc = useLocation();
  const active = ["/screener", "/movers", "/desk", "/macro", "/alerts", "/journal", "/lab", "/settings"].some((p) => loc.pathname.startsWith(p));
  const { data: prefs } = usePrefs();
  const patch = usePatchPrefs();
  const { data: session } = useSession();
  const { open } = useDialogs();
  const { data: ws } = useWorkspaces();
  const switchTo = useSwitchWorkspace();
  const links: { to: string; label: string; icon: ReactNode }[] = [
    { to: "/screener", label: "Screener", icon: <Funnel className="size-5" aria-hidden /> },
    { to: "/movers", label: "Movers", icon: <Flame className="size-5" aria-hidden /> },
    { to: "/desk", label: "Desk", icon: <LayoutGrid className="size-5" aria-hidden /> },
    { to: "/macro", label: "Macro", icon: <Globe className="size-5" aria-hidden /> },
    { to: "/alerts", label: "Alerts", icon: <Bell className="size-5" aria-hidden /> },
    { to: "/journal", label: "Journal", icon: <BookOpen className="size-5" aria-hidden /> },
    { to: "/lab", label: "Lab", icon: <FlaskConical className="size-5" aria-hidden /> },
    { to: "/settings", label: "Settings", icon: <Settings className="size-5" aria-hidden /> },
  ];
  return (
    <RD.Root>
      <RD.Trigger className={cn("flex h-14 w-full flex-col items-center justify-center gap-1 text-[11px] font-medium", active ? "text-accent-text" : "text-fg-3")}>
        <Ellipsis aria-hidden className="size-5" />
        More
      </RD.Trigger>
      <RD.Portal>
        <RD.Overlay className="anim-overlay fixed inset-0 z-40 bg-[var(--overlay)]" />
        <RD.Content className="anim-pop safe-bottom fixed inset-x-0 bottom-0 z-50 rounded-t-2xl border border-line bg-panel p-3">
          <RD.Title className="px-2 pt-1 pb-2 text-sm font-semibold">More</RD.Title>
          <RD.Description className="sr-only">Other sections and preferences</RD.Description>
          <ul className="space-y-1">
            {links.map((l) => (
              <li key={l.to}>
                <RD.Close asChild>
                  <NavLink to={l.to} className={({ isActive }) => cn("flex h-12 items-center gap-3 rounded-lg px-3 text-[15px]", isActive ? "bg-elevated text-fg" : "text-fg-2")}>
                    {l.icon}
                    {l.label}
                  </NavLink>
                </RD.Close>
              </li>
            ))}
            <li>
              <button
                type="button"
                className="flex h-12 w-full items-center gap-3 rounded-lg px-3 text-[15px] text-fg-2"
                onClick={() => {
                  const next = prefs?.theme === "light" ? "dark" : "light";
                  withReveal(() => applyTheme(next));
                  if (!session?.read_only) patch.mutate({ theme: next });
                }}
              >
                {prefs?.theme === "light" ? <Moon className="size-5" aria-hidden /> : <Sun className="size-5" aria-hidden />}
                {prefs?.theme === "light" ? "Dark theme" : "Light theme"}
              </button>
            </li>
            <li>
              <RD.Close asChild>
                <button type="button" className="flex h-12 w-full items-center gap-3 rounded-lg px-3 text-[15px] text-fg-2" onClick={() => open({ kind: "palette" })}>
                  <Search className="size-5" aria-hidden /> Search
                </button>
              </RD.Close>
            </li>
          </ul>
          {ws && ws.items.length > 0 && (
            <div className="mt-2 border-t border-line-subtle pt-2">
              <div className="px-3 pb-1 text-xs text-fg-3">Workspace</div>
              <div className="flex flex-wrap gap-2 px-2">
                {ws.items.map((w) => (
                  <RD.Close asChild key={w.id}>
                    <button
                      type="button"
                      disabled={session?.read_only}
                      aria-pressed={w.id === ws.active}
                      onClick={() => switchTo(w.id)}
                      className={cn("h-11 rounded-lg border px-3 text-[14px]", w.id === ws.active ? "border-accent bg-elevated text-fg" : "border-line text-fg-2")}
                    >
                      {w.name}
                    </button>
                  </RD.Close>
                ))}
              </div>
            </div>
          )}
          <RD.Close ref={closeRef} className="mt-2 h-11 w-full rounded-lg border border-line text-sm text-fg-2">
            Close
          </RD.Close>
        </RD.Content>
      </RD.Portal>
    </RD.Root>
  );
}

/** Keeps this device's opt-in offline copy current (every 10 minutes while visible and online). */
function useOfflineSync() {
  const { data: prefs } = usePrefs();
  const tz = prefs?.display_timezone;
  useEffect(() => {
    if (!tz) return;
    const run = () => {
      if (!document.hidden && navigator.onLine) syncSnapshot(tz).catch(() => undefined);
    };
    run();
    const t = window.setInterval(run, 10 * 60_000);
    return () => window.clearInterval(t);
  }, [tz]);
}

export function Shell() {
  useOfflineSync();
  const { open, state } = useDialogs();
  const navigate = useNavigate();
  const gPending = useRef<number | null>(null);
  const { data: session } = useSession();
  const mainRef = usePageEnter<HTMLElement>(useLocation().pathname);

  useGlobalKeys((e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === "k") {
      e.preventDefault();
      open({ kind: state.kind === "palette" ? "none" : "palette" });
      return;
    }
    if (isTypingTarget(e.target) || mod || e.altKey || state.kind !== "none") return;
    if (e.key === "/") {
      e.preventDefault();
      open({ kind: "palette" });
    } else if (e.key === "?") {
      e.preventDefault();
      open({ kind: "shortcuts" });
    } else if (e.key.toLowerCase() === "n" && !session?.read_only) {
      e.preventDefault();
      open({ kind: "transaction" });
    } else if (e.key.toLowerCase() === "g") {
      gPending.current = window.setTimeout(() => (gPending.current = null), 900);
    } else if (gPending.current) {
      const map: Record<string, string> = { d: "/desk", v: "/movers", o: "/", w: "/watchlists", f: "/screener", m: "/macro", p: "/portfolio", a: "/alerts", j: "/journal", l: "/lab", s: "/settings" };
      const to = map[e.key.toLowerCase()];
      window.clearTimeout(gPending.current);
      gPending.current = null;
      if (to) navigate(to);
    }
  });

  return (
    <div className="flex min-h-dvh">
      <a href="#main" className="sr-only z-50 rounded bg-accent px-3 py-2 text-accent-fg focus:not-sr-only focus:fixed focus:top-2 focus:left-2">
        Skip to content
      </a>
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <OfflineBanner />
        <main id="main" ref={mainRef} className="min-w-0 flex-1 pb-24 md:pb-8">
          <Outlet />
        </main>
      </div>
      <BottomNav />
    </div>
  );
}
