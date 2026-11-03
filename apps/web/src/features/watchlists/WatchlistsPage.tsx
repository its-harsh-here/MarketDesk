import * as DM from "@radix-ui/react-dropdown-menu";
import { ArrowDown, ArrowUp, Ellipsis, ListChecks, Pencil, Plus, Sparkles, Trash } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { useDialogs } from "@/app/dialogs";
import { Panel } from "@/components/ui/Panel";
import { Button, IconButton } from "@/components/ui/Button";
import { ConfirmDialog, Dialog } from "@/components/ui/Dialog";
import { Field, Input } from "@/components/ui/Form";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import type { SortState } from "@/components/ui/DataTable";
import { errorMessage, type ApiError, type Snapshot, type Watchlist } from "@/lib/api/client";
import { cn } from "@/lib/cn";
import { useSnapshots } from "@/features/market/api";
import { usePatchPrefs, usePrefs, useSession, useStatus } from "@/features/settings/api";
import { SymbolPicker } from "@/features/search/SymbolPicker";
import { useWatchlistMutations, useWatchlists } from "./api";
import { WatchlistTable, buildRows } from "./WatchlistTable";

export function NewWatchlistDialog() {
  const { state, close } = useDialogs();
  const { create } = useWatchlistMutations();
  const patch = usePatchPrefs();
  const toast = useToast();
  const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const isOpen = state.kind === "new-watchlist";
  useEffect(() => {
    if (isOpen) {
      setName("");
      setErr(null);
    }
  }, [isOpen]);
  const submit = () => {
    if (!name.trim()) return setErr("Enter a name.");
    create.mutate(name, {
      onSuccess: (w) => {
        toast("success", `Created ${w.name}.`);
        patch.mutate({ default_watchlist_id: w.id });
        close();
      },
      onError: (e) => setErr(errorMessage(e)),
    });
  };
  return (
    <Dialog
      open={isOpen}
      onOpenChange={(o) => !o && close()}
      title="New watchlist"
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={close}>Cancel</Button>
          <Button variant="primary" loading={create.isPending} onClick={submit}>Create</Button>
        </>
      }
    >
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Field label="Name" error={err ?? undefined} required>
          {({ id, describedBy, invalid }) => (
            <Input id={id} autoFocus maxLength={60} value={name} aria-describedby={describedBy} aria-invalid={invalid} onChange={(e) => setName(e.target.value)} />
          )}
        </Field>
      </form>
    </Dialog>
  );
}

export function AddSymbolDialog() {
  const { state, close } = useDialogs();
  const { addSymbol } = useWatchlistMutations();
  const { data: lists } = useWatchlists();
  const toast = useToast();
  const [symbol, setSymbol] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState<string | null>(null);
  const isOpen = state.kind === "add-symbol";
  const wid = state.kind === "add-symbol" ? state.watchlistId : null;
  const wl = lists?.find((l) => l.id === wid);
  useEffect(() => {
    if (isOpen) {
      setSymbol("");
      setErr(null);
      setSuggestion(null);
    }
  }, [isOpen]);
  const submit = (chosen: string = symbol) => {
    if (!chosen || !wid) return setErr("Choose an instrument.");
    setSuggestion(null);
    addSymbol.mutate(
      { id: wid, symbol: chosen },
      {
        onSuccess: () => {
          toast("success", `Added ${chosen} to ${wl?.name ?? "watchlist"}.`);
          setSymbol("");
          close();
        },
        onError: (e) => {
          setErr(errorMessage(e));
          const s = (e as ApiError).details as { suggestions?: string[] } | null;
          setSuggestion(Array.isArray(s?.suggestions) && s!.suggestions[0] ? s!.suggestions[0] : null);
        },
      },
    );
  };
  return (
    <Dialog
      open={isOpen}
      onOpenChange={(o) => !o && close()}
      title={`Add symbol${wl ? ` to ${wl.name}` : ""}`}
      description="Search by company name or symbol. The symbol is verified with the data provider before it is added."
      footer={
        <>
          <Button variant="ghost" onClick={close}>Cancel</Button>
          <Button variant="primary" loading={addSymbol.isPending} disabled={!symbol} onClick={() => submit()}>Add</Button>
        </>
      }
    >
      <Field label="Instrument" error={err ?? undefined} required>
        {({ id, describedBy, invalid }) => (
          <SymbolPicker id={id} describedBy={describedBy} invalid={invalid} value={symbol} autoFocus onChange={(s) => { setSymbol(s); setErr(null); setSuggestion(null); }} />
        )}
      </Field>
      {suggestion && (
        <Button
          className="mt-3"
          variant="secondary"
          onClick={() => {
            setSymbol(suggestion);
            submit(suggestion);
          }}
        >
          Use {suggestion} instead
        </Button>
      )}
    </Dialog>
  );
}

function RenameDialog({ wl, open, onOpenChange }: { wl: Watchlist; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { rename } = useWatchlistMutations();
  const toast = useToast();
  const [name, setName] = useState(wl.name);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (open) {
      setName(wl.name);
      setErr(null);
    }
  }, [open, wl.name]);
  const submit = () =>
    rename.mutate(
      { id: wl.id, name },
      { onSuccess: () => { toast("success", "Watchlist renamed."); onOpenChange(false); }, onError: (e) => setErr((e as ApiError).message) },
    );
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Rename watchlist"
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" loading={rename.isPending} onClick={submit}>Save</Button>
        </>
      }
    >
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Field label="Name" error={err ?? undefined} required>
          {({ id, describedBy, invalid }) => (
            <Input id={id} autoFocus maxLength={60} value={name} aria-describedby={describedBy} aria-invalid={invalid} onChange={(e) => setName(e.target.value)} />
          )}
        </Field>
      </form>
    </Dialog>
  );
}

function ReorderList({ wl }: { wl: Watchlist }) {
  const { reorder } = useWatchlistMutations();
  const toast = useToast();
  const syms = [...wl.items].sort((a, b) => a.position - b.position).map((i) => i.symbol);
  const move = (i: number, d: -1 | 1) => {
    const next = [...syms];
    [next[i], next[i + d]] = [next[i + d], next[i]];
    reorder.mutate({ id: wl.id, symbols: next }, { onError: (e) => toast("error", errorMessage(e)) });
  };
  return (
    <ol className="divide-y divide-line-subtle" aria-label="Reorder symbols">
      {syms.map((s, i) => (
        <li key={s} className="flex h-11 items-center gap-2 px-[var(--panel-pad)]">
          <span className="num w-6 text-xs text-fg-3">{i + 1}</span>
          <span className="num flex-1 text-[13px] font-semibold">{s}</span>
          <IconButton size="sm" label={`Move ${s} up`} disabled={i === 0 || reorder.isPending} onClick={() => move(i, -1)}>
            <ArrowUp className="size-4" aria-hidden />
          </IconButton>
          <IconButton size="sm" label={`Move ${s} down`} disabled={i === syms.length - 1 || reorder.isPending} onClick={() => move(i, 1)}>
            <ArrowDown className="size-4" aria-hidden />
          </IconButton>
        </li>
      ))}
    </ol>
  );
}

export function WatchlistsPage() {
  const { data: lists, isLoading, isError, error, refetch } = useWatchlists();
  const { data: prefs } = usePrefs();
  const { data: session } = useSession();
  const { data: status } = useStatus();
  const [params, setParams] = useSearchParams();
  const { open } = useDialogs();
  const m = useWatchlistMutations();
  const toast = useToast();
  const [region, setRegion] = useStoredRegion();
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [reordering, setReordering] = useState(false);
  const readOnly = Boolean(session?.read_only);

  const selectedId = Number(params.get("id")) || prefs?.default_watchlist_id || lists?.[0]?.id;
  const wl = lists?.find((l) => l.id === selectedId) ?? lists?.[0];
  const symbols = useMemo(() => wl?.items.map((i) => i.symbol) ?? [], [wl]);
  const snaps = useSnapshots(symbols);
  const sort: SortState | null = wl && wl.sort_key !== "manual" ? { key: wl.sort_key, dir: wl.sort_dir as "asc" | "desc" } : null;

  if (isLoading) return <div className="p-6"><SkeletonRows rows={10} /></div>;
  if (isError) return <div className="p-6"><ErrorState message={errorMessage(error)} onRetry={() => refetch()} /></div>;

  if (!lists?.length) {
    return (
      <div className="p-4 md:p-6">
        <Panel title="Watchlists">
          <EmptyState
            icon={<ListChecks aria-hidden />}
            title="Create your first watchlist"
            actions={
              !readOnly && (
                <>
                  <Button variant="primary" icon={<Plus className="size-4" aria-hidden />} onClick={() => open({ kind: "new-watchlist" })}>New watchlist</Button>
                  <Button icon={<Sparkles className="size-4" aria-hidden />} loading={m.starter.isPending} onClick={() => m.starter.mutate(undefined, { onError: (e) => toast("error", errorMessage(e)) })}>
                    {status?.sample_data ? "Load sample starter" : "Load NSE starter"}
                  </Button>
                </>
              )
            }
          >
            Track 10–20 instruments you follow. Rows show last price, change, volume, a 3-month trend and data freshness.
          </EmptyState>
        </Panel>
      </div>
    );
  }

  return (
    <div className="grid gap-4 p-4 md:p-6 lg:grid-cols-[220px_1fr] lg:gap-5">
      <Panel title="Lists" titleId="lists-title" bodyClassName="p-1.5" actions={!readOnly && (
        <IconButton size="sm" label="New watchlist" onClick={() => open({ kind: "new-watchlist" })}>
          <Plus className="size-4" aria-hidden />
        </IconButton>
      )}>
        <ul className="flex gap-1 overflow-x-auto lg:flex-col" aria-label="Watchlists">
          {lists.map((l) => (
            <li key={l.id} className="shrink-0">
              <button
                type="button"
                aria-current={l.id === wl?.id ? "page" : undefined}
                onClick={() => setParams({ id: String(l.id) })}
                className={cn(
                  "flex h-9 w-full items-center gap-2 rounded-md px-2.5 text-left text-[13px] max-md:h-11",
                  l.id === wl?.id ? "bg-elevated text-fg ring-1 ring-line-subtle" : "text-fg-2 hover:bg-hover",
                )}
              >
                <span className="truncate">{l.name}</span>
                {l.id === prefs?.default_watchlist_id && <span className="text-[10px] text-accent-text" title="Shown on Overview">●</span>}
                <span className="num ml-auto text-xs text-fg-3">{l.item_count}</span>
              </button>
            </li>
          ))}
        </ul>
      </Panel>

      {wl && (
        <Panel
          title={wl.name}
          titleId="wl-main-title"
          bodyClassName="p-0"
          refreshing={snaps.isFetching && !snaps.isLoading}
          meta={`${wl.items.length} of 50 symbols${sort ? ` · sorted by ${sort.key.replace("_", " ")}` : " · manual order"}`}
          actions={
            <>
              {!readOnly && (
                <Button size="sm" variant="primary" icon={<Plus className="size-3.5" aria-hidden />} onClick={() => open({ kind: "add-symbol", watchlistId: wl.id })} disabled={wl.items.length >= 50}>
                  Add symbol
                </Button>
              )}
              <DM.Root>
                <DM.Trigger asChild>
                  <IconButton size="sm" label="Watchlist actions" disabled={readOnly} title={readOnly ? "Read-only demo" : undefined}>
                    <Ellipsis className="size-4" aria-hidden />
                  </IconButton>
                </DM.Trigger>
                <DM.Portal>
                  <DM.Content align="end" sideOffset={6} className="anim-pop z-50 min-w-52 rounded-[var(--radius-control)] border border-line bg-elevated p-1 shadow-[var(--shadow-pop)]">
                    {[
                      { label: "Rename", icon: <Pencil className="size-4" aria-hidden />, run: () => setRenaming(true) },
                      { label: reordering ? "Done reordering" : "Reorder manually", icon: <ArrowUp className="size-4" aria-hidden />, run: () => setReordering((r) => !r) },
                      ...(sort ? [{ label: "Clear sort (manual order)", icon: <ArrowDown className="size-4" aria-hidden />, run: () => m.sort.mutate({ id: wl.id, sort_key: "manual", sort_dir: "asc" }) }] : []),
                      { label: "Delete watchlist…", icon: <Trash className="size-4" aria-hidden />, run: () => setDeleting(true), danger: true },
                    ].map((a) => (
                      <DM.Item
                        key={a.label}
                        onSelect={a.run}
                        className={cn("flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-[13px] outline-none data-[highlighted]:bg-hover", "danger" in a && a.danger ? "text-neg" : "text-fg-2")}
                      >
                        {a.icon}
                        {a.label}
                      </DM.Item>
                    ))}
                  </DM.Content>
                </DM.Portal>
              </DM.Root>
            </>
          }
        >
          {wl.items.length === 0 ? (
            <EmptyState
              icon={<ListChecks aria-hidden />}
              title="This watchlist is empty"
              actions={!readOnly && <Button variant="primary" icon={<Plus className="size-4" aria-hidden />} onClick={() => open({ kind: "add-symbol", watchlistId: wl.id })}>Add symbol</Button>}
            >
              Search by company name or symbol.
            </EmptyState>
          ) : reordering ? (
            <ReorderList wl={wl} />
          ) : snaps.isError && !snaps.data ? (
            <ErrorState message={errorMessage(snaps.error)} onRetry={() => snaps.refetch()} />
          ) : (
            <>
              <RegionFilter wl={wl} snaps={snaps.data} value={region} onChange={setRegion} />
              <WatchlistTable
                watchlist={wl}
                snapshots={snaps.data}
                sort={sort}
                region={region}
                onSortChange={(s) => !readOnly && m.sort.mutate({ id: wl.id, sort_key: s.key, sort_dir: s.dir }, { onError: (e) => toast("error", errorMessage(e)) })}
              />
            </>
          )}
          <p className="border-t border-line-subtle px-[var(--panel-pad)] py-2 text-xs text-fg-3">
            Change and change % compare the last observed price with the previous session close from the same price series. Click a row for details; the star removes a symbol from this list.
          </p>
        </Panel>
      )}
      {wl && <RenameDialog wl={wl} open={renaming} onOpenChange={setRenaming} />}
      {wl && (
        <ConfirmDialog
          open={deleting}
          onOpenChange={setDeleting}
          title={`Delete ${wl.name}?`}
          body={`This removes the watchlist and its ${wl.items.length} symbol(s). Transactions, alerts and journal notes are not affected. This cannot be undone.`}
          confirmLabel="Delete watchlist"
          onConfirm={async () => {
            await m.remove.mutateAsync(wl.id);
            setParams({});
            toast("success", `Deleted ${wl.name}.`);
          }}
        />
      )}
    </div>
  );
}

type RegionValue = "all" | "IN" | "US" | "other";

/** Per-viewer convenience: the last market filter, kept in this browser only. */
function useStoredRegion(): [RegionValue, (r: RegionValue) => void] {
  const [region, setRegionState] = useState<RegionValue>(() => {
    try {
      const v = window.localStorage.getItem("md.watchlistRegion");
      return v === "IN" || v === "US" || v === "other" ? v : "all";
    } catch {
      return "all";
    }
  });
  const setRegion = (r: RegionValue) => {
    setRegionState(r);
    try {
      window.localStorage.setItem("md.watchlistRegion", r);
    } catch {
      /* storage unavailable: keep the choice for this page view only */
    }
  };
  return [region, setRegion];
}

/** Market filter shown only when the list mixes markets; counts make empty choices obvious. */
function RegionFilter({ wl, snaps, value, onChange }: { wl: Watchlist; snaps: Snapshot[] | undefined; value: RegionValue; onChange: (r: RegionValue) => void }) {
  const rows = buildRows(wl, snaps);
  const count = (r: RegionValue) => rows.filter((x) => (r === "all" ? true : r === "other" ? x.country !== "IN" && x.country !== "US" : x.country === r)).length;
  const present = (["IN", "US", "other"] as RegionValue[]).filter((r) => count(r) > 0);
  if (present.length < 2 && value === "all") return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 border-b border-line-subtle px-[var(--panel-pad)] py-2 text-xs" role="group" aria-label="Filter by market">
      {(["all", "IN", "US", "other"] as RegionValue[])
        .filter((r) => r === "all" || present.includes(r) || r === value)
        .map((r) => (
          <button
            key={r}
            type="button"
            aria-pressed={value === r}
            onClick={() => onChange(r)}
            className={cn(
              "rounded-[var(--radius-control)] border px-2 py-1 max-md:min-h-9",
              value === r ? "border-accent/60 bg-accent-soft text-fg" : "border-line text-fg-3 hover:text-fg-2",
            )}
          >
            {r === "all" ? "All" : r === "IN" ? "India" : r === "US" ? "US" : "Other/unknown"} <span className="num text-fg-3">{count(r)}</span>
          </button>
        ))}
    </div>
  );
}
