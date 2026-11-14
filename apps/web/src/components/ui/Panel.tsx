import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface PanelProps {
  title?: ReactNode;
  titleId?: string;
  meta?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  as?: "section" | "div" | "aside";
  refreshing?: boolean;
  /**
   * For rich titles (symbol + price): the title keeps its natural width, the meta line wraps below it, and the
   * actions move to their own line when the row is too narrow, instead of clipping the title.
   */
  wrapHeader?: boolean;
  /** Decoration: a light beam travels round the edge (for a page's principal panel). */
  beam?: boolean;
}

/** A bordered surface with an optional header row. Panels label themselves for screen readers. */
export function Panel({ title, titleId, meta, actions, children, className, bodyClassName, as = "section", refreshing, wrapHeader, beam }: PanelProps) {
  const Tag = as;
  return (
    <Tag
      aria-labelledby={title && titleId ? titleId : undefined}
      className={cn("md-panel relative flex min-w-0 flex-col rounded-[var(--radius-panel)] border border-line-subtle bg-panel", beam && "fx-beam", className)}
    >
      {beam && <span className="beam" aria-hidden />}
      {(title || actions || meta) && (
        <header className="flex min-h-12 flex-wrap items-center gap-x-3 gap-y-1 border-b border-line-subtle px-[var(--panel-pad)] py-2">
          <div className={cn("flex min-w-0 items-baseline", wrapHeader ? "flex-[1_1_16rem] flex-wrap gap-x-3 gap-y-0.5" : "flex-1 gap-3")}>
            {title && (
              <h2 id={titleId} className="max-w-full shrink-0 truncate text-[13px] font-semibold tracking-wide text-fg">
                {title}
              </h2>
            )}
            {meta && <div className="min-w-0 max-w-full truncate text-xs text-fg-3">{meta}</div>}
          </div>
          {refreshing && (
            <span className="flex items-center gap-1.5 text-xs text-fg-3" role="status">
              <span className="fx-live size-1.5 rounded-full bg-info" />
              Refreshing
            </span>
          )}
          {actions && <div className="ml-auto flex max-w-full min-w-0 flex-wrap items-center justify-end gap-1">{actions}</div>}
        </header>
      )}
      <div className={cn("min-w-0 flex-1", bodyClassName ?? "p-[var(--panel-pad)]")}>{children}</div>
    </Tag>
  );
}
