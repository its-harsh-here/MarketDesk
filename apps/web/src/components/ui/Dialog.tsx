import * as RD from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Button, IconButton } from "./Button";
import { errorMessage } from "@/lib/api/client";

/** Accessible modal: focus trap, Escape to close, focus returns to the trigger (Radix). */
export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
}) {
  const widths = { sm: "sm:max-w-sm", md: "sm:max-w-lg", lg: "sm:max-w-2xl", xl: "sm:max-w-4xl" };
  return (
    <RD.Root open={open} onOpenChange={onOpenChange}>
      <RD.Portal>
        <RD.Overlay className="anim-overlay fixed inset-0 z-40 bg-[var(--overlay)]" />
        <RD.Content
          className={cn(
            "anim-pop fixed z-50 flex max-h-[min(92dvh,860px)] w-full flex-col border border-line bg-panel shadow-[var(--shadow-pop)]",
            "inset-x-0 bottom-0 rounded-t-2xl sm:inset-auto sm:top-1/2 sm:left-1/2 sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-[var(--radius-panel)]",
            widths[size],
          )}
        >
          <div className="flex items-start gap-3 border-b border-line-subtle px-5 py-4">
            <div className="min-w-0 flex-1">
              <RD.Title className="text-base font-semibold text-fg">{title}</RD.Title>
              {description ? (
                <RD.Description className="mt-1 text-[13px] leading-5 text-fg-2">{description}</RD.Description>
              ) : (
                <RD.Description className="sr-only">{title}</RD.Description>
              )}
            </div>
            <RD.Close asChild>
              <IconButton label="Close dialog" size="sm">
                <X className="size-4" aria-hidden />
              </IconButton>
            </RD.Close>
          </div>
          <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer && <div className="safe-bottom flex flex-wrap justify-end gap-2 border-t border-line-subtle px-5 py-3">{footer}</div>}
        </RD.Content>
      </RD.Portal>
    </RD.Root>
  );
}

/** Confirmation for destructive actions; shows the server error inline if the write fails. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  body,
  confirmLabel = "Delete",
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  body: ReactNode;
  confirmLabel?: string;
  onConfirm: () => Promise<unknown>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) setError(null);
        onOpenChange(o);
      }}
      title={title}
      size="sm"
      footer={
        <>
          <RD.Close asChild>
            <Button variant="ghost">Cancel</Button>
          </RD.Close>
          <Button
            variant="danger"
            loading={busy}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                await onConfirm();
                onOpenChange(false);
              } catch (e) {
                setError(errorMessage(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="text-[13px] leading-5 text-fg-2">{body}</div>
      {error && (
        <p role="alert" className="mt-3 text-[13px] text-neg">
          {error}
        </p>
      )}
    </Dialog>
  );
}
