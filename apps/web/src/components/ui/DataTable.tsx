import { ChevronDown, ChevronRight, ChevronUp } from "lucide-react";
import { useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { useMediaQuery } from "@/lib/hooks";

export interface Column<T> {
  key: string;
  header: ReactNode;
  srHeader?: string;
  align?: "left" | "right" | "center";
  render: (row: T) => ReactNode;
  sortable?: boolean;
  width?: string;
  className?: string;
  hideBelow?: "lg" | "xl" | "2xl";
  /** Shown in the expandable details on phones. */
  mobileLabel?: string;
}

export interface SortState {
  key: string;
  dir: "asc" | "desc";
}

interface DataTableProps<T> {
  caption: string;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  sort?: SortState | null;
  onSortChange?: (s: SortState) => void;
  /** Phone layout: a legible summary row; other columns go in an expandable details list. */
  mobileSummary?: (row: T) => ReactNode;
  mobileDetailKeys?: string[];
  rowClassName?: (row: T) => string | undefined;
  dense?: boolean;
  footer?: ReactNode;
}

export function DataTable<T>({
  caption,
  columns,
  rows,
  rowKey,
  onRowClick,
  sort,
  onSortChange,
  mobileSummary,
  mobileDetailKeys,
  rowClassName,
  footer,
}: DataTableProps<T>) {
  const phone = useMediaQuery("(max-width: 639px)");
  const [open, setOpen] = useState<Record<string, boolean>>({});

  // Clickable rows are also keyboard rows: Tab reaches them, ↑/↓ move between them, Enter or Space opens one.
  const rowKeys = (row: T, openRow: () => void) => (e: React.KeyboardEvent<HTMLElement>) => {
    if (e.target !== e.currentTarget) return; // a control inside the row (star, details) handles its own keys
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openRow();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      const items = Array.from(e.currentTarget.parentElement?.querySelectorAll<HTMLElement>('[data-row="1"]') ?? []);
      const i = items.indexOf(e.currentTarget);
      const next = items[e.key === "ArrowDown" ? i + 1 : i - 1];
      if (next) {
        e.preventDefault();
        next.focus();
      }
    }
    void row;
  };
  const focusRing = "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--focus)]";

  if (phone && mobileSummary) {
    const detailCols = columns.filter((c) => (mobileDetailKeys ? mobileDetailKeys.includes(c.key) : true));
    return (
      <ul aria-label={caption} className="divide-y divide-line-subtle">
        {rows.map((row) => {
          const k = rowKey(row);
          const expanded = Boolean(open[k]);
          return (
            <li key={k} className={rowClassName?.(row)}>
              {/* The row is a tap target for touch; keyboard and screen readers use the Open button, so no control is
                  nested inside another (the summary can hold its own buttons, e.g. a watchlist star). */}
              <div
                className={cn("flex min-h-14 items-center gap-2 px-4 py-2", onRowClick && "cursor-pointer active:bg-hover")}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                <div className="min-w-0 flex-1">{mobileSummary(row)}</div>
                {onRowClick && (
                  <button
                    type="button"
                    aria-label={/^\d+$/.test(String(k)) ? "Open" : `Open ${k}`}
                    className={cn("flex size-11 shrink-0 items-center justify-center rounded-md text-fg-3 hover:bg-hover", focusRing)}
                    onClick={(e) => {
                      e.stopPropagation();
                      onRowClick(row);
                    }}
                  >
                    <ChevronRight className="size-4" aria-hidden />
                  </button>
                )}
                {detailCols.length > 0 && (
                  <button
                    type="button"
                    aria-expanded={expanded}
                    aria-label={expanded ? "Hide details" : "Show details"}
                    className="flex size-11 shrink-0 items-center justify-center rounded-md text-fg-3 hover:bg-hover"
                    onClick={(e) => {
                      e.stopPropagation();
                      setOpen((o) => ({ ...o, [k]: !o[k] }));
                    }}
                  >
                    {expanded ? <ChevronUp className="size-4" aria-hidden /> : <ChevronDown className="size-4" aria-hidden />}
                  </button>
                )}
              </div>
              {expanded && (
                <dl className="grid grid-cols-2 gap-x-4 gap-y-2 bg-canvas/40 px-4 pt-1 pb-3 text-[13px]">
                  {detailCols.map((c) => (
                    <div key={c.key} className="min-w-0">
                      <dt className="text-xs text-fg-3">{c.mobileLabel ?? (typeof c.header === "string" ? c.header : c.srHeader ?? c.key)}</dt>
                      <dd className="mt-0.5 min-w-0 text-fg">{c.render(row)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <div className="scroll-x scrollbar-thin relative w-full overflow-x-auto" tabIndex={onRowClick ? undefined : 0}>
      <table className="w-full min-w-full text-[13px]">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-line-subtle">
            {columns.map((c) => {
              const active = sort?.key === c.key;
              const ariaSort = active ? (sort!.dir === "asc" ? "ascending" : "descending") : c.sortable ? "none" : undefined;
              return (
                <th
                  key={c.key}
                  scope="col"
                  aria-sort={ariaSort}
                  style={c.width ? { width: c.width } : undefined}
                  className={cn(
                    "h-9 px-3 text-xs font-medium whitespace-nowrap text-fg-3 first:pl-[var(--panel-pad)] last:pr-[var(--panel-pad)]",
                    c.align === "right" ? "text-right" : c.align === "center" ? "text-center" : "text-left",
                    c.hideBelow === "lg" && "max-lg:hidden",
                    c.hideBelow === "xl" && "max-xl:hidden",
                    c.hideBelow === "2xl" && "max-2xl:hidden",
                  )}
                >
                  {c.sortable && onSortChange ? (
                    <button
                      type="button"
                      className={cn("inline-flex items-center gap-1 rounded hover:text-fg", active && "text-fg")}
                      onClick={() => onSortChange({ key: c.key, dir: active && sort!.dir === "desc" ? "asc" : "desc" })}
                    >
                      {c.header}
                      {c.srHeader && <span className="sr-only">{c.srHeader}</span>}
                      {active ? (sort!.dir === "asc" ? <ChevronUp className="size-3" aria-hidden /> : <ChevronDown className="size-3" aria-hidden />) : null}
                    </button>
                  ) : (
                    <>
                      {c.header}
                      {c.srHeader && <span className="sr-only">{c.srHeader}</span>}
                    </>
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              tabIndex={onRowClick ? 0 : undefined}
              data-row={onRowClick ? "1" : undefined}
              onKeyDown={onRowClick ? rowKeys(row, () => onRowClick(row)) : undefined}
              className={cn(
                "border-b border-line-subtle last:border-b-0",
                onRowClick && cn("cursor-pointer hover:bg-hover/70 focus-visible:bg-hover/70", focusRing),
                rowClassName?.(row),
              )}
              style={{ height: "var(--row-h)" }}
            >
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={cn(
                    "px-3 py-1.5 align-middle first:pl-[var(--panel-pad)] last:pr-[var(--panel-pad)]",
                    c.align === "right" ? "text-right" : c.align === "center" ? "text-center" : "text-left",
                    c.hideBelow === "lg" && "max-lg:hidden",
                    c.hideBelow === "xl" && "max-xl:hidden",
                    c.hideBelow === "2xl" && "max-2xl:hidden",
                    c.className,
                  )}
                >
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        {footer && <tfoot>{footer}</tfoot>}
      </table>
    </div>
  );
}
