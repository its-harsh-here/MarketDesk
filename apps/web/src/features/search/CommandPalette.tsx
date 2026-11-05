import { listingLabel } from "@/lib/markets";
import * as RD from "@radix-ui/react-dialog";
import { Bell, BookOpen, Briefcase, CornerDownLeft, Download, FileUp, FlaskConical, Funnel, Gauge, Globe, Keyboard, LayoutDashboard, LayoutGrid, ListChecks, NotebookPen, Plus, Rows3, Search, Settings, SunMoon } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router";
import { useDialogs } from "@/app/dialogs";
import { useSymbolSearch } from "@/features/market/api";
import { applyDensity, applyTheme, usePatchPrefs, usePrefs, useSession } from "@/features/settings/api";
import { useWorkspaces } from "@/features/workspace/api";
import { useSwitchWorkspace } from "@/features/workspace/WorkspaceMenu";
import { useDebounced } from "@/lib/hooks";
import { cn } from "@/lib/cn";

interface Item {
  id: string;
  group: "Instruments" | "Pages" | "Actions";
  label: string;
  hint?: string;
  icon?: ReactNode;
  run: () => void;
  writes?: boolean;
}

export function CommandPalette() {
  const { state, open, close } = useDialogs();
  const isOpen = state.kind === "palette";
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const navigate = useNavigate();
  const debounced = useDebounced(q, 180);
  const search = useSymbolSearch(isOpen ? debounced : "");
  const { data: prefs } = usePrefs();
  const patch = usePatchPrefs();
  const { data: session } = useSession();
  const readOnly = Boolean(session?.read_only);
  const { data: ws } = useWorkspaces(isOpen);
  const switchTo = useSwitchWorkspace();
  const loc = useLocation();
  const here = loc.pathname.startsWith("/instrument/") ? decodeURIComponent(loc.pathname.slice("/instrument/".length)) : null;

  const go = (path: string) => () => {
    close();
    navigate(path);
  };

  const items = useMemo<Item[]>(() => {
    const ql = q.trim().toLowerCase();
    const pages: Item[] = [
      { id: "p-overview", group: "Pages", label: "Overview", icon: <LayoutDashboard />, run: go("/") },
      { id: "p-watch", group: "Pages", label: "Watchlists", icon: <ListChecks />, run: go("/watchlists") },
      { id: "p-screener", group: "Pages", label: "Screener", icon: <Funnel />, run: go("/screener") },
      { id: "p-macro", group: "Pages", label: "Macro", icon: <Globe />, run: go("/macro") },
      { id: "p-port", group: "Pages", label: "Portfolio", icon: <Briefcase />, run: go("/portfolio") },
      { id: "p-alerts", group: "Pages", label: "Alerts", icon: <Bell />, run: go("/alerts") },
      { id: "p-journal", group: "Pages", label: "Journal", icon: <BookOpen />, run: go("/journal") },
      { id: "p-lab", group: "Pages", label: "Research lab", icon: <FlaskConical />, run: go("/lab") },
      { id: "p-settings", group: "Pages", label: "Settings", icon: <Settings />, run: go("/settings") },
      { id: "p-usage", group: "Pages", label: "Usage, quotas and refresh", icon: <Gauge />, run: go("/settings?s=usage") },
      { id: "p-workspaces", group: "Pages", label: "Manage workspaces", icon: <LayoutGrid />, run: go("/settings?s=workspaces") },
    ];
    const actions: Item[] = [
      { id: "a-txn", group: "Actions", label: "Add transaction", icon: <Plus />, writes: true, run: () => open({ kind: "transaction" }) },
      { id: "a-import", group: "Actions", label: "Import transactions CSV", icon: <FileUp />, writes: true, run: () => open({ kind: "import" }) },
      { id: "a-alert", group: "Actions", label: "Create price alert", icon: <Bell />, writes: true, run: () => open({ kind: "alert" }) },
      { id: "a-journal", group: "Actions", label: "New journal note", icon: <NotebookPen />, writes: true, run: () => open({ kind: "journal" }) },
      { id: "a-wl", group: "Actions", label: "New watchlist", icon: <ListChecks />, writes: true, run: () => open({ kind: "new-watchlist" }) },
      {
        id: "a-theme",
        group: "Actions",
        label: `Switch to ${prefs?.theme === "light" ? "dark" : "light"} theme`,
        icon: <SunMoon />,
        run: () => {
          const next = prefs?.theme === "light" ? "dark" : "light";
          applyTheme(next);
          if (!readOnly) patch.mutate({ theme: next });
          close();
        },
      },
      {
        id: "a-density",
        group: "Actions",
        label: `Switch to ${prefs?.density === "compact" ? "comfortable" : "compact"} density`,
        icon: <Rows3 />,
        run: () => {
          const next = prefs?.density === "compact" ? "comfortable" : "compact";
          applyDensity(next);
          if (!readOnly) patch.mutate({ density: next });
          close();
        },
      },
      ...(ws?.items ?? []).map((w) => ({
        id: `a-ws-${w.id}`,
        group: "Actions" as const,
        label: `Workspace: ${w.name}${w.id === ws?.active ? " (active)" : ""}`,
        icon: <LayoutGrid />,
        writes: true,
        run: () => {
          close();
          switchTo(w.id);
        },
      })),
      ...(here ? [{ id: "a-export", group: "Actions" as const, label: `Export research for ${here}`, icon: <Download />, run: () => open({ kind: "export", symbol: here }) }] : []),
      { id: "a-keys", group: "Actions", label: "Keyboard shortcuts", icon: <Keyboard />, run: () => open({ kind: "shortcuts" }) },
    ].filter((a) => !(readOnly && a.writes)) as Item[];
    const match = (i: Item) => !ql || i.label.toLowerCase().includes(ql);
    const instruments: Item[] = ql
      ? (search.data?.results ?? []).map((r) => ({
          id: `i-${r.symbol}`,
          group: "Instruments" as const,
          label: r.symbol,
          hint: [r.name, listingLabel(r)].filter(Boolean).join(" · "),
          run: go(`/instrument/${encodeURIComponent(r.symbol)}`),
        }))
      : [];
    return [...instruments, ...pages.filter(match), ...actions.filter(match)];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, search.data, prefs?.theme, prefs?.density, readOnly, ws, here]);

  const groups = ["Instruments", "Pages", "Actions"] as const;
  const safeActive = Math.min(active, Math.max(items.length - 1, 0));

  return (
    <RD.Root
      open={isOpen}
      onOpenChange={(o) => {
        if (!o) close();
        setQ("");
        setActive(0);
      }}
    >
      <RD.Portal>
        <RD.Overlay className="anim-overlay fixed inset-0 z-40 bg-[var(--overlay)]" />
        <RD.Content
          aria-label="Command palette"
          className="anim-pop fixed top-[12vh] left-1/2 z-50 w-[min(640px,calc(100vw-24px))] -translate-x-1/2 overflow-hidden rounded-[var(--radius-panel)] border border-line bg-panel shadow-[var(--shadow-pop)]"
        >
          <RD.Title className="sr-only">Command palette</RD.Title>
          <RD.Description className="sr-only">Search instruments by name or symbol, jump to a page, or run an action.</RD.Description>
          <div className="flex items-center gap-3 border-b border-line-subtle px-4">
            <Search aria-hidden className="size-4 text-fg-3" />
            <input
              autoFocus
              role="combobox"
              aria-expanded
              aria-controls="palette-list"
              aria-activedescendant={items[safeActive] ? `pal-${items[safeActive].id}` : undefined}
              aria-label="Search instruments, pages and actions"
              placeholder="Search company, symbol, page or action…"
              className="h-13 flex-1 bg-transparent text-[15px] text-fg placeholder:text-fg-3 focus:outline-none"
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setActive(0);
              }}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setActive((a) => Math.min(a + 1, items.length - 1));
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setActive((a) => Math.max(a - 1, 0));
                } else if (e.key === "Enter") {
                  e.preventDefault();
                  items[safeActive]?.run();
                }
              }}
            />
            {search.isFetching && <span className="text-xs text-fg-3" role="status">Searching…</span>}
          </div>
          <ul id="palette-list" role="listbox" aria-label="Results" className="scrollbar-thin max-h-[min(420px,60vh)] overflow-y-auto py-2">
            {items.length === 0 && (
              <li className="px-4 py-6 text-center text-[13px] text-fg-3">
                {q && search.data?.meta?.message ? search.data.meta.message : "No matches."}
              </li>
            )}
            {groups.map((g) => {
              const groupItems = items.filter((i) => i.group === g);
              if (!groupItems.length) return null;
              return (
                <li key={g} role="presentation">
                  <div className="px-4 pt-2 pb-1 text-[11px] font-semibold tracking-wider text-fg-3 uppercase">{g}</div>
                  <ul role="presentation">
                    {groupItems.map((it) => {
                      const idx = items.indexOf(it);
                      return (
                        <li
                          key={it.id}
                          id={`pal-${it.id}`}
                          role="option"
                          aria-selected={idx === safeActive}
                          onMouseEnter={() => setActive(idx)}
                          onClick={() => it.run()}
                          className={cn(
                            "mx-2 flex cursor-pointer items-center gap-3 rounded-md px-2.5 py-2 text-[13px]",
                            idx === safeActive ? "bg-hover text-fg" : "text-fg-2",
                          )}
                        >
                          {it.icon && <span className="text-fg-3 [&_svg]:size-4">{it.icon}</span>}
                          <span className={cn("shrink-0", it.group === "Instruments" && "num font-semibold text-fg")}>{it.label}</span>
                          {it.hint && <span className="min-w-0 truncate text-fg-3">{it.hint}</span>}
                          {idx === safeActive && <CornerDownLeft aria-hidden className="ml-auto size-3.5 text-fg-3" />}
                        </li>
                      );
                    })}
                  </ul>
                </li>
              );
            })}
          </ul>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line-subtle px-4 py-2 text-[11px] text-fg-3">
            <span><Kbd>↑</Kbd> <Kbd>↓</Kbd> navigate</span>
            <span><Kbd>Enter</Kbd> open</span>
            <span><Kbd>Esc</Kbd> close</span>
          </div>
        </RD.Content>
      </RD.Portal>
    </RD.Root>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="num inline-flex min-w-5 items-center justify-center rounded border border-line bg-elevated px-1 text-[11px] leading-4 text-fg-2">{children}</kbd>;
}
