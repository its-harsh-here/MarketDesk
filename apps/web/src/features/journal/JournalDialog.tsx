import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";
import { useDialogs } from "@/app/dialogs";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog, Dialog } from "@/components/ui/Dialog";
import { Field, Input, Textarea } from "@/components/ui/Form";
import { InlineNotice } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { ApiError, errorMessage } from "@/lib/api/client";
import { todayIso } from "@/lib/format";
import { usePrefs } from "@/features/settings/api";
import { SymbolPicker } from "@/features/search/SymbolPicker";
import { useJournalMutations } from "./api";

const schema = z
  .object({
    symbol: z.string().min(1, "Choose an instrument."),
    entry_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "Use a valid date."),
    title: z.string().trim().min(1, "Title is required.").max(160),
    thesis: z.string().max(10000),
    risks: z.string().max(10000),
    invalidation: z.string().max(10000),
    tags: z.string().max(400),
    review_date: z.string(),
  })
  .refine((v) => !v.review_date || v.review_date >= v.entry_date, { path: ["review_date"], message: "Review date cannot be before the entry date." })
  .refine((v) => v.tags.split(",").map((t) => t.trim()).filter(Boolean).every((t) => /^[A-Za-z0-9][A-Za-z0-9 _-]{0,31}$/.test(t)), {
    path: ["tags"],
    message: "Tags use letters, numbers, spaces, - or _ (max 32 characters each).",
  });
type Values = z.infer<typeof schema>;

export function JournalDialog() {
  const { state, close } = useDialogs();
  const isOpen = state.kind === "journal";
  const editing = state.kind === "journal" ? state.editing : undefined;
  const { data: prefs } = usePrefs();
  const { create, update, remove } = useJournalMutations();
  const toast = useToast();
  const [serverError, setServerError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const form = useForm<Values>({ resolver: zodResolver(schema) });
  const { register, handleSubmit, control, reset, formState, setError } = form;

  useEffect(() => {
    if (isOpen && state.kind === "journal") {
      const e = state.editing;
      reset({
        symbol: e?.symbol ?? state.symbol ?? "",
        entry_date: e?.entry_date ?? todayIso(prefs?.display_timezone),
        title: e?.title ?? "",
        thesis: e?.thesis ?? "",
        risks: e?.risks ?? "",
        invalidation: e?.invalidation ?? "",
        tags: e?.tags.join(", ") ?? "",
        review_date: e?.review_date ?? "",
      });
      setServerError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  const onSubmit = handleSubmit(async (v) => {
    const body = {
      symbol: v.symbol,
      entry_date: v.entry_date,
      title: v.title,
      thesis: v.thesis,
      risks: v.risks,
      invalidation: v.invalidation,
      tags: v.tags.split(",").map((t) => t.trim()).filter(Boolean),
      review_date: v.review_date || null,
    };
    try {
      if (editing) await update.mutateAsync({ id: editing.id, body });
      else await create.mutateAsync(body);
      toast("success", editing ? "Note updated." : "Note saved.");
      close();
    } catch (err) {
      setServerError(errorMessage(err));
      if (err instanceof ApiError) for (const f of err.fields) if (f.field && f.field in v) setError(f.field as keyof Values, { message: f.message });
    }
  });
  const e = formState.errors;

  return (
    <>
      <Dialog
        open={isOpen}
        onOpenChange={(o) => !o && close()}
        title={editing ? "Edit journal note" : "New journal note"}
        description="Your own reasoning, stored as plain text. MarketDesk never generates or rewrites notes."
        size="lg"
        footer={
          <>
            {editing && <Button variant="danger" className="mr-auto" onClick={() => setConfirm(true)}>Delete</Button>}
            <Button variant="ghost" onClick={close}>Cancel</Button>
            <Button variant="primary" type="submit" form="journal-form" loading={formState.isSubmitting}>{editing ? "Save" : "Save note"}</Button>
          </>
        }
      >
        <form id="journal-form" onSubmit={onSubmit} noValidate className="grid gap-4 sm:grid-cols-2">
          {serverError && <InlineNotice tone="neg" className="sm:col-span-2"><span role="alert">{serverError}</span></InlineNotice>}
          <Field label="Instrument" required error={e.symbol?.message}>
            {({ id, describedBy, invalid }) => (
              <Controller control={control} name="symbol" render={({ field }) => <SymbolPicker id={id} describedBy={describedBy} invalid={invalid} value={field.value ?? ""} onChange={field.onChange} />} />
            )}
          </Field>
          <Field label="Date" required error={e.entry_date?.message}>
            {({ id, describedBy, invalid }) => <Input id={id} type="date" aria-describedby={describedBy} aria-invalid={invalid} {...register("entry_date")} />}
          </Field>
          <Field label="Title" required error={e.title?.message} className="sm:col-span-2">
            {({ id, describedBy, invalid }) => <Input id={id} maxLength={160} aria-describedby={describedBy} aria-invalid={invalid} {...register("title")} />}
          </Field>
          <Field label="Thesis" className="sm:col-span-2" hint="What you expect and why.">
            {({ id, describedBy }) => <Textarea id={id} rows={4} aria-describedby={describedBy} {...register("thesis")} />}
          </Field>
          <Field label="Risks">
            {({ id }) => <Textarea id={id} rows={3} {...register("risks")} />}
          </Field>
          <Field label="Invalidation conditions" hint="What would prove the thesis wrong.">
            {({ id, describedBy }) => <Textarea id={id} rows={3} aria-describedby={describedBy} {...register("invalidation")} />}
          </Field>
          <Field label="Tags" error={e.tags?.message} hint="Comma separated, e.g. banking, long-term">
            {({ id, describedBy, invalid }) => <Input id={id} aria-describedby={describedBy} aria-invalid={invalid} {...register("tags")} />}
          </Field>
          <Field label="Review date" error={e.review_date?.message}>
            {({ id, describedBy, invalid }) => <Input id={id} type="date" aria-describedby={describedBy} aria-invalid={invalid} {...register("review_date")} />}
          </Field>
        </form>
      </Dialog>
      {editing && (
        <ConfirmDialog
          open={confirm}
          onOpenChange={setConfirm}
          title="Delete this note?"
          body={`“${editing.title}” will be permanently deleted.`}
          onConfirm={async () => {
            await remove.mutateAsync(editing.id);
            toast("success", "Note deleted.");
            close();
          }}
        />
      )}
    </>
  );
}
