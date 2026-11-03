import { CircleAlert, Check, Info, X } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";

type ToastTone = "success" | "error" | "info";
interface ToastItem {
  id: number;
  tone: ToastTone;
  text: string;
}

const Ctx = createContext<(tone: ToastTone, text: string) => void>(() => {});

/** Toasts only supplement inline status; every error is also shown where it happened. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const seq = useRef(0);
  const push = useCallback((tone: ToastTone, text: string) => {
    const id = ++seq.current;
    setItems((xs) => [...xs.slice(-3), { id, tone, text }]);
    window.setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), tone === "error" ? 7000 : 4000);
  }, []);
  const value = useMemo(() => push, [push]);
  return (
    <Ctx.Provider value={value}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed right-4 bottom-20 z-[60] flex w-[min(360px,calc(100vw-32px))] flex-col gap-2 md:bottom-4">
        {items.map((t) => {
          const Icon = t.tone === "success" ? Check : t.tone === "error" ? CircleAlert : Info;
          return (
            <div
              key={t.id}
              role={t.tone === "error" ? "alert" : "status"}
              className="anim-pop pointer-events-auto flex items-start gap-2.5 rounded-[var(--radius-control)] border border-line bg-elevated px-3 py-2.5 text-[13px] text-fg shadow-[var(--shadow-pop)]"
            >
              <Icon aria-hidden className={cn("mt-0.5 size-4 shrink-0", t.tone === "success" ? "text-pos" : t.tone === "error" ? "text-neg" : "text-info")} />
              <span className="flex-1 leading-5">{t.text}</span>
              <button type="button" aria-label="Dismiss" className="text-fg-3 hover:text-fg" onClick={() => setItems((xs) => xs.filter((x) => x.id !== t.id))}>
                <X className="size-3.5" aria-hidden />
              </button>
            </div>
          );
        })}
      </div>
    </Ctx.Provider>
  );
}

export function useToast() {
  return useContext(Ctx);
}
