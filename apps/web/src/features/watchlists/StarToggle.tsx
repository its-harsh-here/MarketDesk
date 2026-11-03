import * as DM from "@radix-ui/react-dropdown-menu";
import { Check, ChevronDown, Star } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { errorMessage } from "@/lib/api/client";
import { usePrefs, useSession } from "@/features/settings/api";
import { useMembership, useWatchlistMutations, useWatchlists } from "./api";
import { cn } from "@/lib/cn";

/** Star = membership in the default watchlist; the menu lets you pick any watchlist. Never navigates. */
export function StarToggle({ symbol }: { symbol: string }) {
  const { data: lists } = useWatchlists();
  const { data: prefs } = usePrefs();
  const { data: membership } = useMembership(symbol);
  const { data: session } = useSession();
  const { addSymbol, removeSymbol } = useWatchlistMutations();
  const toast = useToast();
  const ids = new Set(membership?.watchlist_ids ?? []);
  const target = lists?.find((l) => l.id === prefs?.default_watchlist_id) ?? lists?.[0];
  const inTarget = target ? ids.has(target.id) : false;
  const readOnly = Boolean(session?.read_only);
  const busy = addSymbol.isPending || removeSymbol.isPending;

  const toggle = (id: number, name: string, present: boolean) => {
    const m = present ? removeSymbol : addSymbol;
    m.mutate(
      { id, symbol },
      {
        onSuccess: () => toast("success", present ? `Removed ${symbol} from ${name}.` : `Added ${symbol} to ${name}.`),
        onError: (e) => toast("error", errorMessage(e)),
      },
    );
  };

  if (!lists || lists.length === 0) {
    return (
      <Button size="sm" disabled title="Create a watchlist first (Watchlists page)">
        <Star className="size-4" aria-hidden /> Watch
      </Button>
    );
  }

  return (
    <div className="inline-flex">
      <Button
        size="sm"
        className="rounded-r-none"
        disabled={readOnly || busy || !target}
        aria-pressed={inTarget}
        title={readOnly ? "Read-only demo" : undefined}
        onClick={(e) => {
          e.stopPropagation();
          if (target) toggle(target.id, target.name, inTarget);
        }}
      >
        <Star className={cn("size-4", inTarget && "fill-accent text-accent-text")} aria-hidden />
        {inTarget ? `In ${target?.name}` : `Add to ${target?.name}`}
      </Button>
      <DM.Root>
        <DM.Trigger asChild disabled={readOnly}>
          <Button size="sm" className="rounded-l-none border-l-0 px-2" aria-label="Choose watchlists">
            <ChevronDown className="size-4" aria-hidden />
          </Button>
        </DM.Trigger>
        <DM.Portal>
          <DM.Content align="end" sideOffset={6} className="anim-pop z-50 min-w-56 rounded-[var(--radius-control)] border border-line bg-elevated p-1 shadow-[var(--shadow-pop)]">
            <DM.Label className="px-2.5 py-1.5 text-xs text-fg-3">Watchlists</DM.Label>
            {lists.map((l) => {
              const present = ids.has(l.id);
              return (
                <DM.CheckboxItem
                  key={l.id}
                  checked={present}
                  onSelect={(e) => {
                    e.preventDefault();
                    toggle(l.id, l.name, present);
                  }}
                  className="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-[13px] text-fg-2 outline-none data-[highlighted]:bg-hover data-[highlighted]:text-fg"
                >
                  <span className="flex size-4 items-center justify-center">{present && <Check className="size-3.5 text-accent-text" aria-hidden />}</span>
                  {l.name}
                  <span className="num ml-auto text-xs text-fg-3">{l.item_count}</span>
                </DM.CheckboxItem>
              );
            })}
          </DM.Content>
        </DM.Portal>
      </DM.Root>
    </div>
  );
}
