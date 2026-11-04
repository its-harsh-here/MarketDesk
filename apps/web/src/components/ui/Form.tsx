import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

/** Full width unless the caller sets its own width (`w-40`, …): `cn` does not merge conflicting utilities. */
const width = (className?: string) => (/(^|\s)w-/.test(className ?? "") ? "" : "w-full");

const control =
  "rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-fg placeholder:text-fg-3 transition-colors duration-150 hover:border-fg-3/60 focus:border-accent focus:outline-none focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--focus)] disabled:opacity-60 aria-[invalid=true]:border-neg";

/** Label + control + hint + error, with aria-describedby wiring. */
export function Field({
  label,
  hint,
  error,
  children,
  className,
  required,
}: {
  label: string;
  hint?: ReactNode;
  error?: string;
  children: (ids: { id: string; describedBy?: string; invalid: boolean }) => ReactNode;
  className?: string;
  required?: boolean;
}) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errId = error ? `${id}-err` : undefined;
  const describedBy = [hintId, errId].filter(Boolean).join(" ") || undefined;
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={id} className="text-[13px] font-medium text-fg-2">
        {label}
        {required && <span className="text-fg-3"> (required)</span>}
      </label>
      {children({ id, describedBy, invalid: Boolean(error) })}
      {hint && !error && (
        <p id={hintId} className="text-xs leading-4 text-fg-3">
          {hint}
        </p>
      )}
      {error && (
        <p id={errId} className="text-xs leading-4 text-neg" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return <input ref={ref} className={cn(control, width(className), "h-9 max-md:h-11", className)} {...rest} />;
});

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, children, ...rest }, ref) {
  return (
    <select ref={ref} className={cn(control, width(className), "h-9 cursor-pointer pr-8 max-md:h-11", className)} {...rest}>
      {children}
    </select>
  );
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...rest }, ref) {
  return <textarea ref={ref} className={cn(control, width(className), "min-h-24 py-2 leading-5", className)} {...rest} />;
});
