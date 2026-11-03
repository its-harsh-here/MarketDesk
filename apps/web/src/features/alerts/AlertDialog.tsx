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
import { ApiError, errorMessage } from "@/lib/api/client";
import { SymbolPicker } from "@/features/search/SymbolPicker";
import { useAlertMutations } from "./api";

const schema = z.object({
  symbol: z.string().min(1, "Choose an instrument."),
  direction: z.enum(["ABOVE", "BELOW"]),
  target_price: z
    .string()
    .regex(/^\d+(\.\d{1,4})?$/, "Use a plain price with at most 4 decimals.")
    .refine((s) => Number(s) > 0, "Target must be greater than zero."),
  note: z.string().max(280, "Notes are limited to 280 characters."),
});
type Values = z.infer<typeof schema>;

export function AlertDialog() {
  const { state, close } = useDialogs();
  const isOpen = state.kind === "alert";
  const editing = state.kind === "alert" ? state.editing : undefined;
  const { create, update } = useAlertMutations();
  const toast = useToast();
  const [serverError, setServerError] = useState<string | null>(null);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { symbol: "", direction: "ABOVE", target_price: "", note: "" } });
  const { register, handleSubmit, control, reset, formState, setError } = form;

  useEffect(() => {
    if (isOpen && state.kind === "alert") {
      reset({
        symbol: state.editing?.symbol ?? state.symbol ?? "",
        direction: (state.editing?.direction as Values["direction"]) ?? "ABOVE",
        target_price: state.editing?.target_price ?? "",
        note: state.editing?.note ?? "",
      });
      setServerError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  const onSubmit = handleSubmit(async (v) => {
    setServerError(null);
    try {
      if (editing) await update.mutateAsync({ id: editing.id, patch: { direction: v.direction, target_price: v.target_price, note: v.note } });
      else await create.mutateAsync({ symbol: v.symbol, direction: v.direction, target_price: v.target_price, note: v.note || null });
      toast("success", editing ? "Alert updated." : `Alert armed for ${v.symbol}.`);
      close();
    } catch (err) {
      setServerError(errorMessage(err));
      if (err instanceof ApiError) for (const f of err.fields) if (f.field && f.field in v) setError(f.field as keyof Values, { message: f.message });
    }
  });
  const e = formState.errors;
  const lastPrice = state.kind === "alert" ? state.price : undefined;

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(o) => !o && close()}
      title={editing ? `Edit alert for ${editing.symbol}` : "Create price alert"}
      description="Alerts are sampled: the worker checks new quotes at its polling interval and fires once on the first observed match, then waits for you to rearm it."
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
        <Field label="Condition" required>
          {({ id }) => (
            <Select id={id} {...register("direction")}>
              <option value="ABOVE">Price at or above</option>
              <option value="BELOW">Price at or below</option>
            </Select>
          )}
        </Field>
        <Field label="Target price" required error={e.target_price?.message} hint={lastPrice ? `Last observed ${lastPrice}` : undefined}>
          {({ id, describedBy, invalid }) => <Input id={id} inputMode="decimal" className="num" aria-describedby={describedBy} aria-invalid={invalid} {...register("target_price")} />}
        </Field>
        <Field label="Note" error={e.note?.message} className="sm:col-span-2">
          {({ id, describedBy, invalid }) => <Input id={id} aria-describedby={describedBy} aria-invalid={invalid} {...register("note")} />}
        </Field>
        <p className="text-xs leading-4 text-fg-3 sm:col-span-2">
          In-app notifications only. Email, Telegram and push are not configured in this installation. Alerts need the server and the worker process running; a sleeping host cannot evaluate them.
        </p>
      </form>
    </Dialog>
  );
}
