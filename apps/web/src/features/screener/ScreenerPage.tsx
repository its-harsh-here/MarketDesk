import { Download, Funnel, ListPlus, Plus, RefreshCw, Save, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Button, IconButton } from "@/components/ui/Button";
import { DataTable, type Column, type SortState } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/Form";
import { Panel } from "@/components/ui/Panel";
import { Pill } from "@/components/ui/Badges";
import { Segmented } from "@/components/ui/Segmented";
import { EmptyState, ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { ApiError, errorMessage } from "@/lib/api/client";
import { DASH, formatInstant, formatRelative, formatSessionDate } from "@/lib/format";
import { useDebounced } from "@/lib/hooks";
import { cn } from "@/lib/cn";
import { useSession } from "@/features/settings/api";
import {
  downloadScreenCsv,
  parseSpec,
  specKey,
  useCatalog,
  useListMutations,
  useRefreshState,
  useSavedScreens,
  useScreen,
  useScreenMutations,
  useStartRefresh,
  useUniverses,
  type Catalog,
  type DatasetStatus,
  type Filter,
  type MetricDef,
  type ScreenResult,
  type ScreenRow,
  type UniverseInfo,
  type UniverseOption,
  type UniverseSpec,
} from "./api";
import { MetricValue, SCALES, UNIT_HINT, cellNote, defaultScale, formatMetric } from "./cells";
import { HeatmapView } from "./Heatmap";

const OPS = [
  { value: "gte", label: "≥" },
  { value: "lte", label: "≤" },
  { value: "between", label: "between" },
] as const;

const MARKETS = [
  { value: "IN", label: "India" },
  { value: "US", label: "United States" },
];

interface Draft {
  id: string;
  metric: string;
  op: "gte" | "lte" | "between" | "in";
  value: string;
  value2: string;
  currency: "INR" | "USD";
  scale: number;
  values: string[];
}

let seq = 0;
const newId = () => `f${++seq}`;

function plain(n: number): string {
  return n.toLocaleString("en-US", { useGrouping: false, maximumFractionDigits: 10 });
}

function toFilter(d: Draft, defs: Map<string, MetricDef>): Filter | null {
  if (d.op === "in") return d.values.length ? { metric: d.metric, op: "in", values: d.values } : null;
  const def = defs.get(d.metric);
  const num = (s: string) => {
    const t = s.replace(/[,\s]/g, "");
    if (!/^-?\d+(\.\d+)?$/.test(t)) return null;
    return Number(t) * (def?.unit === "currency" ? d.scale : 1);
  };
  const lo = num(d.value);
  if (lo === null) return null;
  const f: Filter = { metric: d.metric, op: d.op, value: plain(lo) };
  if (d.op === "between") {
    const hi = num(d.value2);
    if (hi === null || hi < lo) return null;
    f.value2 = plain(hi);
  }
  if (def?.unit === "currency") f.currency = d.currency;
  return f;
}

function fromFilter(f: Filter, defs: Map<string, MetricDef>): Draft {
  const def = defs.get(f.metric);
  const currency = f.currency ?? "INR";
  const scale = def?.unit === "currency" ? defaultScale(f.metric, currency) : 1;
  const show = (v?: string) => (v === undefined ? "" : plain(Number(v) / scale));
  return { id: newId(), metric: f.metric, op: f.op, value: show(f.value), value2: show(f.value2), currency, scale, values: f.values ?? [] };
}

function filterLabel(f: Filter, catalog: Catalog): string {
  const text = catalog.text_fields.find((t) => t.key === f.metric);
  if (text) return `${text.label}: ${(f.values ?? []).join(", ")}`;
  const def = catalog.metrics.find((m) => m.key === f.metric);
  if (!def) return f.metric;
  const fmt = (v?: string) => (def.unit === "currency" ? formatMetric(def, v, f.currency) : formatMetric(def, v, null));
  if (f.op === "between") return `${def.label} ${fmt(f.value)} – ${fmt(f.value2)}`;
  return `${def.label} ${f.op === "gte" ? "≥" : "≤"} ${fmt(f.value)}`;
}

// ---------------------------------------------------------------------------------------------------------- page
export function ScreenerPage() {
  const [params, setParams] = useSearchParams();
  const catalog = useCatalog();
  const universes = useUniverses();
  const view = params.get("view") === "heatmap" ? "heatmap" : "screen";
  const options = useMemo(() => universes.data?.options ?? [], [universes.data]);
  const universe: UniverseSpec | null = useMemo(() => {
    const wanted = parseSpec(params.get("u"));
    if (wanted && options.some((o) => specKey(o) === specKey(wanted))) return wanted;
    return options.length ? { kind: "watchlists" } : null;
  }, [params, options]);

  const setParam = (k: string, v: string | null) =>
    setParams((p) => {
      const n = new URLSearchParams(p);
      if (v === null) n.delete(k);
      else n.set(k, v);
      return n;
    }, { replace: true });

  return (
    <div className="grid grid-cols-1 gap-4 p-4 md:p-6 lg:grid-cols-12 lg:gap-5">
      <UniverseBar
        options={options}
        universe={universe}
        loading={universes.isLoading}
        maxSize={universes.data?.max_size}
        onChange={(u) => setParam("u", specKey(u))}
        view={view}
        onView={(v) => setParam("view", v === "screen" ? null : v)}
      />
      {universes.isError ? (
        <ErrorState className="lg:col-span-12" message={errorMessage(universes.error)} onRetry={() => universes.refetch()} />
      ) : !catalog.data || !universe ? (
        <Panel className="lg:col-span-12">
          <SkeletonRows rows={8} />
        </Panel>
      ) : view === "heatmap" ? (
        <HeatmapView universe={universe} />
      ) : (
        <ScreenView key={specKey(universe)} catalog={catalog.data} universe={universe} />
      )}
    </div>
  );
}

function UniverseBar({ options, universe, loading, maxSize, onChange, view, onView }: {
  options: UniverseOption[];
  universe: UniverseSpec | null;
  loading: boolean;
  maxSize?: number;
  onChange: (u: UniverseSpec) => void;
  view: "screen" | "heatmap";
  onView: (v: "screen" | "heatmap") => void;
}) {
  const [listsOpen, setListsOpen] = useState(false);
  const { data: session } = useSession();
  return (
    <section aria-label="Universe and view" className="flex flex-wrap items-end gap-3 lg:col-span-12">
      <Field label="Universe" className="w-full sm:w-80" hint={maxSize ? `A named list, never the whole market · at most ${maxSize} members` : undefined}>
        {({ id, describedBy }) => (
          <Select id={id} aria-describedby={describedBy} disabled={loading} value={universe ? specKey(universe) : ""} onChange={(e) => {
            const u = parseSpec(e.target.value);
            if (u) onChange(u);
          }}>
            {options.map((o) => (
              <option key={specKey(o)} value={specKey(o)}>
                {o.label} ({o.count})
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Button icon={<ListPlus className="size-4" aria-hidden />} onClick={() => setListsOpen(true)} disabled={session?.read_only} title={session?.read_only ? "Read-only demo" : undefined}>
        Manage lists
      </Button>
      <div className="ml-auto">
        <Segmented label="Screener view" value={view} onChange={onView} options={[{ value: "screen", label: "Screen" }, { value: "heatmap", label: "Sector heatmap" }]} />
      </div>
      <ListsDialog open={listsOpen} onOpenChange={setListsOpen} options={options} onPick={onChange} />
    </section>
  );
}

// ------------------------------------------------------------------------------------------------- dataset status
export function DatasetBar({ universe, info, dataset }: { universe: UniverseSpec; info?: UniverseInfo; dataset?: DatasetStatus }) {
  const refresh = useRefreshState();
  const start = useStartRefresh();
  const toast = useToast();
  const st = refresh.data;
  const running = Boolean(st?.running);
  const last = !running && st?.result && st.finished_at ? st : null;
  const go = () =>
    start.mutate(universe, {
      onError: (e) => toast("error", errorMessage(e)),
    });
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[13px]" aria-live="polite">
      <p className="min-w-0 basis-full text-fg-2 sm:flex-1 sm:basis-auto">
        {dataset ? (
          <>
            <span className="text-fg">{info?.label}</span> · <span className="num">{dataset.members}</span> member{dataset.members === 1 ? "" : "s"}
            {info?.excluded.length ? <span title={info.excluded.join(", ")}> ({info.excluded.length} {info.excluded.length === 1 ? "index or currency" : "indices or currencies"} not screened)</span> : null}
            {info?.truncated ? <span className="text-warn"> · {info.truncated} beyond the size limit not included</span> : null} · data loaded for{" "}
            <span className="num">{dataset.loaded}</span>
            {dataset.oldest ? <span title={`Oldest snapshot ${formatInstant(dataset.oldest)}; newest ${formatInstant(dataset.newest)}`}> · oldest snapshot {formatRelative(dataset.oldest)}</span> : null}
            {dataset.stale ? <span className="text-warn"> · {dataset.stale} older than {dataset.refresh_hours} h</span> : null}
          </>
        ) : (
          DASH
        )}
      </p>
      {running ? (
        <span className="flex items-center gap-2 text-fg-2" role="status">
          <RefreshCw className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
          Loading data{st?.total ? ` ${st.done ?? 0} of ${st.total}` : ""}…
        </span>
      ) : (
        <Button size="sm" icon={<RefreshCw className="size-4" aria-hidden />} onClick={go} loading={start.isPending}
          title="Fetch quotes, one-year history, fundamentals and annual statements for members whose snapshot is missing or older than the refresh window">
          {dataset && dataset.loaded < dataset.members ? "Load data" : "Refresh data"}
        </Button>
      )}
      {last?.result && (
        <span className="w-full text-xs text-fg-3">
          Last refresh ({last.label}): {last.result.refreshed} updated
          {last.result.failed.length ? `, ${last.result.failed.length} failed (${last.result.failed.map((f) => f.symbol).join(", ")})` : ""}
          {last.result.remaining ? `, ${last.result.remaining} still due — refresh again` : ""}
          {last.result.due === 0 ? " — everything was already current" : ""}.
        </span>
      )}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------------- screen
function ScreenView({ catalog, universe }: { catalog: Catalog; universe: UniverseSpec }) {
  const [params, setParams] = useSearchParams();
  const defs = useMemo(() => new Map(catalog.metrics.map((m) => [m.key, m])), [catalog]);
  const saved = useSavedScreens();
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [sort, setSort] = useState<SortState | null>({ key: "symbol", dir: "asc" });
  const [loadedScreen, setLoadedScreen] = useState<number | null>(null);

  // Opening a saved screen (from the URL) loads its filters and sort once.
  const screenId = Number(params.get("screen")) || null;
  useEffect(() => {
    if (!screenId || !saved.data || loadedScreen === screenId) return;
    const s = saved.data.find((x) => x.id === screenId);
    if (!s) return;
    setDrafts(s.filters.map((f) => fromFilter(f, defs)));
    setSort(s.sort ?? { key: "symbol", dir: "asc" });
    setLoadedScreen(screenId);
  }, [screenId, saved.data, loadedScreen, defs]);

  const filters = useMemo(() => drafts.map((d) => toFilter(d, defs)).filter((f): f is Filter => f !== null), [drafts, defs]);
  const incomplete = drafts.length - filters.length;
  const debounced = useDebounced(filters, 300);
  const base = useScreen(universe, [], null);
  const result = useScreen(universe, debounced, sort);
  const r = result.data;

  const textOptions = useMemo(() => {
    const rows = base.data?.rows ?? [];
    const uniq = (xs: (string | null)[]) => [...new Set(xs.filter((x): x is string => Boolean(x)))].sort();
    return {
      country: MARKETS.filter((m) => rows.some((x) => x.country === m.value)).map((m) => ({ value: m.value, label: m.label })),
      sector: uniq(rows.map((x) => x.sector)).map((v) => ({ value: v, label: v })),
      industry: uniq(rows.map((x) => x.industry)).map((v) => ({ value: v, label: v })),
      currency: uniq(rows.map((x) => x.currency)).map((v) => ({ value: v, label: v })),
      exchange: uniq(rows.map((x) => x.exchange)).map((v) => ({ value: v, label: v })),
    } as Record<string, { value: string; label: string }[]>;
  }, [base.data]);

  const pickScreen = (id: number | null) =>
    setParams((p) => {
      const n = new URLSearchParams(p);
      if (id === null) {
        n.delete("screen");
        setDrafts([]);
        setSort({ key: "symbol", dir: "asc" });
        setLoadedScreen(null);
      } else n.set("screen", String(id));
      return n;
    }, { replace: true });

  return (
    <>
      <Panel title="Filters" titleId="flt-title" className="lg:col-span-12 xl:col-span-4 xl:self-start" actions={<AddFilter catalog={catalog} onAdd={(metric) => {
        const def = defs.get(metric);
        const text = catalog.text_fields.some((t) => t.key === metric);
        setDrafts((ds) => [...ds, {
          id: newId(), metric, op: text ? "in" : "gte", value: "", value2: "", currency: "INR",
          scale: def?.unit === "currency" ? defaultScale(metric, "INR") : 1, values: [],
        }]);
      }} />}>
        <div className="space-y-3">
          <SavedScreens universe={universe} filters={filters} sort={sort} current={screenId} onPick={pickScreen} saved={saved.data ?? []} />
          {drafts.length === 0 ? (
            <p className="text-[13px] leading-5 text-fg-2">
              No filters yet: every member is listed. Add a filter for valuation, growth, liquidity, leverage, risk or price.
            </p>
          ) : (
            <ul className="grid gap-2 lg:grid-cols-2 xl:grid-cols-1" aria-label="Active filters">
              {drafts.map((d) => (
                <FilterRow key={d.id} draft={d} catalog={catalog} textOptions={textOptions[d.metric] ?? []}
                  funnel={funnelFor(r, toFilter(d, defs))}
                  onChange={(nd) => setDrafts((ds) => ds.map((x) => (x.id === d.id ? nd : x)))}
                  onRemove={() => setDrafts((ds) => ds.filter((x) => x.id !== d.id))} />
              ))}
            </ul>
          )}
          {incomplete > 0 && <p className="text-xs text-warn">{incomplete} incomplete filter{incomplete === 1 ? " is" : "s are"} not applied yet.</p>}
          <p className="text-xs leading-4 text-fg-3">{r?.note ?? "Missing values never pass a filter."}</p>
        </div>
      </Panel>
      <Results catalog={catalog} universe={universe} result={r} loading={result.isLoading} error={result.isError ? result.error : null}
        refetch={() => result.refetch()} filters={debounced} sort={sort} onSort={setSort} fetching={result.isFetching && !result.isLoading} />
    </>
  );
}

/** Pass/fail/missing counts for one filter (the server echoes each filter in the same normalized shape). */
function funnelFor(r: ScreenResult | undefined, f: Filter | null) {
  if (!r || !f) return undefined;
  const key = JSON.stringify(f);
  return r.funnel.find((x) => JSON.stringify(x.filter) === key);
}

function AddFilter({ catalog, onAdd }: { catalog: Catalog; onAdd: (metric: string) => void }) {
  const groups = useMemo(() => {
    const g = new Map<string, MetricDef[]>();
    for (const m of catalog.metrics) g.set(m.group, [...(g.get(m.group) ?? []), m]);
    return [...g.entries()];
  }, [catalog]);
  return (
    <label className="flex items-center gap-2 text-[13px]">
      <span className="sr-only">Add a filter</span>
      <Plus className="size-4 text-fg-3" aria-hidden />
      <Select className="h-8 w-44" value="" onChange={(e) => e.target.value && onAdd(e.target.value)}>
        <option value="">Add filter…</option>
        <optgroup label="Listing">
          {catalog.text_fields.map((t) => (
            <option key={t.key} value={t.key}>{t.label}</option>
          ))}
        </optgroup>
        {groups.map(([g, ms]) => (
          <optgroup key={g} label={g}>
            {ms.map((m) => (
              <option key={m.key} value={m.key}>{m.label}</option>
            ))}
          </optgroup>
        ))}
      </Select>
    </label>
  );
}

function FilterRow({ draft, catalog, textOptions, funnel, onChange, onRemove }: {
  draft: Draft;
  catalog: Catalog;
  textOptions: { value: string; label: string }[];
  funnel?: { passed: number; failed: number; missing: number };
  onChange: (d: Draft) => void;
  onRemove: () => void;
}) {
  const def = catalog.metrics.find((m) => m.key === draft.metric);
  const text = catalog.text_fields.find((t) => t.key === draft.metric);
  const label = def?.label ?? text?.label ?? draft.metric;
  const bad = (s: string) => s !== "" && !/^-?\d+(\.\d+)?$/.test(s.replace(/[,\s]/g, ""));
  return (
    <li className="rounded-[var(--radius-control)] border border-line-subtle bg-canvas/40 p-2.5">
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-fg" title={def?.formula}>{label}</span>
        <IconButton label={`Remove filter ${label}`} size="sm" onClick={onRemove}>
          <X className="size-4" aria-hidden />
        </IconButton>
      </div>
      {text ? (
        <fieldset className="mt-1.5">
          <legend className="sr-only">{label} values</legend>
          {textOptions.length === 0 ? (
            <p className="text-xs text-fg-3">No {label.toLowerCase()} values in this universe’s loaded data yet.</p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {textOptions.map((o) => {
                const on = draft.values.includes(o.value);
                return (
                  <button key={o.value} type="button" aria-pressed={on}
                    onClick={() => onChange({ ...draft, values: on ? draft.values.filter((v) => v !== o.value) : [...draft.values, o.value] })}
                    className={cn("rounded-full border px-2.5 py-1 text-xs max-md:min-h-9", on ? "border-accent bg-accent/15 text-fg" : "border-line text-fg-2 hover:bg-hover")}>
                    {o.label}
                  </button>
                );
              })}
            </div>
          )}
        </fieldset>
      ) : def ? (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          <Select aria-label={`${label} condition`} className="h-8 w-24" value={draft.op} onChange={(e) => onChange({ ...draft, op: e.target.value as Draft["op"] })}>
            {OPS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </Select>
          <Input aria-label={`${label} ${draft.op === "between" ? "from" : "value"}`} aria-invalid={bad(draft.value)} inputMode="decimal" className="h-8 w-24 num"
            value={draft.value} onChange={(e) => onChange({ ...draft, value: e.target.value })} placeholder="0" />
          {draft.op === "between" && (
            <>
              <span className="text-xs text-fg-3">and</span>
              <Input aria-label={`${label} to`} aria-invalid={bad(draft.value2)} inputMode="decimal" className="h-8 w-24 num"
                value={draft.value2} onChange={(e) => onChange({ ...draft, value2: e.target.value })} placeholder="0" />
            </>
          )}
          {def.unit === "currency" ? (
            <Select aria-label={`${label} unit`} className="h-8 w-28" value={`${draft.currency}:${draft.scale}`} onChange={(e) => {
              const [ccy, f] = e.target.value.split(":");
              onChange({ ...draft, currency: ccy as "INR" | "USD", scale: Number(f) });
            }}>
              {(["INR", "USD"] as const).flatMap((ccy) => SCALES[ccy].map((s) => <option key={`${ccy}${s.factor}`} value={`${ccy}:${s.factor}`}>{s.label}</option>))}
            </Select>
          ) : (
            <span className="text-xs text-fg-3">{UNIT_HINT[def.unit]}</span>
          )}
        </div>
      ) : null}
      {funnel && (
        <p className="mt-1.5 text-xs text-fg-3">
          <span className="num text-fg-2">{funnel.passed}</span> pass · <span className="num">{funnel.failed}</span> fail
          {funnel.missing ? <> · <span className="num text-warn">{funnel.missing}</span> without data (excluded)</> : null}
        </p>
      )}
      {def?.unit === "currency" && <p className="mt-1 text-xs text-fg-3">Listings in the other currency are compared at the current USD/INR rate.</p>}
    </li>
  );
}

function SavedScreens({ universe, filters, sort, current, onPick, saved }: {
  universe: UniverseSpec;
  filters: Filter[];
  sort: SortState | null;
  current: number | null;
  onPick: (id: number | null) => void;
  saved: { id: number; name: string; universe: UniverseSpec }[];
}) {
  const m = useScreenMutations();
  const toast = useToast();
  const { data: session } = useSession();
  const [name, setName] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const cur = saved.find((s) => s.id === current);
  const ro = Boolean(session?.read_only);
  const save = () => {
    if (!cur) return setName("");
    m.update.mutate({ id: cur.id, universe, filters, sort }, {
      onSuccess: () => toast("success", `Saved “${cur.name}”.`),
      onError: (e) => toast("error", errorMessage(e)),
    });
  };
  return (
    <div className="space-y-2">
      <div className="flex items-end gap-2">
        <Field label="Saved screen" className="min-w-0 flex-1">
          {({ id }) => (
            <Select id={id} value={current ?? ""} onChange={(e) => onPick(e.target.value ? Number(e.target.value) : null)}>
              <option value="">Unsaved screen</option>
              {saved.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </Select>
          )}
        </Field>
        <IconButton label={cur ? `Save changes to ${cur.name}` : "Save this screen"} onClick={save} disabled={ro}>
          <Save className="size-4" aria-hidden />
        </IconButton>
        {cur && (
          <IconButton label={`Delete saved screen ${cur.name}`} onClick={() => setConfirmDelete(true)} disabled={ro}>
            <Trash2 className="size-4" aria-hidden />
          </IconButton>
        )}
      </div>
      {cur && specKey(cur.universe) !== specKey(universe) && (
        <p className="text-xs text-warn">This screen was saved for another universe; saving will switch it to the current one.</p>
      )}
      {name !== null && (
        <form className="flex items-end gap-2" onSubmit={(e) => {
          e.preventDefault();
          m.create.mutate({ name, universe, filters, sort }, {
            onSuccess: (s) => {
              toast("success", `Saved “${s.name}”.`);
              setName(null);
              onPick(s.id);
            },
          });
        }}>
          <Field label="Name for this screen" className="min-w-0 flex-1" error={m.create.error ? errorMessage(m.create.error) : undefined}>
            {({ id, describedBy, invalid }) => <Input id={id} aria-describedby={describedBy} aria-invalid={invalid} autoFocus maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />}
          </Field>
          <Button type="submit" variant="primary" disabled={!name.trim()} loading={m.create.isPending}>Save</Button>
          <Button variant="ghost" onClick={() => setName(null)}>Cancel</Button>
        </form>
      )}
      {cur && (
        <Dialog open={confirmDelete} onOpenChange={setConfirmDelete} title={`Delete “${cur.name}”?`} size="sm"
          description="The saved filters are removed. Watchlists, lists and data are not affected."
          footer={<>
            <Button variant="ghost" onClick={() => setConfirmDelete(false)}>Cancel</Button>
            <Button variant="danger" loading={m.remove.isPending} onClick={() => m.remove.mutate(cur.id, {
              onSuccess: () => {
                setConfirmDelete(false);
                onPick(null);
                toast("success", "Saved screen deleted.");
              },
              onError: (e) => toast("error", errorMessage(e)),
            })}>Delete</Button>
          </>}>
          <span className="sr-only">Confirm deletion</span>
        </Dialog>
      )}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------------ results
function Results({ catalog, universe, result, loading, error, refetch, filters, sort, onSort, fetching }: {
  catalog: Catalog;
  universe: UniverseSpec;
  result?: ScreenResult;
  loading: boolean;
  error: unknown;
  refetch: () => void;
  filters: Filter[];
  sort: SortState | null;
  onSort: (s: SortState) => void;
  fetching: boolean;
}) {
  const defs = useMemo(() => new Map(catalog.metrics.map((m) => [m.key, m])), [catalog]);
  const [preview, setPreview] = useState<ScreenRow | null>(null);
  const [exporting, setExporting] = useState(false);
  const toast = useToast();
  const navigate = useNavigate();
  const metricCols = useMemo(() => {
    const keys = [...new Set([...filters.map((f) => f.metric).filter((k) => defs.has(k)), ...catalog.default_columns])];
    return keys.map((k) => defs.get(k)!);
  }, [filters, catalog, defs]);
  const rows = result?.rows ?? [];

  const columns: Column<ScreenRow>[] = [
    {
      key: "symbol",
      header: "Instrument",
      sortable: true,
      render: (r) => (
        <div className="min-w-0 max-w-64">
          <div className="num truncate font-medium text-fg">{r.symbol}</div>
          <div className="truncate text-xs text-fg-3" title={r.name ?? undefined}>{r.name ?? DASH}</div>
        </div>
      ),
    },
    { key: "sector", header: "Sector", sortable: true, hideBelow: "xl", render: (r) => <span className="text-xs text-fg-2">{r.sector ?? DASH}</span> },
    ...metricCols.map((def): Column<ScreenRow> => ({
      key: def.key,
      header: def.label,
      align: "right",
      sortable: true,
      render: (r) => (r.metrics ? <MetricValue def={def} cell={r.metrics[def.key]} currency={r.currency} /> : <span className="text-xs text-fg-3" title="Not loaded yet: refresh the dataset">not loaded</span>),
    })),
  ];

  return (
    <Panel title="Results" titleId="res-title" className="lg:col-span-12 xl:col-span-8" refreshing={fetching}
      meta={result ? `${result.matched} of ${result.dataset.members} match` : undefined}
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button size="sm" icon={<Download className="size-4" aria-hidden />} loading={exporting} disabled={!result}
            onClick={async () => {
              setExporting(true);
              try {
                await downloadScreenCsv(universe, filters, sort);
              } catch (e) {
                toast("error", errorMessage(e));
              } finally {
                setExporting(false);
              }
            }}>
            Export CSV
          </Button>
        </div>
        {result && <DatasetBar universe={universe} info={result.universe} dataset={result.dataset} />}
        {result && result.filters.length > 0 && (
          <ul className="flex flex-wrap gap-1.5" aria-label="Filter results">
            {result.funnel.map((f, i) => (
              <li key={i}>
                <Pill tone={f.passed ? "neutral" : "warn"}>
                  {filterLabel(f.filter, catalog)} · {f.passed} pass{f.missing ? ` · ${f.missing} no data` : ""}
                </Pill>
              </li>
            ))}
          </ul>
        )}
        {result?.fx && result.filters.some((f) => defs.get(f.metric)?.unit === "currency") && (
          <p className="text-xs text-fg-3">
            {result.fx.rate ? `USD/INR ${Number(result.fx.rate).toFixed(4)} (${result.fx.status}${result.fx.market_time ? `, ${formatInstant(result.fx.market_time)}` : ""}) converts amounts between currencies for comparison only.` : result.fx.message}
          </p>
        )}
        {loading ? (
          <SkeletonRows rows={8} />
        ) : error && !result ? (
          error instanceof ApiError && error.status === 404 ? (
            <EmptyState title="This universe no longer exists">Choose another universe above.</EmptyState>
          ) : (
            <ErrorState message={errorMessage(error)} onRetry={refetch} />
          )
        ) : !result ? null : result.dataset.members === 0 ? (
          <EmptyState icon={<Funnel />} title="This universe has no members"
            actions={<Link to="/watchlists" className="text-[13px] text-accent-text hover:underline">Add symbols to a watchlist</Link>}>
            Screens cover the instruments you name: a watchlist, your holdings or a pasted list.
          </EmptyState>
        ) : result.dataset.loaded === 0 ? (
          <EmptyState icon={<RefreshCw />} title="No data loaded for this universe yet">
            Use “Load data” to fetch each member’s quote, one-year history, fundamentals and annual statements. Screens then read
            that stored snapshot; the worker keeps it current daily.
          </EmptyState>
        ) : rows.length === 0 ? (
          <EmptyState icon={<Funnel />} title="No instruments pass every filter">
            Members without a value for a filtered metric are excluded, never counted as passing. Loosen a filter or see the
            counts above.
          </EmptyState>
        ) : (
          <>
            <DataTable
              caption={`Screen results for ${result.universe.label}`}
              columns={columns}
              rows={rows}
              rowKey={(r) => r.symbol}
              onRowClick={setPreview}
              sort={sort}
              onSortChange={onSort}
              mobileSummary={(r) => (
                <div className="flex items-center gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="num truncate font-medium">{r.symbol}</div>
                    <div className="truncate text-xs text-fg-3">{r.name ?? DASH}</div>
                  </div>
                  {r.metrics && defs.get("change_1d_pct") && <MetricValue def={defs.get("change_1d_pct")!} cell={r.metrics.change_1d_pct} currency={r.currency} />}
                </div>
              )}
              mobileDetailKeys={["sector", ...metricCols.map((m) => m.key)]}
            />
            <Coverage result={result} defs={defs} keys={metricCols.map((m) => m.key)} />
          </>
        )}
      </div>
      {preview && <PreviewDialog row={preview} catalog={catalog} onClose={() => setPreview(null)} onOpen={() => navigate(`/instrument/${encodeURIComponent(preview.symbol)}`)} />}
    </Panel>
  );
}

function Coverage({ result, defs, keys }: { result: ScreenResult; defs: Map<string, MetricDef>; keys: string[] }) {
  return (
    <details className="text-xs text-fg-3">
      <summary className="cursor-pointer select-none text-fg-2 hover:text-fg">Data coverage and as-of dates</summary>
      <ul className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2">
        {keys.map((k) => {
          const c = result.coverage[k];
          const def = defs.get(k);
          if (!c || !def) return null;
          return (
            <li key={k} title={def.formula}>
              <span className="text-fg-2">{def.label}</span>: <span className="num">{c.with_value}</span> of <span className="num">{c.members}</span> with a value
              {c.as_of_min ? ` · ${c.as_of_min === c.as_of_max ? formatSessionDate(c.as_of_min) : `${formatSessionDate(c.as_of_min)} – ${formatSessionDate(c.as_of_max)}`}` : ""}
            </li>
          );
        })}
      </ul>
      <p className="mt-2">Hover a value (or open a row) for its formula, period and source. Prices are the provider’s observations; ratios are computed in MarketDesk from the provider’s figures.</p>
    </details>
  );
}

function PreviewDialog({ row, catalog, onClose, onOpen }: { row: ScreenRow; catalog: Catalog; onClose: () => void; onOpen: () => void }) {
  const groups = useMemo(() => {
    const g = new Map<string, MetricDef[]>();
    for (const m of catalog.metrics) g.set(m.group, [...(g.get(m.group) ?? []), m]);
    return [...g.entries()];
  }, [catalog]);
  const inputs = row.inputs ?? {};
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={`${row.symbol} · ${row.name ?? ""}`} size="lg"
      description={`${row.exchange ?? DASH} · ${row.currency ?? DASH} · ${row.sector ?? "sector not reported"}${row.industry ? ` · ${row.industry}` : ""}`}
      footer={<>
        <Button variant="ghost" onClick={onClose}>Close</Button>
        <Button variant="primary" onClick={onOpen}>Open instrument</Button>
      </>}>
      {!row.metrics ? (
        <p className="text-[13px] text-fg-2">No data is loaded for this member yet. Use “Load data” above.</p>
      ) : (
        <div className="space-y-4">
          {groups.map(([g, ms]) => (
            <div key={g}>
              <h3 className="mb-1 text-xs font-medium text-fg-2">{g}</h3>
              <dl className="divide-y divide-line-subtle/60 text-[13px]">
                {ms.map((m) => (
                  <div key={m.key} className="flex items-baseline justify-between gap-3 py-1.5">
                    <dt className="min-w-0">
                      <span className="text-fg-2">{m.label}</span>
                      <span className="block text-xs text-fg-3">{cellNote(m, row.metrics?.[m.key])}</span>
                    </dt>
                    <dd className="shrink-0 text-right"><MetricValue def={m} cell={row.metrics?.[m.key]} currency={row.currency} /></dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
          <div className="text-xs text-fg-3">
            <h3 className="mb-1 font-medium text-fg-2">Inputs</h3>
            <ul className="space-y-0.5">
              {Object.entries(inputs).map(([k, v]) => (
                <li key={k}>
                  {k}: {v.status}{v.source_label ? ` · ${v.source_label}` : v.source ? ` · ${v.source}` : ""}{v.fetched_at ? ` · fetched ${formatRelative(v.fetched_at)}` : ""}
                  {v.adjustment ? ` · ${v.adjustment}` : ""}{v.message ? ` · ${v.message}` : ""}
                </li>
              ))}
              <li>Snapshot computed {formatRelative(row.computed_at)}.</li>
            </ul>
          </div>
        </div>
      )}
    </Dialog>
  );
}

// ------------------------------------------------------------------------------------------------------- lists
function ListsDialog({ open, onOpenChange, options, onPick }: { open: boolean; onOpenChange: (o: boolean) => void; options: UniverseOption[]; onPick: (u: UniverseSpec) => void }) {
  const lists = options.filter((o) => o.kind === "list");
  const m = useListMutations();
  const toast = useToast();
  const [editing, setEditing] = useState<UniverseOption | "new" | null>(null);
  const [name, setName] = useState("");
  const [symbols, setSymbols] = useState("");
  const [skipped, setSkipped] = useState<{ symbol: string; reason: string }[]>([]);
  const start = (o: UniverseOption | "new") => {
    setEditing(o);
    setName(o === "new" ? "" : o.name ?? "");
    setSymbols(o === "new" ? "" : (o.symbols ?? []).join(" "));
    setSkipped([]);
  };
  const mut = editing === "new" ? m.create : m.update;
  const submit = () => {
    const done = (out: { id: number; name: string; skipped: { symbol: string; reason: string }[] }) => {
      setSkipped(out.skipped);
      toast("success", `List “${out.name}” saved${out.skipped.length ? ` (${out.skipped.length} symbol${out.skipped.length === 1 ? "" : "s"} skipped)` : ""}.`);
      if (!out.skipped.length) setEditing(null);
      onPick({ kind: "list", id: out.id });
    };
    if (editing === "new") m.create.mutate({ name, symbols }, { onSuccess: done });
    else if (editing) m.update.mutate({ id: editing.id!, name, symbols }, { onSuccess: done });
  };
  const err = mut.error instanceof ApiError ? mut.error : null;
  const errSkipped = (err?.details as { skipped?: { symbol: string; reason: string }[] } | undefined)?.skipped;
  return (
    <Dialog open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) setEditing(null); }} title="Screening lists" size="lg"
      description="A list is a named set of symbols you paste (for example an index’s members you trust). Each symbol is verified with the data provider; indices and currencies are not screened.">
      {editing ? (
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); submit(); }}>
          <Field label="Name" required>
            {({ id }) => <Input id={id} maxLength={60} value={name} onChange={(e) => setName(e.target.value)} autoFocus />}
          </Field>
          <Field label="Symbols" required hint="Separate with spaces, commas or new lines, e.g. RELIANCE.NS TCS.NS AAPL">
            {({ id, describedBy }) => <Textarea id={id} aria-describedby={describedBy} rows={6} className="num" value={symbols} onChange={(e) => setSymbols(e.target.value)} />}
          </Field>
          {err && <InlineNotice tone="neg">{err.message}</InlineNotice>}
          {[...(errSkipped ?? []), ...skipped].length > 0 && (
            <InlineNotice tone="warn">
              <p className="font-medium">Skipped symbols</p>
              <ul className="mt-1 space-y-0.5 text-xs">
                {[...(errSkipped ?? []), ...skipped].map((s) => <li key={s.symbol}><span className="num">{s.symbol}</span>: {s.reason}</li>)}
              </ul>
            </InlineNotice>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setEditing(null)}>Back</Button>
            <Button type="submit" variant="primary" loading={mut.isPending} disabled={!name.trim() || !symbols.trim()}>
              {mut.isPending ? "Verifying symbols…" : "Save list"}
            </Button>
          </div>
        </form>
      ) : (
        <div className="space-y-3">
          {lists.length === 0 ? (
            <p className="text-[13px] text-fg-2">No lists yet. Watchlists and holdings are always available as universes.</p>
          ) : (
            <ul className="divide-y divide-line-subtle">
              {lists.map((l) => (
                <li key={l.id} className="flex items-center gap-2 py-2">
                  <span className="min-w-0 flex-1 truncate text-[13px]">{l.name} <span className="text-fg-3">· {l.count} symbols</span></span>
                  <Button size="sm" variant="ghost" onClick={() => start(l)}>Edit</Button>
                  <Button size="sm" variant="ghost" loading={m.remove.isPending && m.remove.variables === l.id} onClick={() => m.remove.mutate(l.id!, {
                    onSuccess: () => toast("success", "List deleted."),
                    onError: (e) => toast("error", errorMessage(e)),
                  })}>Delete</Button>
                </li>
              ))}
            </ul>
          )}
          <Button icon={<Plus className="size-4" aria-hidden />} onClick={() => start("new")}>New list</Button>
        </div>
      )}
    </Dialog>
  );
}
