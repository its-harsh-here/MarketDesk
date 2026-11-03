import * as RT from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";

export const TooltipProvider = RT.Provider;

/** Radix tooltips open on hover and on keyboard focus, so content stays reachable without a mouse. */
export function Tooltip({ content, children, side = "top" }: { content: ReactNode; children: ReactNode; side?: "top" | "bottom" | "left" | "right" }) {
  return (
    <RT.Root delayDuration={250}>
      <RT.Trigger asChild>{children}</RT.Trigger>
      <RT.Portal>
        <RT.Content
          side={side}
          sideOffset={6}
          collisionPadding={12}
          className="anim-pop z-50 max-w-72 rounded-md border border-line bg-elevated px-3 py-2 text-xs leading-5 text-fg shadow-[var(--shadow-pop)]"
        >
          {content}
        </RT.Content>
      </RT.Portal>
    </RT.Root>
  );
}
