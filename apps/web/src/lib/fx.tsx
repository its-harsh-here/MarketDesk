/** Visual effects helpers. All decoration: nothing here carries information, and everything honours
 * prefers-reduced-motion and the "Visual effects" preference (stored per browser as md-fx). */
import { useEffect, useRef, useState } from "react";

export type FxMode = "full" | "calm";
const KEY = "md-fx";

/** Phones and touch devices default to calm effects (blur and animation cost most there); a stored choice wins. */
const lowPower = () => typeof window.matchMedia === "function" && window.matchMedia("(max-width: 768px), (pointer: coarse)").matches;

export function readFx(): FxMode {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "calm" || v === "full") return v;
  } catch {
    /* storage unavailable */
  }
  return lowPower() ? "calm" : "full";
}

export function applyFx(mode: FxMode) {
  if (mode === "calm") document.documentElement.setAttribute("data-fx", "off");
  else document.documentElement.removeAttribute("data-fx");
  try {
    localStorage.setItem(KEY, mode);
  } catch {
    /* storage unavailable */
  }
}

const reduced = () => typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
export const fxActive = () => !reduced() && document.documentElement.getAttribute("data-fx") !== "off";

/** Fixed ambient layer (aurora, grid, pointer glow) and the scroll progress line. Also runs the one pointer
 * listener that feeds --mx/--my to the surface under the cursor (panels, buttons) and --px/--py to the glow. */
export function FxBackground() {
  useEffect(() => {
    let frame = 0;
    let last: PointerEvent | null = null;
    const flush = () => {
      frame = 0;
      const e = last;
      if (!e || !fxActive()) return;
      document.documentElement.style.setProperty("--px", `${e.clientX}px`);
      document.documentElement.style.setProperty("--py", `${e.clientY}px`);
      const el = (e.target as Element | null)?.closest?.<HTMLElement>(".md-btn, .md-panel");
      const hosts = el ? [el, el.classList.contains("md-btn") ? el.closest<HTMLElement>(".md-panel") : null] : [];
      for (const h of hosts) {
        if (!h) continue;
        const r = h.getBoundingClientRect();
        h.style.setProperty("--mx", `${e.clientX - r.left}px`);
        h.style.setProperty("--my", `${e.clientY - r.top}px`);
      }
    };
    const onMove = (e: PointerEvent) => {
      if (e.pointerType === "touch") return;
      last = e;
      if (!frame) frame = requestAnimationFrame(flush);
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    // Pause the background animation while the tab is hidden (no CPU spent on what nobody sees).
    const onVisibility = () => document.documentElement.toggleAttribute("data-hidden", document.hidden);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pointermove", onMove);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);
  return (
    <>
      <div className="fx-bg" aria-hidden>
        <i className="a1" />
        <i className="a2" />
        <i className="a3" />
        <i className="grid" />
        <i className="cursor" />
      </div>
      <div className="fx-progress" aria-hidden />
    </>
  );
}

/** Class that flashes a figure green or red for a moment when its numeric value changes (never on first render). */
export function useFlash(value: unknown): string {
  const num = typeof value === "string" || typeof value === "number" ? Number(String(value).replace(/[^0-9.+-]/g, "")) : NaN;
  const prev = useRef(num);
  const [cls, setCls] = useState("");
  useEffect(() => {
    const before = prev.current;
    prev.current = num;
    if (!Number.isFinite(num) || !Number.isFinite(before) || num === before) return;
    setCls(num > before ? "fx-flash-up" : "fx-flash-down");
    const t = window.setTimeout(() => setCls(""), 1150);
    return () => window.clearTimeout(t);
  }, [num]);
  return cls;
}

/** Replays the page-enter animation on an element whenever `key` changes, without remounting the page. */
export function usePageEnter<T extends HTMLElement>(key: string) {
  const ref = useRef<T>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || !fxActive()) return;
    el.classList.remove("page-enter");
    void el.offsetWidth; // restart the animation
    el.classList.add("page-enter");
  }, [key]);
  return ref;
}

/** Runs a DOM change inside a View Transition (a circular reveal from the pointer) where supported. */
export function withReveal(change: () => void) {
  const doc = document as Document & { startViewTransition?: (cb: () => void) => unknown };
  if (!doc.startViewTransition || !fxActive()) return change();
  const s = getComputedStyle(document.documentElement);
  document.documentElement.style.setProperty("--vx", s.getPropertyValue("--px") || "100%");
  document.documentElement.style.setProperty("--vy", s.getPropertyValue("--py") || "0%");
  doc.startViewTransition(change);
}
