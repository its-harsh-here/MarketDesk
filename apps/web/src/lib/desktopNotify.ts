import { useEffect, useRef, useState } from "react";
import type { InboxItem } from "@/lib/api/client";

/** Desktop notifications for new alerts and briefings while MarketDesk is open (per device, opt-in). */
const KEY = "md-desktop-notify";

export type NotifyState = "unsupported" | "denied" | "off" | "on";

function supported() {
  return typeof window !== "undefined" && "Notification" in window;
}

export function notifyState(): NotifyState {
  if (!supported()) return "unsupported";
  if (Notification.permission === "denied") return "denied";
  let on = false;
  try {
    on = localStorage.getItem(KEY) === "1";
  } catch {
    on = false;
  }
  return on && Notification.permission === "granted" ? "on" : "off";
}

export function useNotifySetting() {
  const [state, setState] = useState<NotifyState>(() => notifyState());
  const enable = async () => {
    if (!supported()) return;
    const perm = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
    try {
      localStorage.setItem(KEY, perm === "granted" ? "1" : "0");
    } catch {
      /* per-device convenience only */
    }
    setState(notifyState());
  };
  const disable = () => {
    try {
      localStorage.setItem(KEY, "0");
    } catch {
      /* ignore */
    }
    setState(notifyState());
  };
  return { state, enable, disable };
}

/** Show a desktop notification for each unread item that arrives after this page loaded. */
export function useDesktopNotifications(items: InboxItem[] | undefined) {
  const seen = useRef<Set<string> | null>(null);
  useEffect(() => {
    if (!items) return;
    const ids = items.map((i) => `${i.type}-${i.id}`);
    if (seen.current === null) {
      seen.current = new Set(ids); // what was already there when the page opened is not "new"
      return;
    }
    const fresh = items.filter((i) => !seen.current!.has(`${i.type}-${i.id}`));
    ids.forEach((id) => seen.current!.add(id));
    if (!fresh.length || notifyState() !== "on") return;
    for (const i of fresh.slice(0, 3)) {
      try {
        // the tag makes two open tabs show one notification
        new Notification(i.type === "alert" ? "MarketDesk alert" : "MarketDesk briefing", { body: i.title, tag: `md-${i.type}-${i.id}` });
      } catch {
        /* some browsers only allow notifications from a service worker */
      }
    }
  }, [items]);
}
