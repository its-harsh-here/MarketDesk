import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { Alert, JournalEntry, Transaction } from "@/lib/api/client";

export type DialogState =
  | { kind: "none" }
  | { kind: "palette" }
  | { kind: "shortcuts" }
  | { kind: "transaction"; editing?: Transaction; symbol?: string; type?: Transaction["type"] }
  | { kind: "import" }
  | { kind: "alert"; editing?: Alert; symbol?: string; price?: string }
  | { kind: "journal"; editing?: JournalEntry; symbol?: string }
  | { kind: "add-symbol"; watchlistId: number }
  | { kind: "new-watchlist" };

interface Ctx {
  state: DialogState;
  open: (s: DialogState) => void;
  close: () => void;
}

const DialogCtx = createContext<Ctx>({ state: { kind: "none" }, open: () => {}, close: () => {} });

export function DialogProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<DialogState>({ kind: "none" });
  const open = useCallback((s: DialogState) => setState(s), []);
  const close = useCallback(() => setState({ kind: "none" }), []);
  const value = useMemo(() => ({ state, open, close }), [state, open, close]);
  return <DialogCtx.Provider value={value}>{children}</DialogCtx.Provider>;
}

export function useDialogs() {
  return useContext(DialogCtx);
}
