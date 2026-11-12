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
import { useCsvMappingMutations, useCsvMappings, useTransactionMutations, type CsvMapping } from "./api";

const TEMPLATE = [
  "date,type,symbol,quantity,price,fees,amount,currency,split_from,split_to,counter_currency,counter_amount,fx_rate,fx_source,fx_time,notes",
  "2026-01-02,DEPOSIT,,,,,100000,INR,,,,,,,,Initial funding",
  "2026-01-03,BUY,RELIANCE.NS,10,1250.50,20,,INR,,,,,,,,",
  "2026-01-05,SELL,RELIANCE.NS,5,1290,20,,INR,,,,,,,,",
  "2026-01-06,FX,,,,150,42000,INR,,,USD,500,84,Your bank,2026-01-06T10:30:00+05:30,Remittance",
  "2026-01-07,BUY,AAPL,2,230.10,1,,USD,,,,,,,,",
].join("\n");

const FIELD_LABEL: Record<string, string> = {
  date: "Trade date", type: "Buy / sell", symbol: "Symbol", quantity: "Quantity", price: "Price",
  fees: "Charges (optional)", exchange: "Exchange (optional)", order_id: "Order id (optional)", currency: "Currency (optional)",
};
const input = "h-9 w-full rounded-[var(--radius-control)] border border-line bg-panel px-2 text-[13px] text-fg";

/** Describe another broker's export once: which column holds each field, and how buy/sell and dates are written. */
function MappingForm({ fields, required, dateFormats, onSaved, onCancel }: {
  fields: string[]; required: string[]; dateFormats: string[]; onSaved: (m: CsvMapping) => void; onCancel: () => void;
}) {
  const { save } = useCsvMappingMutations();
  const [name, setName] = useState("");
  const [cols, setCols] = useState<Record<string, string>>({});
  const [buy, setBuy] = useState("buy, b");
  const [sell, setSell] = useState("sell, s");
  const [fmt, setFmt] = useState("auto");
  const [suffix, setSuffix] = useState("ns");
  const [currency, setCurrency] = useState("INR");
  const [combine, setCombine] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const words = (s: string) => s.split(",").map((w) => w.trim()).filter(Boolean);
  const submit = async () => {
    setErr(null);
    try {
      onSaved(await save.mutateAsync({ name, columns: cols, buy_words: words(buy), sell_words: words(sell), date_format: fmt, symbol_suffix: suffix, currency, combine_fills: combine }));
    } catch (e) {
      setErr(errorMessage(e));
    }
  };
  return (
    <fieldset className="space-y-3 rounded-[var(--radius-control)] border border-line-subtle bg-canvas/40 p-3 text-[13px]">
      <legend className="px-1 text-fg">New broker mapping</legend>
      <p className="text-xs text-fg-3">Type the column headings exactly as they appear in your broker's CSV.</p>
      <label className="block"><span className="text-fg-2">Mapping name</span><input className={input} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. My broker trades" /></label>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        {fields.map((f) => (
          <label key={f} className="block">
            <span className="text-fg-2">{FIELD_LABEL[f] ?? f}{required.includes(f) ? " *" : ""}</span>
            <input className={input} value={cols[f] ?? ""} onChange={(e) => setCols((c) => ({ ...c, [f]: e.target.value }))} aria-required={required.includes(f)} />
          </label>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <label className="block"><span className="text-fg-2">Words meaning buy</span><input className={input} value={buy} onChange={(e) => setBuy(e.target.value)} /></label>
        <label className="block"><span className="text-fg-2">Words meaning sell</span><input className={input} value={sell} onChange={(e) => setSell(e.target.value)} /></label>
        <label className="block"><span className="text-fg-2">Date format</span>
          <select className={input} value={fmt} onChange={(e) => setFmt(e.target.value)}>
            {dateFormats.map((d) => <option key={d} value={d}>{d === "auto" ? "Detect" : d.replace("%Y", "YYYY").replace("%m", "MM").replace("%d", "DD").replace("%b", "Mon")}</option>)}
          </select>
        </label>
        <label className="block"><span className="text-fg-2">Symbols</span>
          <select className={input} value={suffix} onChange={(e) => setSuffix(e.target.value)}>
            <option value="ns">Add .NS (NSE)</option><option value="bo">Add .BO (BSE)</option>
            <option value="exchange">From the exchange column</option><option value="none">Use as written</option>
          </select>
        </label>
        <label className="block"><span className="text-fg-2">Account</span>
          <select className={input} value={currency} onChange={(e) => setCurrency(e.target.value)}><option>INR</option><option>USD</option></select>
        </label>
        <label className="flex items-end gap-2 pb-2"><input type="checkbox" checked={combine} onChange={(e) => setCombine(e.target.checked)} /> <span className="text-fg-2">Combine partial fills of one order</span></label>
      </div>
      {err && <InlineNotice tone="neg"><span role="alert">{err}</span></InlineNotice>}
      <div className="flex gap-2">
        <Button variant="primary" size="sm" loading={save.isPending} onClick={submit}>Save mapping</Button>
        <Button variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
      </div>
    </fieldset>
  );
}

export function ImportDialog() {
  const { state, close } = useDialogs();
  const isOpen = state.kind === "import";
  const { preview, commit } = useTransactionMutations();
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ImportPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const maps = useCsvMappings(isOpen);
  const [mapping, setMapping] = useState("");
  const [creating, setCreating] = useState(false);
  const chosen = maps.data?.mappings.find((m) => m.id === mapping);

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
      setResult(await preview.mutateAsync({ file: f, mapping: mapping || undefined }));
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
      description="Upload the MarketDesk format or a broker's trade export. You will see every row before anything is written; the import is all-or-nothing."
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
        <div className="flex flex-wrap items-end gap-3">
          <label className="block text-[13px]">
            <span className="text-fg-2">File format</span>
            <select className={cn(input, "min-w-64")} value={mapping} onChange={(e) => { setMapping(e.target.value); setResult(null); }}>
              <option value="">MarketDesk format</option>
              {maps.data?.mappings.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          </label>
          <Button size="sm" variant="ghost" onClick={() => setCreating((c) => !c)}>{creating ? "Close mapping form" : "New broker mapping"}</Button>
          {chosen && !chosen.builtin && <SavedMappingDelete id={chosen.id} onDeleted={() => setMapping("")} />}
        </div>
        {chosen?.note && <p className="text-xs text-fg-3">{chosen.note}</p>}
        {creating && maps.data && (
          <MappingForm fields={maps.data.fields} required={maps.data.required} dateFormats={maps.data.date_formats}
            onCancel={() => setCreating(false)} onSaved={(m) => { setCreating(false); setMapping(m.id); toast("success", `Saved mapping “${m.name}”.`); }} />
        )}
        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={fileInput}
            type="file"
            accept=".csv,text/csv"
            className="sr-only"
            id="csv-file"
            aria-label="CSV file"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setFile(f);
              if (f) runPreview(f);
              e.target.value = "";
            }}
          />
          <Button icon={<FileUp className="size-4" aria-hidden />} onClick={() => fileInput.current?.click()} loading={preview.isPending}>
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
            <code className="num text-xs text-fg">date,type,symbol,quantity,price,fees,amount,currency,split_from,split_to,notes</code> (plus <code className="num text-xs text-fg">counter_currency,counter_amount,fx_rate,fx_source,fx_time</code> for FX rows) — dates as YYYY-MM-DD; types DEPOSIT, WITHDRAWAL, BUY, SELL, DIVIDEND, SPLIT or FX; plain numbers without thousands separators; currency is the account, INR or USD (blank means INR), and an instrument must trade in its row's currency. Enter trades with their original quantities; a SPLIT row applies a split once. Rows identical to existing transactions (including notes) are treated as duplicates and skipped.
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
            {(result.conversion_notes ?? []).length > 0 && (
              <ul className="list-disc space-y-0.5 pl-5 text-xs text-fg-2">{result.conversion_notes!.map((n) => <li key={n}>{n}</li>)}</ul>
            )}
            {result.blocking_reason && <InlineNotice tone={result.error_rows || result.ledger_error ? "neg" : "warn"}>{result.blocking_reason}</InlineNotice>}
            {result.header_errors.length > 0 && (
              <ul className="list-disc pl-5 text-[13px] text-neg">
                {result.header_errors.map((h) => <li key={h}>{h}</li>)}
              </ul>
            )}
            {result.rows.length > 0 && (
              <div tabIndex={0} className="scrollbar-thin max-h-80 overflow-auto rounded-[var(--radius-control)] border border-line-subtle">
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

function SavedMappingDelete({ id, onDeleted }: { id: string; onDeleted: () => void }) {
  const { remove } = useCsvMappingMutations();
  const [confirm, setConfirm] = useState(false);
  return confirm ? (
    <span className="flex items-center gap-2 text-xs">
      Delete this mapping?
      <Button size="sm" variant="danger" loading={remove.isPending} onClick={async () => { await remove.mutateAsync(id); onDeleted(); }}>Delete</Button>
      <Button size="sm" variant="ghost" onClick={() => setConfirm(false)}>Keep</Button>
    </span>
  ) : (
    <Button size="sm" variant="ghost" onClick={() => setConfirm(true)}>Delete mapping</Button>
  );
}
