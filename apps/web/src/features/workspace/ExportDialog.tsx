import { useEffect, useState } from "react";
import { Download } from "lucide-react";
import { Dialog } from "@/components/ui/Dialog";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { useDialogs } from "@/app/dialogs";
import { errorMessage } from "@/lib/api/client";
import { downloadResearch, type ExportSection } from "./api";

const OPTIONS: { key: ExportSection; label: string; hint: string; private?: boolean }[] = [
  { key: "ai", label: "Saved AI answers with their sources", hint: "Model interpretation, kept separate, with each retrieved source, its date and link. Includes your questions." },
  { key: "journal", label: "My journal entries", hint: "Private: your thesis, risks and decisions for this instrument.", private: true },
  { key: "holdings", label: "My holding", hint: "Private: quantity, average cost and value from your ledger.", private: true },
];

/** Research export: public market facts always; private sections only when ticked (all private ones start off). */
export function ExportDialog() {
  const { state, close } = useDialogs();
  const open = state.kind === "export";
  const symbol = state.kind === "export" ? state.symbol : "";
  const [sel, setSel] = useState<Set<ExportSection>>(new Set(["ai"]));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();
  useEffect(() => {
    if (open) {
      setSel(new Set(["ai"]));
      setError(null);
    }
  }, [open, symbol]);
  const privateOn = OPTIONS.filter((o) => o.private && sel.has(o.key));
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && close()}
      title={`Export research · ${symbol}`}
      description="A Markdown file with the last observed quote, fundamentals and corporate actions (with source and fetch times), SEC filings for US listings, and the sections you choose."
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={close}>Cancel</Button>
          <Button
            variant="primary"
            icon={<Download className="size-4" aria-hidden />}
            loading={busy}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                await downloadResearch(symbol, [...sel]);
                toast("success", "Research exported.");
                close();
              } catch (e) {
                setError(errorMessage(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            Download .md
          </Button>
        </>
      }
    >
      <fieldset className="space-y-3">
        <legend className="mb-1 text-[13px] font-medium text-fg-2">Include</legend>
        {OPTIONS.map((o) => (
          <label key={o.key} className="flex cursor-pointer items-start gap-3 text-[13px]">
            <input
              type="checkbox"
              className="mt-0.5 size-4 accent-[var(--accent)]"
              checked={sel.has(o.key)}
              onChange={(e) => {
                const next = new Set(sel);
                if (e.target.checked) next.add(o.key);
                else next.delete(o.key);
                setSel(next);
              }}
            />
            <span>
              <span className="text-fg">{o.label}</span>
              <span className="block text-xs text-fg-3">{o.hint}</span>
            </span>
          </label>
        ))}
      </fieldset>
      {privateOn.length > 0 && (
        <InlineNotice tone="warn" className="mt-3">
          This file will contain private data ({privateOn.map((o) => o.key).join(", ")}). Its header says so; share it only with people you trust.
        </InlineNotice>
      )}
      {error && <InlineNotice tone="neg" className="mt-3">{error}</InlineNotice>}
    </Dialog>
  );
}
