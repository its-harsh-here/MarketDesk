import { BookOpen, CalendarCheck, History, Pencil, Plus, Search, X } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { useDialogs } from "@/app/dialogs";
import { Panel } from "@/components/ui/Panel";
import { Button, IconButton } from "@/components/ui/Button";
import { Input, Select } from "@/components/ui/Form";
import { Pill } from "@/components/ui/Badges";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/States";
import { errorMessage, type JournalEntry } from "@/lib/api/client";
import { formatSessionDate } from "@/lib/format";
import { useDebounced } from "@/lib/hooks";
import { cn } from "@/lib/cn";
import { useSession } from "@/features/settings/api";
import { useJournal } from "./api";

function Section({ label, text }: { label: string; text: string }) {
  if (!text.trim()) return null;
  return (
    <div>
      <h4 className="text-xs font-semibold tracking-wide text-fg-3 uppercase">{label}</h4>
      {/* Plain text only: rendered as text nodes, never as HTML. */}
      <p className="mt-1 text-[13px] leading-5 whitespace-pre-wrap text-fg-2">{text}</p>
    </div>
  );
}

function ReviewQueue({ readOnly }: { readOnly: boolean }) {
  const due = useJournal({ due: true }, 20);
  const { open } = useDialogs();
  if (!due.data?.items.length) return null;
  return (
    <Panel title="Review queue" titleId="review-q" meta={`${due.data.total} due`}>
      <ul className="divide-y divide-line-subtle" aria-label="Notes due for review">
        {due.data.items.map((e) => (
          <li key={e.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-[13px]">
            {/* On phones the symbol and title take the first line, the due date and button the second. */}
            <span className="flex min-w-0 basis-full items-center gap-3 sm:flex-1 sm:basis-auto">
              <span className="num shrink-0 font-semibold text-fg">{e.symbol}</span>
              <span className="min-w-0 flex-1 truncate text-fg-2">{e.title}</span>
            </span>
            <span className="text-xs text-fg-3">due {formatSessionDate(e.review_date)}</span>
            <Button size="sm" variant={readOnly ? "ghost" : "primary"} icon={<CalendarCheck className="size-3.5" aria-hidden />} onClick={() => open({ kind: "journal-detail", id: e.id, section: "reviews" })}>
              {readOnly ? "View" : "Review"}
            </Button>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function EntryCard({ e, readOnly }: { e: JournalEntry; readOnly: boolean }) {
  const { open } = useDialogs();
  return (
    <article className="rounded-[var(--radius-panel)] border border-line-subtle bg-panel p-[var(--panel-pad)]" aria-labelledby={`je-${e.id}`}>
      <header className="flex flex-wrap items-start gap-x-3 gap-y-1">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-xs text-fg-3">
            <Link to={`/instrument/${encodeURIComponent(e.symbol)}`} className="num font-semibold text-fg-2 hover:text-accent-text">{e.symbol}</Link>
            <span>{formatSessionDate(e.entry_date)}</span>
            {e.review_date && (
              <Pill tone={e.review_due ? "accent" : "neutral"} className="py-0">
                {e.review_due ? "Review due" : "Review"} {formatSessionDate(e.review_date)}
              </Pill>
            )}
          </div>
          <h3 id={`je-${e.id}`} className="mt-1 text-[15px] font-semibold text-fg">{e.title}</h3>
          {(e.decision || e.conviction || e.horizon) && (
            <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-fg-2">
              {e.decision && <Pill tone="info" className="py-0">Your decision: {e.decision.charAt(0) + e.decision.slice(1).toLowerCase()}</Pill>}
              {e.conviction && <span>Conviction {e.conviction}/5</span>}
              {e.horizon && <span>Horizon {e.horizon}</span>}
            </p>
          )}
        </div>
        <Button size="sm" variant="ghost" icon={<History className="size-3.5" aria-hidden />} onClick={() => open({ kind: "journal-detail", id: e.id })} aria-label={`History, evidence and reviews for ${e.title}`}>
          v{e.version}
        </Button>
        {!readOnly && (
          <IconButton size="sm" label={`Edit note ${e.title}`} onClick={() => open({ kind: "journal", editing: e })}>
            <Pencil className="size-3.5" aria-hidden />
          </IconButton>
        )}
      </header>
      <div className="mt-3 grid gap-3 md:grid-cols-3">
        <Section label="Thesis" text={e.thesis} />
        <Section label="Risks" text={e.risks} />
        <Section label="Invalidation" text={e.invalidation} />
      </div>
      {e.tags.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-1.5" aria-label="Tags">
          {e.tags.map((t) => (
            <li key={t}><Link to={`/journal?tag=${encodeURIComponent(t)}`}><Pill className="py-0 hover:border-fg-3">#{t}</Pill></Link></li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-[11px] text-fg-3">Your note · version {e.version} · not investment advice</p>
    </article>
  );
}

export function JournalPage() {
  const [params, setParams] = useSearchParams();
  const symbol = params.get("symbol") ?? "";
  const tag = params.get("tag") ?? "";
  const [text, setText] = useState(params.get("q") ?? "");
  const q = useDebounced(text, 250);
  const journal = useJournal({ symbol: symbol || undefined, tag: tag || undefined, q: q || undefined });
  const { open } = useDialogs();
  const { data: session } = useSession();
  const readOnly = Boolean(session?.read_only);
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    setParams(next, { replace: true });
  };
  const filtered = Boolean(symbol || tag || q);

  return (
    <div className="space-y-4 p-4 md:p-6">
      <ReviewQueue readOnly={readOnly} />
      <Panel
        title="Journal"
        titleId="journal-h"
        meta={journal.data ? `${journal.data.total} note(s)` : undefined}
        actions={!readOnly && <Button size="sm" variant="primary" icon={<Plus className="size-3.5" aria-hidden />} onClick={() => open({ kind: "journal", symbol: symbol || undefined })}>New note</Button>}
      >
        <div className="flex flex-wrap items-center gap-2" role="search" aria-label="Filter journal">
          <div className="relative min-w-48 flex-1">
            <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-fg-3" />
            <Input aria-label="Search notes" placeholder="Search title, thesis, risks…" value={text} onChange={(e) => setText(e.target.value)} className="pl-9" />
          </div>
          <Select aria-label="Filter by symbol" className="w-40" value={symbol} onChange={(e) => set("symbol", e.target.value)}>
            <option value="">All symbols</option>
            {(journal.data?.symbols ?? []).concat(symbol && !journal.data?.symbols.includes(symbol) ? [symbol] : []).map((s) => <option key={s} value={s}>{s}</option>)}
          </Select>
          <Select aria-label="Filter by tag" className="w-36" value={tag} onChange={(e) => set("tag", e.target.value)}>
            <option value="">All tags</option>
            {(journal.data?.tags ?? []).map((t) => <option key={t} value={t}>#{t}</option>)}
          </Select>
          {filtered && (
            <Button size="sm" variant="ghost" icon={<X className="size-3.5" aria-hidden />} onClick={() => { setText(""); setParams({}, { replace: true }); }}>
              Clear
            </Button>
          )}
        </div>
      </Panel>
      {journal.isLoading ? (
        <SkeletonRows rows={6} />
      ) : journal.isError ? (
        <ErrorState message={errorMessage(journal.error)} onRetry={() => journal.refetch()} />
      ) : !journal.data!.items.length ? (
        <Panel>
          <EmptyState
            icon={<BookOpen aria-hidden />}
            title={filtered ? "No notes match these filters" : "Start your investment journal"}
            actions={!readOnly && !filtered && <Button variant="primary" onClick={() => open({ kind: "journal" })}>Write a note</Button>}
          >
            {filtered ? "Try another symbol or tag." : "Link a symbol to a dated thesis, its risks, the conditions that would invalidate it, tags and a review date."}
          </EmptyState>
        </Panel>
      ) : (
        <div className={cn("grid gap-3", journal.isFetching && "opacity-80")}>
          {journal.data!.items.map((e) => <EntryCard key={e.id} e={e} readOnly={readOnly} />)}
        </div>
      )}
    </div>
  );
}
