import { CircleAlert, CloudOff, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Button } from "./Button";

export function Skeleton({ className, style }: { className?: string; style?: React.CSSProperties }) {
  return <div aria-hidden className={cn("skeleton", className)} style={style} />;
}

export function SkeletonRows({ rows = 6, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)} role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-4 w-16" />
        </div>
      ))}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  children,
  actions,
  className,
}: {
  icon?: ReactNode;
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-2 px-6 py-10 text-center", className)}>
      {icon && <div className="mb-1 text-fg-3 [&_svg]:size-6">{icon}</div>}
      <p className="text-sm font-semibold text-fg">{title}</p>
      {children && <div className="max-w-sm text-[13px] leading-5 text-fg-2">{children}</div>}
      {actions && <div className="mt-3 flex flex-wrap justify-center gap-2">{actions}</div>}
    </div>
  );
}

export function ErrorState({
  title = "Could not load this panel",
  message,
  onRetry,
  offline,
  className,
}: {
  title?: string;
  message?: string;
  onRetry?: () => void;
  offline?: boolean;
  className?: string;
}) {
  return (
    <div role="alert" className={cn("flex flex-col items-center justify-center gap-2 px-6 py-8 text-center", className)}>
      <div className="text-neg [&_svg]:size-6">{offline ? <CloudOff aria-hidden /> : <CircleAlert aria-hidden />}</div>
      <p className="text-sm font-semibold text-fg">{title}</p>
      {message && <p className="max-w-sm text-[13px] leading-5 text-fg-2">{message}</p>}
      {onRetry && (
        <Button size="sm" className="mt-2" icon={<RefreshCw className="size-3.5" aria-hidden />} onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function InlineNotice({ tone = "info", children, className }: { tone?: "info" | "warn" | "neg"; children: ReactNode; className?: string }) {
  const tones = {
    info: "border-info/30 bg-info-soft text-fg-2",
    warn: "border-warn/40 bg-warn-soft text-fg",
    neg: "border-neg/40 bg-neg-soft text-fg",
  };
  return <div className={cn("rounded-[var(--radius-control)] border px-3 py-2 text-[13px] leading-5", tones[tone], className)}>{children}</div>;
}
