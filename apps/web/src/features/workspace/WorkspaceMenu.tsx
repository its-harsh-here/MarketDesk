import * as DM from "@radix-ui/react-dropdown-menu";
import { Check, ChevronDown, LayoutGrid } from "lucide-react";
import { useNavigate } from "react-router";
import { useToast } from "@/components/ui/Toast";
import { errorMessage } from "@/lib/api/client";
import { useSession } from "@/features/settings/api";
import { useApplyWorkspace, useWorkspaces } from "./api";

/** Apply a workspace and open its start page; reports notes (e.g. a deleted default watchlist). */
export function useSwitchWorkspace() {
  const apply = useApplyWorkspace();
  const navigate = useNavigate();
  const toast = useToast();
  return (id: string) =>
    apply.mutate(id, {
      onSuccess: (r) => {
        navigate(r.workspace.start);
        toast(r.notes.length ? "info" : "success", [`Workspace: ${r.workspace.name}.`, ...r.notes].join(" "));
      },
      onError: (e) => toast("error", errorMessage(e)),
    });
}

export function WorkspaceMenu() {
  const { data: session } = useSession();
  const { data } = useWorkspaces();
  const switchTo = useSwitchWorkspace();
  const navigate = useNavigate();
  const active = data?.items.find((w) => w.id === data.active);
  const item = "flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-[13px] text-fg-2 outline-none data-[highlighted]:bg-hover data-[highlighted]:text-fg";
  return (
    <DM.Root>
      <DM.Trigger
        className="flex items-center gap-1 rounded text-[11px] font-medium tracking-wider text-fg-3 uppercase hover:text-fg-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus)]"
        aria-label={`Workspace: ${active?.name ?? "Personal"}. Switch workspace`}
      >
        {active ? `${active.name} workspace` : "Personal workspace"}
        <ChevronDown className="size-3" aria-hidden />
      </DM.Trigger>
      <DM.Portal>
        <DM.Content align="start" sideOffset={6} className="anim-pop z-50 w-64 rounded-[var(--radius-control)] border border-line bg-elevated p-1 shadow-[var(--shadow-pop)]">
          <DM.Label className="px-2.5 pt-1.5 pb-1 text-xs text-fg-3">Workspaces · start page, density, default watchlist</DM.Label>
          {(data?.items ?? []).map((w) => (
            <DM.Item key={w.id} className={item} disabled={session?.read_only} onSelect={() => switchTo(w.id)}>
              {w.id === data?.active ? <Check className="size-4 text-accent-text" aria-hidden /> : <LayoutGrid className="size-4" aria-hidden />}
              <span className="min-w-0 flex-1 truncate">{w.name}</span>
              <span className="text-xs text-fg-3">{data?.start_pages.find((p) => p.path === w.start)?.label}</span>
            </DM.Item>
          ))}
          <DM.Separator className="my-1 h-px bg-line-subtle" />
          <DM.Item className={item} onSelect={() => navigate("/settings?s=workspaces")}>
            Manage or save current layout…
          </DM.Item>
        </DM.Content>
      </DM.Portal>
    </DM.Root>
  );
}
