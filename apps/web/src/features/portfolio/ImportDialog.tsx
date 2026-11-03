import { FileUp } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useDialogs } from "@/app/dialogs";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Pill } from "@/components/ui/Badges";
import { InlineNotice } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { errorMessage, type ImportPreview } from "@/lib/api/client";
import { cn } from "@/lib/cn";
import { useTransactionMutations } from "./api";

const TEMPLATE = [
  "date,type,symbol,quantity,price,fees,amount,currency,split_from,split_to,notes",
  "2026-01-02,DEPOSIT,,,,,10000,INR,,,Initial funding",
  "2026-01-03,BUY,RELIANCE.NS,10,1250.50,20,,INR,,,",
  "2026-01-05,SELL,RELIANCE.NS,5,1290,20,,INR,,,",
].join("\n");

export function ImportDialog() {
  const { state, close } = useDialogs();
  const isOpen = state.kind === "import";
  const { preview, commit } = useTransactionMutations();
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ImportPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen) {
      setFile(null);
      setResult(null);
      setError(null);
      setDone(null);
    }
  }, [isOpen]);

  const runPreview = async (f: File) => {
    setError(null);
    setResult(null);
    setDone(null);
    try {
      setResult(await preview.mutateAsync(f));
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const runCommit = async () => {
    if (!result?.token) return;
    setError(null);
    try {
      const r = await commit.mutateAsync(result.token);
      const msg = `Imported ${r.imported} transaction(s)${r.skipped_duplicates ? `, skipped ${r.skipped_duplicates} duplicate(s)` : ""}.`;
      setDone(msg);
      setResult(null);
      toast("success", msg);
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(o) => !o && close()}
      title="Import transactions (CSV)"
      description="Upload a file in the canonical MarketDesk format. You will see every row before anything is written; the import is all-or-nothing."
      size="xl"
      footer={
        <>
          <Button variant="ghost" onClick={close}>{done ? "Close" : "Cancel"}</Button>
          {result && (
            <Button variant="primary" disabled={!result.can_import} loading={commit.isPending} onClick={runCommit} title={result.blocking_reason ?? undefined}>
              {result.can_import ? `Import ${result.ok_rows} row(s)` : "Cannot import"}
            </Button>
          )}
        </>
      }
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={input}
            type="file"
            accept=".csv,text/csv"
            className="sr-only"
            id="csv-file"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setFile(f);
              if (f) runPreview(f);
              e.target.value = "";
            }}
          />
          <Button icon={<FileUp className="size-4" aria-hidden />} onClick={() => input.current?.click()} loading={preview.isPending}>
            {file ? "Choose another file" : "Choose CSV file"}
          </Button>
          {file && <span className="num text-[13px] text-fg-2">{file.name}</span>}
          <a
            className="ml-auto text-[13px] text-accent-text hover:underline"
            href={`data:text/csv;charset=utf-8,${encodeURIComponent(TEMPLATE)}`}
            download="marketdesk-template.csv"
          >
            Download template
          </a>
        </div>
        <details className="rounded-[var(--radius-control)] border border-line-subtle bg-canvas/40 px-3 py-2 text-[13px] text-fg-2">
          <summary className="cursor-pointer text-fg">Canonical columns</summary>
          <p className="mt-2 leading-5">
            <code className="num text-xs text-fg">date,type,symbol,quantity,price,fees,amount,currency,split_from,split_to,notes</code> — dates as YYYY-MM-DD; types DEPOSIT, WITHDRAWAL, BUY, SELL, DIVIDEND or SPLIT; plain numbers without thousands separators; currency INR (blank means INR). Enter trades with their original quantities; a SPLIT row applies a split once. Rows identical to existing transactions (including notes) are treated as duplicates and skipped.
          </p>
        </details>
        {error && <InlineNotice tone="neg"><span role="alert">{error}</span></InlineNotice>}
        {done && <InlineNotice tone="info"><span role="status">{done}</span></InlineNotice>}
        {result && (
          <>
            <div className="flex flex-wrap items-center gap-2 text-[13px]" role="status">
              <Pill>{result.total_rows} rows</Pill>
              <Pill tone="pos">{result.ok_rows} new</Pill>
              <Pill tone={result.duplicate_rows ? "warn" : "neutral"}>{result.duplicate_rows} duplicate</Pill>
              <Pill tone={result.error_rows ? "neg" : "neutral"}>{result.error_rows} with errors</Pill>
            </div>
            {result.blocking_reason && <InlineNotice tone={result.error_rows || result.ledger_error ? "neg" : "warn"}>{result.blocking_reason}</InlineNotice>}
            {result.header_errors.length > 0 && (
              <ul className="list-disc pl-5 text-[13px] text-neg">
                {result.header_errors.map((h) => <li key={h}>{h}</li>)}
              </ul>
            )}
            {result.rows.length > 0 && (
              <div className="scrollbar-thin max-h-80 overflow-auto rounded-[var(--radius-control)] border border-line-subtle">
                <table className="w-full text-[12.5px]">
                  <caption className="sr-only">Import preview</caption>
                  <thead className="sticky top-0 bg-elevated text-xs text-fg-3">
                    <tr>
                      {["Row", "Status", "Date", "Type", "Symbol", "Qty", "Price", "Fees", "Amount", "Messages"].map((h, i) => (
                        <th key={h} scope="col" className={cn("px-2.5 py-2 font-medium whitespace-nowrap", i >= 5 && i <= 8 ? "text-right" : "text-left")}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.map((r) => (
                      <tr key={r.row} className={cn("border-t border-line-subtle", r.status === "error" && "bg-neg-soft", r.status === "duplicate" && "bg-warn-soft")}>
                        <td className="num px-2.5 py-1.5 text-fg-3">{r.row}</td>
                        <td className="px-2.5"><Pill tone={r.status === "ok" ? "pos" : r.status === "error" ? "neg" : "warn"} className="py-0">{r.status === "ok" ? "New" : r.status === "error" ? "Error" : "Duplicate"}</Pill></td>
                        <td className="num px-2.5 whitespace-nowrap">{r.values.date ?? ""}</td>
                        <td className="px-2.5">{r.values.type ?? ""}</td>
                        <td className="num px-2.5">{r.values.symbol ?? ""}</td>
                        <td className="num px-2.5 text-right">{r.values.quantity ?? ""}</td>
                        <td className="num px-2.5 text-right">{r.values.price ?? ""}</td>
                        <td className="num px-2.5 text-right">{r.values.fees ?? ""}</td>
                        <td className="num px-2.5 text-right">{r.values.amount ?? ""}</td>
                        <td className="max-w-72 px-2.5 text-fg-2">{r.messages.join(" ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </Dialog>
  );
}
