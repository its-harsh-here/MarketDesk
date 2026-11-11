import { useQuery } from "@tanstack/react-query";
import { ExternalLink, NotebookPen } from "lucide-react";
import { useDialogs } from "@/app/dialogs";
import { Pill } from "@/components/ui/Badges";
import { Button } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Panel";
import { ErrorState, InlineNotice, SkeletonRows } from "@/components/ui/States";
import { api, errorMessage } from "@/lib/api/client";
import { formatSessionDate } from "@/lib/format";
import { useSession } from "@/features/settings/api";

interface Item { quote: string; named: { name: string; share_pct: string }[] }
interface Rel {
  symbol: string; status: string; reason?: string; confidence: "low"; method: string;
  filing?: { form: string; filed: string; period: string | null; url: string; index_url: string | null };
  customers?: Item[]; suppliers?: Item[];
}

function Quotes({ items, empty, url }: { items: Item[]; empty: string; url?: string }) {
  if (!items.length) return <p className="text-[13px] text-fg-3">{empty}</p>;
  return (
    <ul className="space-y-3">
      {items.map((it, i) => (
        <li key={i} className="text-[13px]">
          {it.named.length > 0 && (
            <div className="mb-1 flex flex-wrap gap-1.5">
              {it.named.map((n) => <Pill key={n.name} tone="info" className="py-0">{n.name} · <span className="num">{n.share_pct}%</span></Pill>)}
            </div>
          )}
          <blockquote className="border-l-2 border-info/50 pl-3 leading-5 text-fg-2">“{it.quote}”</blockquote>
          {url && <a href={url} target="_blank" rel="noopener noreferrer" className="mt-0.5 inline-flex items-center gap-1 pl-3 text-xs text-fg-3 hover:text-fg-2">in the filing <ExternalLink className="size-3" aria-hidden /></a>}
        </li>
      ))}
    </ul>
  );
}

/** Terminal T10: customer and supplier disclosures quoted from the latest annual report, plus the owner's notes. */
export function RelationsTab({ symbol }: { symbol: string }) {
  const { open } = useDialogs();
  const { data: session } = useSession();
  const q = useQuery({
    queryKey: ["terminal", "relationships", symbol],
    queryFn: ({ signal }) => api.get<Rel>("/api/terminal/relationships", { symbol }, signal),
    staleTime: 60 * 60_000,
    retry: false,
  });
  const d = q.data;
  const meta = d?.filing ? `${d.filing.form} filed ${formatSessionDate(d.filing.filed)}${d.filing.period ? ` · period ${formatSessionDate(d.filing.period)}` : ""}` : undefined;
  return (
    <>
      <Panel title="Customers" titleId="rel-c" className="lg:col-span-6" meta={meta} refreshing={q.isFetching && !q.isLoading}>
        {q.isLoading ? <SkeletonRows rows={5} /> : q.isError || !d ? <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} /> : d.status !== "available" ? (
          <InlineNotice>{d.reason}</InlineNotice>
        ) : <Quotes items={d.customers!} url={d.filing?.url} empty="The annual report states no customer's share of revenue in a recognisable sentence." />}
      </Panel>
      <Panel title="Suppliers" titleId="rel-s" className="lg:col-span-6" meta={meta}>
        {q.isLoading ? <SkeletonRows rows={5} /> : d?.status === "available" ? (
          <Quotes items={d.suppliers!} url={d.filing?.url} empty="No sentence about depending on particular suppliers was found." />
        ) : <p className="text-[13px] text-fg-3">{d?.reason ?? ""}</p>}
      </Panel>
      <Panel title="About these relationships" titleId="rel-about" className="lg:col-span-12">
        <div className="flex flex-wrap items-start gap-4 text-xs text-fg-3">
          <p className="min-w-0 flex-[1_1_28rem]">
            <Pill tone="warn" className="mr-2 py-0">low confidence</Pill>
            {d?.method ?? "Quoted from the latest annual report."} Companies need not name customers or suppliers, so absence here means
            nothing was disclosed in these words.
          </p>
          <Button size="sm" icon={<NotebookPen className="size-4" aria-hidden />} disabled={session?.read_only} onClick={() => open({ kind: "journal", symbol })}>
            Add your own note
          </Button>
        </div>
      </Panel>
    </>
  );
}
