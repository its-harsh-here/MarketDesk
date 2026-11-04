import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";
import { useDialogs } from "@/app/dialogs";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Input, Select } from "@/components/ui/Form";
import { InlineNotice } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { ApiError, errorMessage, type Alert } from "@/lib/api/client";
import { SymbolPicker } from "@/features/search/SymbolPicker";
import { useAlertMutations, type AlertInput, type RuleName } from "./api";

export const CONDITIONS = [
  { value: "PRICE:ABOVE", label: "Price at or above" },
  { value: "PRICE:BELOW", label: "Price at or below" },
  { value: "CROSS:ABOVE", label: "Price crosses above" },
  { value: "CROSS:BELOW", label: "Price crosses below" },
  { value: "VOLUME", label: "Unusual volume (completed session)" },
  { value: "VOLATILITY", label: "Unusual daily move (completed session)" },
  { value: "FILING", label: "New SEC filing (US listings)" },
  { value: "EARNINGS", label: "Results reminder (estimated date or deadline)" },
] as const;
type Condition = (typeof CONDITIONS)[number]["value"];

export const FILING_FORMS = ["10-K", "10-Q", "8-K", "20-F", "6-K", "DEF 14A"] as const;
const COOLDOWNS = [
  { value: "", label: "Manual rearm" },
  { value: "15", label: "Rearm after 15 minutes" },
  { value: "60", label: "Rearm after 1 hour" },
  { value: "240", label: "Rearm after 4 hours" },
  { value: "1440", label: "Rearm after 1 day" },
  { value: "10080", label: "Rearm after 7 days" },
];

const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;
const schema = z
  .object({
    symbol: z.string().min(1, "Choose an instrument."),
    condition: z.enum(CONDITIONS.map((c) => c.value) as [Condition, ...Condition[]]),
    level: z.string(),
    lookback: z.string(),
    forms: z.array(z.string()),
    days: z.string(),
    cooldown: z.string(),
    quiet_start: z.string(),
    quiet_end: z.string(),
    note: z.string().max(280, "Notes are limited to 280 characters."),
  })
  .superRefine((v, ctx) => {
    const rule = ruleOf(v.condition);
    if (rule === "PRICE" || rule === "CROSS") {
      if (!/^\d+(\.\d{1,4})?$/.test(v.level)) ctx.addIssue({ code: "custom", path: ["level"], message: "Use a plain price with at most 4 decimals." });
      else if (Number(v.level) <= 0) ctx.addIssue({ code: "custom", path: ["level"], message: "The level must be greater than zero." });
    }
    if (rule === "VOLUME" || rule === "VOLATILITY") {
      const n = Number(v.level);
      if (!/^\d+(\.\d{1,2})?$/.test(v.level) || n < 1.1 || n > 20) ctx.addIssue({ code: "custom", path: ["level"], message: "Enter a multiple between 1.1 and 20." });
      const lb = Number(v.lookback);
      if (!Number.isInteger(lb) || lb < 5 || lb > 60) ctx.addIssue({ code: "custom", path: ["lookback"], message: "Use 5 to 60 sessions." });
    }
    if (rule === "FILING" && v.forms.length === 0) ctx.addIssue({ code: "custom", path: ["forms"], message: "Choose at least one form." });
    if (rule === "EARNINGS" && (!/^\d{1,2}$/.test(v.days) || Number(v.days) > 30)) ctx.addIssue({ code: "custom", path: ["days"], message: "Use 0 to 30 days." });
    const qs = v.quiet_start, qe = v.quiet_end;
    if (qs || qe) {
      if (!HHMM.test(qs) || !HHMM.test(qe)) ctx.addIssue({ code: "custom", path: ["quiet_start"], message: "Give both a start and an end time, or neither." });
      else if (qs === qe) ctx.addIssue({ code: "custom", path: ["quiet_start"], message: "Start and end must differ." });
    }
  });
type Values = z.infer<typeof schema>;

function ruleOf(c: Condition): RuleName {
  return c.split(":")[0] as RuleName;
}

function conditionOf(a: Alert): Condition {
  return (a.rule === "PRICE" || a.rule === "CROSS" ? `${a.rule}:${a.direction}` : a.rule) as Condition;
}

const FIELD_MAP: Record<string, keyof Values> = { target_price: "level", "params.lookback": "lookback", quiet_start: "quiet_start", quiet_end: "quiet_end", cooldown_minutes: "cooldown", note: "note", rule: "condition", symbol: "symbol" };

export function AlertDialog() {
  const { state, close } = useDialogs();
  const isOpen = state.kind === "alert";
  const editing = state.kind === "alert" ? state.editing : undefined;
  const { create, update } = useAlertMutations();
  const toast = useToast();
  const [serverError, setServerError] = useState<string | null>(null);
  const defaults: Values = { symbol: "", condition: "PRICE:ABOVE", level: "", lookback: "20", forms: ["10-K", "10-Q", "8-K"], days: "3", cooldown: "", quiet_start: "", quiet_end: "", note: "" };
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: defaults });
  const { register, handleSubmit, control, reset, formState, setError, watch } = form;
  const condition = watch("condition");
  const rule = ruleOf(condition);

  useEffect(() => {
    if (isOpen && state.kind === "alert") {
      const a = state.editing;
      reset(
        a
          ? {
              symbol: a.symbol,
              condition: conditionOf(a),
              level: a.rule === "FILING" || a.rule === "EARNINGS" ? "" : String(Number(a.target_price)),
              lookback: String((a.params as { lookback?: number }).lookback ?? 20),
              forms: (a.params as { forms?: string[] }).forms ?? [],
              days: String((a.params as { days_before?: number }).days_before ?? 3),
              cooldown: a.cooldown_minutes ? String(a.cooldown_minutes) : "",
              quiet_start: a.quiet_start ?? "",
              quiet_end: a.quiet_end ?? "",
              note: a.note ?? "",
            }
          : { ...defaults, symbol: state.symbol ?? "" },
      );
      setServerError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  const onSubmit = handleSubmit(async (v) => {
    setServerError(null);
    const r = ruleOf(v.condition);
    const direction = v.condition.endsWith(":BELOW") ? "BELOW" : "ABOVE";
    const common = {
      cooldown_minutes: v.cooldown ? Number(v.cooldown) : null,
      quiet_start: v.quiet_start || null,
      quiet_end: v.quiet_end || null,
      note: v.note || null,
    };
    try {
      if (editing) {
        await update.mutateAsync({
          id: editing.id,
          patch: { ...common, ...(r === "FILING" || r === "EARNINGS" ? {} : { target_price: v.level }), ...(r === "PRICE" || r === "CROSS" ? { direction } : {}) },
        });
      } else {
        const body: AlertInput = {
          symbol: v.symbol,
          rule: r,
          direction,
          target_price: r === "FILING" || r === "EARNINGS" ? null : v.level,
          params:
            r === "VOLUME" || r === "VOLATILITY" ? { lookback: Number(v.lookback) } : r === "FILING" ? { forms: v.forms } : r === "EARNINGS" ? { days_before: Number(v.days) } : null,
          ...common,
        };
        await create.mutateAsync(body);
      }
      toast("success", editing ? "Alert updated." : `Alert armed for ${v.symbol}.`);
      close();
    } catch (err) {
      setServerError(errorMessage(err));
      if (err instanceof ApiError) for (const f of err.fields) if (f.field && FIELD_MAP[f.field]) setError(FIELD_MAP[f.field], { message: f.message });
    }
  });
  const e = formState.errors;
  const lastPrice = state.kind === "alert" ? state.price : undefined;
  const options = editing ? CONDITIONS.filter((c) => ruleOf(c.value) === editing.rule) : CONDITIONS;
  const sessionRule = rule === "VOLUME" || rule === "VOLATILITY";

  const help: Record<RuleName, string> = {
    PRICE: "Fires on the first sampled quote at or beyond the level, then waits to be rearmed.",
    CROSS: "Fires only when two consecutive sampled quotes are on opposite sides of the level. The first quote after arming is a baseline.",
    VOLUME: "Compares a finished session's volume with the average of the sessions before it. A session still trading is never compared with full days.",
    VOLATILITY: "Compares a finished session's close-to-close move with the standard deviation of the previous sessions' daily moves.",
    FILING: "One notice per new SEC filing of the chosen forms (US-registered issuers; needs SEC access configured on the server). Stays active.",
    EARNINGS: "One notice per results date, the chosen number of days before it. US: estimated from the cadence of past SEC results filings; India: the SEBI deadline. Never an announced date. Stays active.",
  };

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(o) => !o && close()}
      title={editing ? `Edit alert for ${editing.symbol}` : "Create alert"}
      description="Alerts are evaluated by the worker at its polling interval (sampled, not tick-by-tick) against new, valid data only. Stale or missing data is skipped and the reason is shown."
      footer={
        <>
          <Button variant="ghost" onClick={close}>Cancel</Button>
          <Button variant="primary" type="submit" form="alert-form" loading={formState.isSubmitting}>{editing ? "Save" : "Create alert"}</Button>
        </>
      }
    >
      <form id="alert-form" onSubmit={onSubmit} noValidate className="grid gap-4 sm:grid-cols-2">
        {serverError && <InlineNotice tone="neg" className="sm:col-span-2"><span role="alert">{serverError}</span></InlineNotice>}
        <Field label="Instrument" required error={e.symbol?.message} className="sm:col-span-2">
          {({ id, describedBy, invalid }) => (
            <Controller control={control} name="symbol" render={({ field }) => (
              editing ? <Input id={id} value={field.value} disabled className="num" /> :
              <SymbolPicker id={id} describedBy={describedBy} invalid={invalid} value={field.value} onChange={field.onChange} />
            )} />
          )}
        </Field>
        <Field label="Condition" required hint={help[rule]} className="sm:col-span-2">
          {({ id, describedBy }) => (
            <Select id={id} aria-describedby={describedBy} {...register("condition")}>
              {options.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </Select>
          )}
        </Field>
        {(rule === "PRICE" || rule === "CROSS") && (
          <Field label="Price level" required error={e.level?.message} hint={lastPrice ? `Last observed ${lastPrice}` : undefined}>
            {({ id, describedBy, invalid }) => <Input id={id} inputMode="decimal" className="num" aria-describedby={describedBy} aria-invalid={invalid} {...register("level")} />}
          </Field>
        )}
        {sessionRule && (
          <>
            <Field label={rule === "VOLUME" ? "Multiple of average volume" : "Standard deviations"} required error={e.level?.message} hint={rule === "VOLUME" ? "For example 2 = twice the average." : "For example 2.5."}>
              {({ id, describedBy, invalid }) => <Input id={id} inputMode="decimal" className="num" aria-describedby={describedBy} aria-invalid={invalid} {...register("level")} />}
            </Field>
            <Field label="Comparison window (sessions)" required error={e.lookback?.message}>
              {({ id, describedBy, invalid }) => <Input id={id} inputMode="numeric" className="num" readOnly={Boolean(editing)} aria-describedby={describedBy} aria-invalid={invalid} {...register("lookback")} />}
            </Field>
          </>
        )}
        {rule === "FILING" && (
          <fieldset className="sm:col-span-2" aria-describedby={e.forms ? "forms-err" : undefined}>
            <legend className="mb-1.5 text-[13px] font-medium text-fg-2">Forms</legend>
            {editing ? (
              <p className="num text-[13px] text-fg">{watch("forms").join(", ")} <span className="font-sans text-xs text-fg-3">(create a new alert to change forms)</span></p>
            ) : (
              <div className="flex flex-wrap gap-x-4 gap-y-2">
                {FILING_FORMS.map((f) => (
                  <label key={f} className="inline-flex min-h-8 items-center gap-2 text-[13px]">
                    <input type="checkbox" value={f} className="size-4 accent-[var(--accent)]" {...register("forms")} />
                    <span className="num">{f}</span>
                  </label>
                ))}
              </div>
            )}
            {e.forms && <p id="forms-err" role="alert" className="mt-1 text-xs text-neg">{e.forms.message}</p>}
          </fieldset>
        )}
        {rule === "EARNINGS" && (
          <Field label="Days before" required error={e.days?.message} hint="0 = on the day">
            {({ id, describedBy, invalid }) => <Input id={id} inputMode="numeric" className="num" aria-describedby={describedBy} aria-invalid={invalid} {...register("days")} />}
          </Field>
        )}
        {rule !== "FILING" && rule !== "EARNINGS" && (
          <Field label="After it fires" hint="Rearming starts a new arm; the same observation or session never fires twice.">
            {({ id, describedBy }) => (
              <Select id={id} aria-describedby={describedBy} {...register("cooldown")}>
                {COOLDOWNS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
              </Select>
            )}
          </Field>
        )}
        <fieldset className={rule === "FILING" ? "sm:col-span-2" : undefined}>
          <legend className="mb-1.5 text-[13px] font-medium text-fg-2">Quiet hours (display timezone)</legend>
          <div className="flex items-center gap-2">
            <Input type="time" aria-label="Quiet hours start" aria-invalid={Boolean(e.quiet_start)} className="num" {...register("quiet_start")} />
            <span className="text-fg-3" aria-hidden>–</span>
            <Input type="time" aria-label="Quiet hours end" className="num" {...register("quiet_end")} />
          </div>
          {e.quiet_start ? (
            <p role="alert" className="mt-1 text-xs text-neg">{e.quiet_start.message}</p>
          ) : (
            <p className="mt-1 text-xs leading-4 text-fg-3">Events are still recorded; the notice appears when the window ends.</p>
          )}
        </fieldset>
        <Field label="Note" error={e.note?.message} className="sm:col-span-2">
          {({ id, describedBy, invalid }) => <Input id={id} aria-describedby={describedBy} aria-invalid={invalid} {...register("note")} />}
        </Field>
        <p className="text-xs leading-4 text-fg-3 sm:col-span-2">
          In-app notices only. Email, Telegram and push are not configured in this installation. Alerts need the server and the worker process running; a sleeping host cannot evaluate them.
        </p>
      </form>
    </Dialog>
  );
}
