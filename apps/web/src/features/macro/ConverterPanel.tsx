import { useQuery } from "@tanstack/react-query";
import { ArrowLeftRight } from "lucide-react";
import { useEffect, useState } from "react";
import { Panel } from "@/components/ui/Panel";
import { InlineNotice } from "@/components/ui/States";
import { api, errorMessage } from "@/lib/api/client";
import { formatInstant, sourceName } from "@/lib/format";
import { usePrefs } from "@/features/settings/api";

interface Conversion {
  from: string;
  to: string;
  amount: string;
  rate: string | null;
  inverse: string | null;
  result: string | null;
  status: string;
  market_time?: string | null;
  source?: string | null;
  symbol?: string | null;
  inverted?: boolean;
  message?: string | null;
  currencies: string[];
  note?: string;
}

/** Indicative currency conversion at the provider's latest quoted rate. */
export function ConverterPanel({ className }: { className?: string }) {
  const [amount, setAmount] = useState("1000");
  const [from, setFrom] = useState("USD");
  const [to, setTo] = useState("INR");
  const [debounced, setDebounced] = useState(amount);
  const { data: prefs } = usePrefs();
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(amount), 300);
    return () => window.clearTimeout(t);
  }, [amount]);
  const valid = /^\d{1,12}(\.\d{0,6})?$/.test(debounced) && Number(debounced) > 0;
  const q = useQuery({
    queryKey: ["convert", debounced, from, to],
    queryFn: ({ signal }) => api.get<Conversion>("/api/terminal/convert", { amount: debounced, from, to }, signal),
    enabled: valid,
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  });
  const d = q.data;
  const currencies = d?.currencies ?? ["INR", "USD"];
  const fmt = (v: string | null | undefined, ccy: string) =>
    v === null || v === undefined ? "—" : new Intl.NumberFormat("en-IN", { style: "currency", currency: ccy, maximumFractionDigits: ccy === "JPY" ? 0 : 2 }).format(Number(v));
  const select = (value: string, set: (v: string) => void, label: string) => (
    <select aria-label={label} value={value} onChange={(e) => set(e.target.value)} className="h-10 rounded-[var(--radius-control)] border border-line bg-panel px-2 text-[14px] text-fg">
      {currencies.map((c) => <option key={c} value={c}>{c}</option>)}
    </select>
  );
  return (
    <Panel title="Currency converter" titleId="cv-title" className={className} refreshing={q.isFetching && !q.isLoading}>
      <div className="max-w-2xl space-y-3">
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex min-w-0 flex-1 flex-col gap-1 text-xs text-fg-3">
            Amount
            <input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^0-9.]/g, ""))}
              className="num h-10 rounded-[var(--radius-control)] border border-line bg-panel px-3 text-[15px] text-fg" aria-invalid={!valid} />
          </label>
          {select(from, setFrom, "From currency")}
          <button type="button" aria-label="Swap currencies" onClick={() => { setFrom(to); setTo(from); }}
            className="md-icon-btn flex size-10 items-center justify-center rounded-full border border-line text-fg-2 hover:rotate-180 hover:text-fg">
            <ArrowLeftRight className="size-4" aria-hidden />
          </button>
          {select(to, setTo, "To currency")}
        </div>
        {!valid ? (
          <p className="text-xs text-neg">Enter a positive amount (up to six decimals).</p>
        ) : q.isError ? (
          <InlineNotice tone="warn">{errorMessage(q.error)}</InlineNotice>
        ) : d && d.status === "unsupported" ? (
          <InlineNotice>{d.message}</InlineNotice>
        ) : d ? (
          <div aria-live="polite">
            <p className="num fx-reveal text-[26px] leading-8 font-semibold text-fg" key={`${d.result}${d.to}`}>{fmt(d.result, d.to)}</p>
            <p className="num text-[13px] text-fg-2">{fmt(d.amount, d.from)} at {d.rate ?? "—"} {d.to} per {d.from} · 1 {d.to} = {d.inverse ?? "—"} {d.from}</p>
            {d.rate === null && <p className="mt-1 text-xs text-warn">No usable rate: {d.message ?? d.status}.</p>}
            <p className="mt-1.5 text-xs text-fg-3">
              {d.source ? `Source: ${sourceName(d.source)}${d.symbol ? ` (${d.symbol})` : ""}` : ""}{d.market_time ? ` · quoted ${formatInstant(d.market_time, prefs?.display_timezone)}` : ""}{d.status && d.status !== "identity" ? ` · ${d.status}` : ""}. {d.note}
            </p>
          </div>
        ) : null}
      </div>
    </Panel>
  );
}
