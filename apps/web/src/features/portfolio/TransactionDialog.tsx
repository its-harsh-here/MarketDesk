import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useMemo, useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { z } from "zod";
import { useDialogs } from "@/app/dialogs";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog, Dialog } from "@/components/ui/Dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/Form";
import { InlineNotice } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { ApiError, errorMessage, type AccountCurrency, type Transaction, type TransactionInput } from "@/lib/api/client";
import { formatMoney, formatNumber, todayIso } from "@/lib/format";
import { usePrefs } from "@/features/settings/api";
import { SymbolPicker } from "@/features/search/SymbolPicker";
import { useTransactionMutations } from "./api";

const TYPES = ["DEPOSIT", "WITHDRAWAL", "BUY", "SELL", "DIVIDEND", "SPLIT", "FX"] as const;
type TxType = (typeof TYPES)[number];
const LABELS: Record<TxType, string> = {
  DEPOSIT: "Deposit cash",
  WITHDRAWAL: "Withdraw cash",
  BUY: "Buy",
  SELL: "Sell",
  DIVIDEND: "Dividend received",
  SPLIT: "Stock split (confirmed)",
  FX: "Convert currency (FX)",
};
const ACCOUNTS = ["INR", "USD"] as const;
const other = (c: AccountCurrency): AccountCurrency => (c === "INR" ? "USD" : "INR");

const dec = (places: number) => new RegExp(`^\\d+(\\.\\d{1,${places}})?$`);

const schema = z
  .object({
    type: z.enum(TYPES),
    effective_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "Use a valid date."),
    symbol: z.string(),
    quantity: z.string(),
    price: z.string(),
    fees: z.string(),
    amount: z.string(),
    split_from: z.string(),
    split_to: z.string(),
    split_confirmed: z.boolean(),
    currency: z.enum(ACCOUNTS),
    counter_amount: z.string(),
    fx_rate: z.string(),
    fx_source: z.string().max(80, "Use at most 80 characters."),
    fx_time: z.string(),
    notes: z.string().max(500, "Notes are limited to 500 characters."),
  })
  .superRefine((v, ctx) => {
    const req = (field: keyof typeof v, msg: string) => ctx.addIssue({ code: "custom", path: [field], message: msg });
    const positive = (field: "quantity" | "price" | "amount" | "split_from" | "split_to" | "counter_amount", places: number, label: string) => {
      const s = v[field].trim();
      if (!s) return req(field, `${label} is required.`);
      if (!dec(places).test(s)) return req(field, `${label} must be a plain number with at most ${places} decimals.`);
      if (Number(s) <= 0) req(field, `${label} must be greater than zero.`);
    };
    if (["BUY", "SELL", "DIVIDEND", "SPLIT"].includes(v.type) && !v.symbol.trim()) req("symbol", "Choose an instrument.");
    if (v.type === "BUY" || v.type === "SELL") {
      positive("quantity", 6, "Quantity");
      positive("price", 4, "Price");
      if (v.fees.trim() && !dec(2).test(v.fees.trim())) req("fees", "Fees must be a plain number with at most 2 decimals.");
    }
    if (v.type === "DEPOSIT" || v.type === "WITHDRAWAL" || v.type === "DIVIDEND") positive("amount", 2, "Amount");
    if (v.type === "FX") {
      positive("amount", 2, "Amount converted");
      positive("counter_amount", 2, "Amount received");
      if (v.fees.trim() && !dec(2).test(v.fees.trim())) req("fees", "Fees must be a plain number with at most 2 decimals.");
      if (v.fx_rate.trim() && (!dec(6).test(v.fx_rate.trim()) || Number(v.fx_rate) <= 0)) req("fx_rate", "Use a positive rate with at most 6 decimals.");
      if (!v.fx_source.trim()) req("fx_source", "Name the source of the rate (for example the bank or broker).");
    }
    if (v.type === "SPLIT") {
      positive("split_from", 6, "Old shares");
      positive("split_to", 6, "New shares");
      if (v.split_from.trim() && v.split_from.trim() === v.split_to.trim()) req("split_to", "A 1:1 split has no effect.");
      if (!v.split_confirmed) req("split_confirmed", "Confirm that this split has not already been reflected in your quantities.");
    }
  });

type FormValues = z.infer<typeof schema>;

function defaults(editing?: Transaction, symbol?: string, type?: TxType, tz?: string, currency?: AccountCurrency): FormValues {
  return {
    type: (editing?.type as TxType) ?? type ?? "BUY",
    effective_date: editing?.effective_date ?? todayIso(tz),
    symbol: editing?.symbol ?? symbol ?? "",
    quantity: editing?.quantity ?? "",
    price: editing?.price ?? "",
    fees: editing && editing.fees !== "0" ? editing.fees : "",
    amount: editing?.amount ?? "",
    split_from: editing?.split_from ?? "1",
    split_to: editing?.split_to ?? "2",
    split_confirmed: editing?.type === "SPLIT",
    currency: (editing?.currency as AccountCurrency | undefined) ?? currency ?? "INR",
    counter_amount: editing?.counter_amount ?? "",
    fx_rate: editing?.fx_rate ?? "",
    fx_source: editing?.fx_source ?? "",
    fx_time: editing?.fx_time ? editing.fx_time.slice(0, 16) : "",
    notes: editing?.notes ?? "",
  };
}

export function TransactionDialog() {
  const { state, close } = useDialogs();
  const isOpen = state.kind === "transaction";
  const editing = state.kind === "transaction" ? state.editing : undefined;
  const { data: prefs } = usePrefs();
  const { create, update, remove } = useTransactionMutations();
  const toast = useToast();
  const [serverError, setServerError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const form = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: defaults(), mode: "onTouched" });
  const { register, handleSubmit, control, reset, setError, formState } = form;
  const type = useWatch({ control, name: "type" });
  const account = useWatch({ control, name: "currency" });
  const [qty, price, fees, amount, received] = useWatch({ control, name: ["quantity", "price", "fees", "amount", "counter_amount"] });

  useEffect(() => {
    if (isOpen && state.kind === "transaction") {
      reset(defaults(state.editing, state.symbol, state.type as TxType | undefined, prefs?.display_timezone, state.currency));
      setServerError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  const estimate = useMemo(() => {
    const q = Number(qty);
    const p = Number(price);
    const f = Number(fees || 0);
    if (!(q > 0 && p > 0) || Number.isNaN(f)) return null;
    const gross = Math.round(q * p * 100) / 100;
    return type === "BUY" ? -(gross + f) : gross - f;
  }, [qty, price, fees, type]);
  const effectiveRate = useMemo(() => {
    const a = Number(amount);
    const r = Number(received);
    if (type !== "FX" || !(a > 0 && r > 0)) return null;
    return account === "INR" ? a / r : r / a; // INR per 1 USD
  }, [amount, received, account, type]);

  const onSubmit = handleSubmit(async (v) => {
    setServerError(null);
    const body: TransactionInput = {
      type: v.type,
      effective_date: v.effective_date,
      symbol: ["BUY", "SELL", "DIVIDEND", "SPLIT"].includes(v.type) ? v.symbol.trim() : null,
      quantity: v.type === "BUY" || v.type === "SELL" ? v.quantity.trim() : null,
      price: v.type === "BUY" || v.type === "SELL" ? v.price.trim() : null,
      fees: ["BUY", "SELL", "FX"].includes(v.type) ? v.fees.trim() || "0" : "0",
      amount: ["DEPOSIT", "WITHDRAWAL", "DIVIDEND", "FX"].includes(v.type) ? v.amount.trim() : null,
      split_from: v.type === "SPLIT" ? v.split_from.trim() : null,
      split_to: v.type === "SPLIT" ? v.split_to.trim() : null,
      split_confirmed: v.type === "SPLIT" && v.split_confirmed,
      currency: v.currency,
      ...(v.type === "FX"
        ? {
            counter_currency: other(v.currency),
            counter_amount: v.counter_amount.trim(),
            fx_rate: v.fx_rate.trim() || null,
            fx_source: v.fx_source.trim(),
            fx_time: v.fx_time ? new Date(v.fx_time).toISOString() : null,
          }
        : {}),
      notes: v.notes.trim() || null,
    };
    try {
      if (editing) await update.mutateAsync({ id: editing.id, body });
      else await create.mutateAsync(body);
      toast("success", editing ? "Transaction updated; ledger replayed." : "Transaction recorded.");
      close();
    } catch (err) {
      // keep the user's input; explain the problem next to the field and at the top
      setServerError(errorMessage(err));
      if (err instanceof ApiError) {
        for (const f of err.fields) {
          if (f.field && f.field in v) setError(f.field as keyof FormValues, { type: "server", message: f.message });
        }
      }
    }
  });

  const e = formState.errors;
  const trade = type === "BUY" || type === "SELL";
  const fx = type === "FX";
  const cashOnly = type === "DEPOSIT" || type === "WITHDRAWAL" || fx;
  const ccy = account;

  return (
    <>
      <Dialog
        open={isOpen}
        onOpenChange={(o) => !o && close()}
        title={editing ? `Edit transaction #${editing.id}` : "Add transaction"}
        description="Separate INR and USD accounts. Every change replays the full history of both; a change that would make an account's cash negative or oversell at any point is rejected. Amounts are never converted except by an explicit FX conversion."
        size="md"
        footer={
          <>
            {editing && (
              <Button variant="danger" className="mr-auto" onClick={() => setConfirmDelete(true)}>
                Delete
              </Button>
            )}
            <Button variant="ghost" onClick={close}>Cancel</Button>
            <Button variant="primary" type="submit" form="txn-form" loading={formState.isSubmitting}>
              {editing ? "Save changes" : "Record transaction"}
            </Button>
          </>
        }
      >
        <form id="txn-form" onSubmit={onSubmit} noValidate className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {serverError && (
            <InlineNotice tone="neg" className="sm:col-span-2">
              <span role="alert">{serverError}</span>
            </InlineNotice>
          )}
          <Field label="Type" required>
            {({ id }) => (
              <Select id={id} {...register("type")}>
                {TYPES.map((t) => (
                  <option key={t} value={t}>{LABELS[t]}</option>
                ))}
              </Select>
            )}
          </Field>
          <Field label={fx ? "Convert from account" : "Account"} required error={e.currency?.message} hint={fx ? `Into the ${other(ccy)} account.` : "Amounts are in this account's currency."}>
            {({ id, describedBy }) => (
              <Select id={id} aria-describedby={describedBy} {...register("currency")}>
                {ACCOUNTS.map((c) => (
                  <option key={c} value={c}>{c} account</option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Effective date" required error={e.effective_date?.message} hint="Trade or settlement date (exchange calendar date).">
            {({ id, describedBy, invalid }) => <Input id={id} type="date" aria-describedby={describedBy} aria-invalid={invalid} {...register("effective_date")} />}
          </Field>
          {!cashOnly && (
            <Field label="Instrument" required error={e.symbol?.message} className="sm:col-span-2" hint={`Must trade in ${ccy}; a listing in the other currency belongs in that account.`}>
              {({ id, describedBy, invalid }) => (
                <Controller control={control} name="symbol" render={({ field }) => (
                  <SymbolPicker id={id} describedBy={describedBy} invalid={invalid} value={field.value} onChange={(s) => field.onChange(s)} />
                )} />
              )}
            </Field>
          )}
          {trade && (
            <>
              <Field label="Quantity" required error={e.quantity?.message}>
                {({ id, describedBy, invalid }) => <Input id={id} inputMode="decimal" className="num" aria-describedby={describedBy} aria-invalid={invalid} {...register("quantity")} />}
              </Field>
              <Field label={`Price per share (${ccy})`} required error={e.price?.message}>
                {({ id, describedBy, invalid }) => <Input id={id} inputMode="decimal" className="num" aria-describedby={describedBy} aria-invalid={invalid} {...register("price")} />}
              </Field>
              <Field label={`Fees and charges (${ccy})`} error={e.fees?.message} hint="Brokerage, taxes and charges for this trade.">
                {({ id, describedBy, invalid }) => <Input id={id} inputMode="decimal" className="num" placeholder="0.00" aria-describedby={describedBy} aria-invalid={invalid} {...register("fees")} />}
              </Field>
              <div className="flex flex-col justify-end rounded-[var(--radius-control)] border border-line-subtle bg-canvas/50 px-3 py-2 text-[13px]">
                <span className="text-xs text-fg-3">Estimated cash effect</span>
                <span className="num text-fg">{estimate === null ? "—" : formatMoney(estimate, ccy)}</span>
              </div>
            </>
          )}
          {(cashOnly || type === "DIVIDEND") && (
            <Field label={fx ? `Amount converted (${ccy})` : type === "DIVIDEND" ? `Amount received (net, ${ccy})` : `Amount (${ccy})`} required error={e.amount?.message}>
              {({ id, describedBy, invalid }) => <Input id={id} inputMode="decimal" className="num" aria-describedby={describedBy} aria-invalid={invalid} {...register("amount")} />}
            </Field>
          )}
          {fx && (
            <>
              <Field label={`Amount received (${other(ccy)})`} required error={e.counter_amount?.message}>
                {({ id, describedBy, invalid }) => <Input id={id} inputMode="decimal" className="num" aria-describedby={describedBy} aria-invalid={invalid} {...register("counter_amount")} />}
              </Field>
              <Field label={`Conversion fees (${ccy})`} error={e.fees?.message} hint="Charged on top of the amount converted.">
                {({ id, describedBy, invalid }) => <Input id={id} inputMode="decimal" className="num" placeholder="0.00" aria-describedby={describedBy} aria-invalid={invalid} {...register("fees")} />}
              </Field>
              <Field label="Quoted rate (INR per USD)" error={e.fx_rate?.message} hint={effectiveRate ? `Effective ${formatNumber(effectiveRate, 4)} INR per USD from the amounts.` : "Optional; checked against the amounts."}>
                {({ id, describedBy, invalid }) => <Input id={id} inputMode="decimal" className="num" aria-describedby={describedBy} aria-invalid={invalid} {...register("fx_rate")} />}
              </Field>
              <Field label="Rate source" required error={e.fx_source?.message} hint="Bank, broker or provider.">
                {({ id, describedBy, invalid }) => <Input id={id} aria-describedby={describedBy} aria-invalid={invalid} {...register("fx_source")} />}
              </Field>
              <Field label="Rate time" error={e.fx_time?.message} hint="When the rate applied (your local time). Optional.">
                {({ id, describedBy, invalid }) => <Input id={id} type="datetime-local" className="num" aria-describedby={describedBy} aria-invalid={invalid} {...register("fx_time")} />}
              </Field>
            </>
          )}
          {type === "SPLIT" && (
            <>
              <Field label="Old shares" required error={e.split_from?.message}>
                {({ id, describedBy, invalid }) => <Input id={id} inputMode="decimal" className="num" aria-describedby={describedBy} aria-invalid={invalid} {...register("split_from")} />}
              </Field>
              <Field label="New shares" required error={e.split_to?.message} hint="2-for-1: old 1, new 2.">
                {({ id, describedBy, invalid }) => <Input id={id} inputMode="decimal" className="num" aria-describedby={describedBy} aria-invalid={invalid} {...register("split_to")} />}
              </Field>
              <div className="sm:col-span-2">
                <label className="flex items-start gap-2.5 text-[13px] leading-5 text-fg-2">
                  <input type="checkbox" className="mt-0.5 size-4 accent-[var(--accent)]" {...register("split_confirmed")} aria-invalid={Boolean(e.split_confirmed)} />
                  I confirm this split is real and my earlier trades use their original (pre-split) quantities. Quantity changes and average cost falls; total cost basis is unchanged.
                </label>
                {e.split_confirmed && <p className="mt-1 text-xs text-neg" role="alert">{e.split_confirmed.message}</p>}
              </div>
            </>
          )}
          <Field label="Notes" error={e.notes?.message} className="sm:col-span-2">
            {({ id, describedBy, invalid }) => <Textarea id={id} rows={2} className="min-h-16" aria-describedby={describedBy} aria-invalid={invalid} {...register("notes")} />}
          </Field>
        </form>
      </Dialog>
      {editing && (
        <ConfirmDialog
          open={confirmDelete}
          onOpenChange={setConfirmDelete}
          title={`Delete transaction #${editing.id}?`}
          body="The ledger is replayed without it. If later rows depend on it (for example, a deposit funding a buy), the delete is rejected and nothing changes."
          onConfirm={async () => {
            await remove.mutateAsync(editing.id);
            toast("success", "Transaction deleted.");
            close();
          }}
        />
      )}
    </>
  );
}
