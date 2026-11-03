import { useEffect, useId, useRef, useState } from "react";
import { Search } from "lucide-react";
import { useSymbolSearch } from "@/features/market/api";
import { useDebounced } from "@/lib/hooks";
import { cn } from "@/lib/cn";
import type { Instrument } from "@/lib/api/client";

const SYMBOLISH = /^[\^A-Za-z0-9:.\-&=]{1,24}$/;

/**
 * Combobox for choosing an instrument by name or symbol.
 * Results are only selectable once they belong to what is currently typed, so a quick Enter can
 * never pick a stale result or the raw text while the search is still running.
 */
export function SymbolPicker({
  value,
  onChange,
  id,
  describedBy,
  invalid,
  placeholder = "Search name or symbol",
  autoFocus,
}: {
  value: string;
  onChange: (symbol: string, inst?: Instrument) => void;
  id?: string;
  describedBy?: string;
  invalid?: boolean;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  const [text, setText] = useState(value);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [pendingEnter, setPendingEnter] = useState(false);
  const listId = useId();
  const debounced = useDebounced(text, 200);
  const search = useSymbolSearch(open ? debounced : "");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => setText(value), [value]);

  const typed = text.trim();
  const settled = Boolean(typed) && debounced.trim() === typed && !search.isFetching && search.data !== undefined;
  const results = settled ? (search.data?.results ?? []) : [];
  const upper = typed.toUpperCase();
  const options: { symbol: string; inst?: Instrument; label: string }[] = results.map((r) => ({
    symbol: r.symbol,
    inst: r,
    label: r.name ?? r.symbol,
  }));
  const hasListing = results.some((r) => r.symbol === upper || r.symbol.startsWith(`${upper}.`));
  if (settled && SYMBOLISH.test(upper) && !hasListing) {
    options.push({ symbol: upper, label: `Use “${upper}” as typed` });
  }

  const choose = (i: number) => {
    const o = options[i];
    if (!o) return;
    onChange(o.symbol, o.inst);
    setText(o.symbol);
    setOpen(false);
    setPendingEnter(false);
  };

  // Enter pressed while the search was still running: pick the top result once it arrives.
  useEffect(() => {
    if (pendingEnter && settled) {
      if (options.length) choose(0);
      else setPendingEnter(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingEnter, settled]);

  const searching = open && Boolean(typed) && !settled;

  return (
    <div className="relative">
      <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-fg-3" />
      <input
        ref={inputRef}
        id={id}
        role="combobox"
        aria-expanded={open && (options.length > 0 || searching)}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && options[active] ? `${listId}-${active}` : undefined}
        aria-describedby={describedBy}
        aria-invalid={invalid || undefined}
        aria-busy={searching || undefined}
        autoComplete="off"
        spellCheck={false}
        autoFocus={autoFocus}
        placeholder={placeholder}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
          setActive(0);
          setPendingEnter(false);
          if (!e.target.value) onChange("");
        }}
        onFocus={() => text && setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 120)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setOpen(true);
            setActive((a) => Math.min(a + 1, Math.max(options.length - 1, 0)));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((a) => Math.max(a - 1, 0));
          } else if (e.key === "Enter" && open && typed) {
            e.preventDefault();
            if (settled) choose(active);
            else setPendingEnter(true);
          } else if (e.key === "Escape" && open) {
            e.stopPropagation();
            setOpen(false);
          }
        }}
        className={cn(
          "h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated pr-3 pl-9 text-sm text-fg placeholder:text-fg-3 focus:border-accent focus:outline-none max-md:h-11",
          invalid && "border-neg",
        )}
      />
      {open && (options.length > 0 || searching) && (
        <ul id={listId} role="listbox" className="scrollbar-thin absolute top-full right-0 left-0 z-30 mt-1 max-h-64 overflow-y-auto rounded-[var(--radius-control)] border border-line bg-elevated py-1 shadow-[var(--shadow-pop)]">
          {searching && (
            <li role="presentation" className="px-3 py-2 text-[13px] text-fg-3" aria-live="polite">
              Searching Yahoo for “{typed}”…
            </li>
          )}
          {!searching &&
            options.map((o, i) => (
              <li
                key={o.symbol + i}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === active}
                onMouseDown={(e) => {
                  e.preventDefault();
                  choose(i);
                }}
                onMouseEnter={() => setActive(i)}
                className={cn("flex cursor-pointer items-center gap-3 px-3 py-2 text-[13px]", i === active && "bg-hover")}
              >
                <span className="num w-28 shrink-0 truncate font-semibold text-fg">{o.symbol}</span>
                <span className="min-w-0 flex-1 truncate text-fg-2">{o.label}</span>
                {o.inst && (
                  <span className="shrink-0 text-xs text-fg-3">{[o.inst.exchange, o.inst.currency].filter(Boolean).join(" · ") || "—"}</span>
                )}
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}
