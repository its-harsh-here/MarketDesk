import { useEffect, useMemo, useState } from "react";
import { useDialogs } from "@/app/dialogs";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Select, Textarea, Input } from "@/components/ui/Form";
import { Pill } from "@/components/ui/Badges";
import { Segmented } from "@/components/ui/Segmented";
import { ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { errorMessage, type JournalDetail, type JournalVersion } from "@/lib/api/client";
import { lineDiff } from "@/lib/diff";
import { DASH, formatInstant, formatMoney, formatPercent, formatSessionDate, todayIso } from "@/lib/format";
import { cn } from "@/lib/cn";
import { usePrefs, useSession } from "@/features/settings/api";
import { OUTCOMES, useJournalCompare, useJournalDetail, useJournalMutations } from "./api";

type Section = "history" | "evidence" | "reviews";
type Evidence = {
  captured?: boolean;
  reason?: string;
  captured_at?: string;
  price?: { value: string | null; currency?: string; market_time?: string; status?: string; message?: string | null };
  fundamentals?: { pe_ratio?: string | null; market_cap?: string | null; dividend_yield_percent?: string | null; status?: string; currency?: string };
  filings?: { status?: string; items?: { form: string; filing_date: string; accession: string; link?: string | null }[] };
};

const FIELDS: { key: string; label: string }[] = [
  { key: "title", label: "Title" },
  { key: "entry_date", label: "Date" },
  { key: "decision", label: "Decision" },
  { key: "conviction", label: "Conviction" },
  { key: "horizon", label: "Horizon" },
  { key: "thesis", label: "Thesis" },
  { key: "risks", label: "Risks" },
  { key: "invalidation", label: "Invalidation" },
];

const str = (v: unknown) => (v === null || v === undefined ? "" : String(v));

function VersionDiff({ a, b }: { a: JournalVersion; b: JournalVersion }) {
  const changed = FIELDS.filter((f) => str(a.content[f.key]) !== str(b.content[f.key]));
  if (!changed.length) return <p className="text-[13px] text-fg-3">No differences in the thesis fields.</p>;
  return (
    <div className="space-y-3">
      {changed.map((f) => (
        <div key={f.key}>
          <h4 className="text-xs font-semibold text-fg-2">{f.label}</h4>
          <div className="mt-1 rounded-[var(--radius-control)] border border-line-subtle bg-canvas/40 p-2 text-[13px] leading-5">
            {lineDiff(str(a.content[f.key]), str(b.content[f.key])).map((op, i) => (
              <div
                key={i}
                className={cn("whitespace-pre-wrap", op.type === "add" ? "bg-pos-soft text-pos" : op.type === "del" ? "bg-neg-soft text-neg line-through" : "text-fg-2")}
              >
                <span className="num mr-2 select-none" aria-hidden>{op.type === "add" ? "+" : op.type === "del" ? "−" : " "}</span>
                <span className="sr-only">{op.type === "add" ? "Added: " : op.type === "del" ? "Removed: " : ""}</span>
                {op.text || " "}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function History({ d }: { d: JournalDetail }) {
  const { data: prefs } = usePrefs();
  const versions = d.versions;
  const [from, setFrom] = useState(1);
  const [to, setTo] = useState(versions.length);
  useEffect(() => setTo(versions.length), [versions.length]);
  const a = versions.find((v) => v.version === from);
  const b = versions.find((v) => v.version === to);
  return (
    <div className="space-y-4">
      <ol className="space-y-2" aria-label="Versions">
        {[...versions].reverse().map((v) => (
          <li key={v.version} className="rounded-[var(--radius-control)] border border-line-subtle px-3 py-2 text-[13px]">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="num font-semibold text-fg">v{v.version}</span>
              <span className="text-xs text-fg-3">{formatInstant(v.created_at, prefs?.display_timezone)}</span>
              {v.version === versions.length && <Pill tone="accent" className="py-0">Current</Pill>}
            </div>
            <p className="mt-0.5 text-fg-2">{v.change_note ?? (v.version === 1 ? "Original note." : "")}</p>
          </li>
        ))}
      </ol>
      {versions.length > 1 ? (
        <div>
          <div className="mb-2 flex flex-wrap items-center gap-2 text-[13px]">
            <span className="text-fg-2">Compare</span>
            <Select aria-label="Compare from version" className="h-8 w-24" value={from} onChange={(e) => setFrom(Number(e.target.value))}>
              {versions.map((v) => <option key={v.version} value={v.version}>v{v.version}</option>)}
            </Select>
            <span className="text-fg-3">with</span>
            <Select aria-label="Compare with version" className="h-8 w-24" value={to} onChange={(e) => setTo(Number(e.target.value))}>
              {versions.map((v) => <option key={v.version} value={v.version}>v{v.version}</option>)}
            </Select>
          </div>
          {a && b && <VersionDiff a={a} b={b} />}
        </div>
      ) : (
        <p className="text-[13px] text-fg-3">One version so far. Edits that change the thesis add versions here; earlier versions are never changed.</p>
      )}
    </div>
  );
}

function EvidenceCard({ title, ev, tz }: { title: string; ev: Evidence | null | undefined; tz?: string }) {
  if (!ev || ev.captured === false) {
    return (
      <div className="rounded-[var(--radius-control)] border border-line-subtle p-3 text-[13px]">
        <h4 className="text-xs font-semibold text-fg-2">{title}</h4>
        <p className="mt-1 text-fg-3">{ev?.reason ?? "No evidence was captured."}</p>
      </div>
    );
  }
  const p = ev.price;
  const f = ev.fundamentals;
  return (
    <div className="rounded-[var(--radius-control)] border border-line-subtle p-3 text-[13px]">
      <h4 className="text-xs font-semibold text-fg-2">{title}</h4>
      <p className="text-xs text-fg-3">Captured {formatInstant(ev.captured_at, tz)}</p>
      <dl className="mt-2 space-y-1">
        <div className="flex justify-between gap-2">
          <dt className="text-fg-2">Price</dt>
          <dd className="num text-right">
            {p?.value ? formatMoney(p.value, p.currency) : DASH}
            <span className="block text-xs text-fg-3">{p?.value ? `${p.status} · market time ${formatInstant(p.market_time, tz)}` : (p?.message ?? p?.status)}</span>
          </dd>
        </div>
        <div className="flex justify-between gap-2"><dt className="text-fg-2">P/E</dt><dd className="num">{f?.pe_ratio ? `${Number(f.pe_ratio).toFixed(2)}×` : DASH}</dd></div>
        <div className="flex justify-between gap-2"><dt className="text-fg-2">Dividend yield</dt><dd className="num">{f?.dividend_yield_percent ? formatPercent(f.dividend_yield_percent, { signed: false }) : DASH}</dd></div>
      </dl>
      <h5 className="mt-2 text-xs font-medium text-fg-2">Recent SEC filings</h5>
      {ev.filings?.items?.length ? (
        <ul className="mt-1 space-y-0.5 text-xs">
          {ev.filings.items.map((x) => (
            <li key={x.accession}>
              {x.link ? <a className="text-accent-text underline decoration-accent/40 underline-offset-2 hover:decoration-accent" href={x.link} target="_blank" rel="noopener noreferrer">{x.form}</a> : x.form} · <span className="num">{formatSessionDate(x.filing_date)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-fg-3">{ev.filings?.status === "not_applicable" ? "Not a US registrant." : ev.filings?.status === "not_configured" ? "SEC data not configured." : "None captured."}</p>
      )}
    </div>
  );
}

function EvidenceTab({ d }: { d: JournalDetail }) {
  const { data: prefs } = usePrefs();
  const tz = prefs?.display_timezone;
  const [version, setVersion] = useState(1);
  const c = useJournalCompare(d.id, version);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-[13px]">
        <span className="text-fg-2">Evidence from</span>
        <Select aria-label="Evidence from version" className="h-8 w-28" value={version} onChange={(e) => setVersion(Number(e.target.value))}>
          {d.versions.map((v) => <option key={v.version} value={v.version}>v{v.version}{v.version === 1 ? " (original)" : ""}</option>)}
        </Select>
        <span className="text-fg-3">compared with today</span>
      </div>
      {c.isLoading ? (
        <SkeletonRows rows={4} />
      ) : c.isError ? (
        <ErrorState message={errorMessage(c.error)} onRetry={() => c.refetch()} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <EvidenceCard title={`Then (v${c.data!.version}, stored)`} ev={c.data!.then as Evidence} tz={tz} />
            <EvidenceCard title="Now (fetched for comparison, not stored)" ev={c.data!.now as Evidence} tz={tz} />
          </div>
          <div className="rounded-[var(--radius-control)] border border-line-subtle bg-canvas/40 p-3 text-[13px]">
            <p>
              <span className="text-fg-2">Since then ({c.data!.days_elapsed} days): </span>
              price {c.data!.price_change_pct === null ? <span className="text-fg-3">not compared</span> : <span className="num">{formatPercent(c.data!.price_change_pct)}</span>}
              {c.data!.filings_since.length > 0 && <> · {c.data!.filings_since.length} new SEC filing{c.data!.filings_since.length > 1 ? "s" : ""}</>}
            </p>
            <p className="mt-1 text-xs text-fg-3">{c.data!.price_note}</p>
            {c.data!.splits_since.length > 0 && <p className="mt-1 text-xs text-warn">Splits since: {c.data!.splits_since.map((s) => `${formatSessionDate(String(s.date))} ${String(s.description)}`).join("; ")}</p>}
          </div>
          <p className="text-xs text-fg-3">Stored snapshots never change; "now" is shown beside them and is not saved. Observed figures only: no cause is inferred.</p>
        </>
      )}
    </div>
  );
}

function Reviews({ d, readOnly }: { d: JournalDetail; readOnly: boolean }) {
  const { data: prefs } = usePrefs();
  const tz = prefs?.display_timezone;
  const m = useJournalMutations();
  const toast = useToast();
  const [outcome, setOutcome] = useState<string>("intact");
  const [notes, setNotes] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState<string | null>(null);
  const today = todayIso(tz);
  const label = (o: string) => OUTCOMES.find((x) => x.value === o)?.label ?? o;
  const submit = async () => {
    setError(null);
    if (next && next <= today) return setError("The next review must be after today.");
    try {
      await m.review.mutateAsync({ id: d.id, outcome, notes, next_review_date: next || null });
      toast("success", next ? `Review recorded; next review ${formatSessionDate(next)}.` : "Review recorded.");
      setNotes("");
      setNext("");
    } catch (err) {
      setError(errorMessage(err));
    }
  };
  return (
    <div className="space-y-4">
      {!readOnly && (
        <div className="rounded-[var(--radius-control)] border border-line-subtle p-3">
          <h4 className="text-[13px] font-semibold text-fg">{d.review_due ? "Review due" : "Record a review"}{d.review_date ? ` · scheduled ${formatSessionDate(d.review_date)}` : ""}</h4>
          <p className="mt-0.5 text-xs text-fg-3">Compare the current thesis (v{d.version}) with the evidence tab, then record what you concluded. The evidence at this moment is stored with the review.</p>
          {error && <InlineNotice tone="neg" className="mt-2"><span role="alert">{error}</span></InlineNotice>}
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <Field label="Outcome" required>
              {({ id }) => (
                <Select id={id} value={outcome} onChange={(e) => setOutcome(e.target.value)}>
                  {OUTCOMES.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </Select>
              )}
            </Field>
            <Field label="Next review" hint="Leave empty to take the note off the review queue.">
              {({ id, describedBy }) => <Input id={id} type="date" min={today} aria-describedby={describedBy} value={next} onChange={(e) => setNext(e.target.value)} />}
            </Field>
            <Field label="Review notes" className="sm:col-span-2">
              {({ id }) => <Textarea id={id} rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />}
            </Field>
          </div>
          <div className="mt-3 flex justify-end">
            <Button variant="primary" size="sm" loading={m.review.isPending} onClick={submit}>Complete review</Button>
          </div>
        </div>
      )}
      {d.reviews.length === 0 ? (
        <p className="text-[13px] text-fg-3">No reviews yet.</p>
      ) : (
        <ol className="space-y-2" aria-label="Review history">
          {d.reviews.map((r) => {
            const p = (r.evidence as Evidence | null)?.price;
            return (
              <li key={r.id} className="rounded-[var(--radius-control)] border border-line-subtle px-3 py-2 text-[13px]">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <Pill tone={r.outcome === "intact" ? "pos" : r.outcome === "invalidated" ? "neg" : r.outcome === "weakened" ? "warn" : "neutral"} className="py-0">{label(r.outcome)}</Pill>
                  <span className="text-xs text-fg-3">{formatInstant(r.reviewed_at, tz)} · thesis v{r.version}{r.scheduled_for ? ` · was due ${formatSessionDate(r.scheduled_for)}` : ""}</span>
                </div>
                {r.notes && <p className="mt-1 whitespace-pre-wrap text-fg-2">{r.notes}</p>}
                <p className="mt-1 text-xs text-fg-3">
                  Price at review {p?.value ? formatMoney(p.value, p.currency) : DASH}
                  {r.next_review_date ? ` · next review ${formatSessionDate(r.next_review_date)}` : " · no further review scheduled"}
                </p>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

export function JournalDetailDialog() {
  const { state, close } = useDialogs();
  const isOpen = state.kind === "journal-detail";
  const id = isOpen && state.kind === "journal-detail" ? state.id : null;
  const q = useJournalDetail(id);
  const { data: session } = useSession();
  const [section, setSection] = useState<Section>("history");
  useEffect(() => {
    if (isOpen && state.kind === "journal-detail") setSection(state.section ?? "history");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);
  const d = q.data;
  const title = useMemo(() => (d ? `${d.symbol} · ${d.title}` : "Journal note"), [d]);
  return (
    <Dialog
      open={isOpen}
      onOpenChange={(o) => !o && close()}
      title={title}
      description="Versions, evidence snapshots and reviews. What you wrote and what the data showed are kept as recorded."
      size="xl"
      footer={<Button variant="ghost" onClick={close}>Close</Button>}
    >
      {q.isLoading ? (
        <SkeletonRows rows={6} />
      ) : q.isError || !d ? (
        <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
      ) : (
        <div className="space-y-4">
          <Segmented<Section>
            label="Note sections"
            value={section}
            onChange={setSection}
            options={[
              { value: "history", label: `History (${d.versions.length})` },
              { value: "evidence", label: "Evidence" },
              { value: "reviews", label: `Reviews (${d.reviews.length})` },
            ]}
          />
          {section === "history" ? <History d={d} /> : section === "evidence" ? <EvidenceTab d={d} /> : <Reviews d={d} readOnly={Boolean(session?.read_only)} />}
        </div>
      )}
    </Dialog>
  );
}
