/** Visual effects helpers. All decoration: nothing here carries information, and everything honours
 * prefers-reduced-motion and the "Visual effects" preference (stored per browser as md-fx). */
import { useIsFetching } from "@tanstack/react-query";
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
    let tilted: HTMLElement | null = null;
    // A ripple from the point a button was pressed.
    const onDown = (e: PointerEvent) => {
      const btn = (e.target as Element | null)?.closest?.<HTMLElement>(".md-btn");
      if (!btn || !fxActive() || (btn as HTMLButtonElement).disabled) return;
      const r = btn.getBoundingClientRect();
      const dot = document.createElement("span");
      dot.className = "fx-ripple";
      dot.setAttribute("aria-hidden", "true");
      dot.style.left = `${e.clientX - r.left}px`;
      dot.style.top = `${e.clientY - r.top}px`;
      btn.appendChild(dot);
      window.setTimeout(() => dot.remove(), 650);
    };
    window.addEventListener("pointerdown", onDown, { passive: true });
    const flush = () => {
      frame = 0;
      const e = last;
      if (!e || !fxActive()) return;
      document.documentElement.style.setProperty("--px", `${e.clientX}px`);
      document.documentElement.style.setProperty("--py", `${e.clientY}px`);
      const tilt = (e.target as Element | null)?.closest?.<HTMLElement>(".fx-tilt");
      if (tilt !== tilted) {
        tilted?.style.removeProperty("--rx");
        tilted?.style.removeProperty("--ry");
        tilted = tilt ?? null;
      }
      if (tilt) {
        const r = tilt.getBoundingClientRect();
        const x = (e.clientX - r.left) / r.width - 0.5;
        const y = (e.clientY - r.top) / r.height - 0.5;
        tilt.style.setProperty("--ry", `${(x * 7).toFixed(2)}deg`);
        tilt.style.setProperty("--rx", `${(-y * 7).toFixed(2)}deg`);
      }
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
    // Panels below the fold play their entrance once, when they first scroll into view.
    let io: IntersectionObserver | null = null;
    let mo: MutationObserver | null = null;
    if (typeof IntersectionObserver === "function" && typeof MutationObserver === "function") {
      const seen = new WeakSet<Element>();
      io = new IntersectionObserver((entries) => {
        for (const en of entries) {
          const first = !seen.has(en.target);
          seen.add(en.target);
          if (en.isIntersecting) {
            if (!first && fxActive()) en.target.classList.add("fx-in"); // was off screen when built
            io?.unobserve(en.target);
          }
        }
      }, { rootMargin: "0px 0px -6% 0px" });
      const watch = (root: ParentNode) => root.querySelectorAll?.(".md-panel").forEach((el) => io?.observe(el));
      watch(document);
      mo = new MutationObserver((muts) => {
        for (const m of muts) m.addedNodes.forEach((n) => {
          if (!(n instanceof Element)) return;
          if (n.classList.contains("md-panel")) io?.observe(n);
          watch(n);
        });
      });
      mo.observe(document.body, { childList: true, subtree: true });
    }
    // Pause the background animation while the tab is hidden (no CPU spent on what nobody sees).
    const onVisibility = () => document.documentElement.toggleAttribute("data-hidden", document.hidden);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerdown", onDown);
      io?.disconnect();
      mo?.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);
  return (
    <>
      <div className="fx-bg" aria-hidden>
        <div className="parallax">
          <i className="ribbon" />
          <i className="a1" />
          <i className="a2" />
          <i className="a3" />
        </div>
        <i className="grid" />
        <Constellation />
        <i className="cursor" />
        <i className="grain" />
      </div>
      <div className="fx-progress" aria-hidden />
      <LoadingBeam />
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

/** A thin moving beam at the very top while any data request is in flight (after a short delay, so quick ones
 * do not flicker). Decoration: each panel still shows its own loading and refreshing state. */
function LoadingBeam() {
  const busy = useIsFetching() > 0;
  return <div className="fx-loading" data-on={busy ? "" : undefined} aria-hidden />;
}

/** Slow-drifting points joined by faint lines, brighter near the pointer. Desktop and full effects only; stops
 * while the tab is hidden; a fixed, small number of points so the cost stays flat. */
function Constellation() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx || typeof window.matchMedia !== "function" || window.matchMedia("(max-width: 767px)").matches) return;
    let w = 0, h = 0, raf = 0, px = -9999, py = -9999;
    const N = 46;
    const pts = Array.from({ length: N }, () => ({ x: Math.random(), y: Math.random(), vx: (Math.random() - 0.5) * 0.00022, vy: (Math.random() - 0.5) * 0.00022, r: 0.6 + Math.random() * 1.4 }));
    const size = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = window.innerWidth; h = window.innerHeight;
      canvas.width = w * dpr; canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    const colour = () => getComputedStyle(document.documentElement).getPropertyValue("--accent-2").trim() || "#22d3ee";
    let stroke = colour();
    let tick = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      if (document.hidden || !fxActive()) { ctx.clearRect(0, 0, w, h); return; }
      if (++tick % 120 === 0) stroke = colour(); // follows a theme change
      ctx.clearRect(0, 0, w, h);
      for (const p of pts) {
        p.x = (p.x + p.vx + 1) % 1; p.y = (p.y + p.vy + 1) % 1;
      }
      ctx.strokeStyle = stroke; ctx.fillStyle = stroke; ctx.lineWidth = 0.6;
      for (let i = 0; i < N; i++) {
        const a = pts[i], ax = a.x * w, ay = a.y * h;
        const near = Math.max(0, 1 - Math.hypot(ax - px, ay - py) / 260);
        ctx.globalAlpha = 0.25 + near * 0.6;
        ctx.beginPath(); ctx.arc(ax, ay, a.r + near * 1.6, 0, 6.283); ctx.fill();
        for (let j = i + 1; j < N; j++) {
          const b = pts[j], d = Math.hypot(ax - b.x * w, ay - b.y * h);
          if (d < 150) {
            ctx.globalAlpha = (1 - d / 150) * (0.1 + near * 0.35);
            ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(b.x * w, b.y * h); ctx.stroke();
          }
        }
      }
      ctx.globalAlpha = 1;
    };
    const onMove = (e: PointerEvent) => { px = e.clientX; py = e.clientY; };
    size();
    window.addEventListener("resize", size);
    window.addEventListener("pointermove", onMove, { passive: true });
    if (!reduced()) raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", size);
      window.removeEventListener("pointermove", onMove);
    };
  }, []);
  return <canvas ref={ref} />;
}

/** Counts a formatted figure up to its value (e.g. "₹10,525.00", "+4.25%", "1.2 Cr") when it first appears or
 * changes, keeping its prefix, suffix, sign and decimals; the final frame is always the exact text given. */
export function useCountUp(text: string | null): string | null {
  const [shown, setShown] = useState(text);
  const from = useRef<number | null>(null);
  useEffect(() => {
    setShown(text);
    if (text === null || typeof window.matchMedia !== "function" || !fxActive()) return;
    const m = /^([^0-9]*?)(\d[\d,]*)(\.\d+)?(.*)$/s.exec(text);
    if (!m) return;
    const [, pre, int, frac = "", post] = m;
    const target = Number(int.replace(/,/g, "") + frac);
    if (!Number.isFinite(target) || target === 0) return;
    const start = from.current ?? 0;
    from.current = target;
    const decimals = frac ? frac.length - 1 : 0;
    const locale = /^\d{1,2}(,\d{2})+,\d{3}$/.test(int) ? "en-IN" : int.includes(",") ? "en-US" : undefined;
    const fmt = (n: number) => (locale ? n.toLocaleString(locale, { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) : n.toFixed(decimals));
    const t0 = performance.now(), dur = 750;
    let raf = requestAnimationFrame(function step(now) {
      const k = Math.min(1, (now - t0) / dur);
      const eased = 1 - Math.pow(1 - k, 4);
      if (k < 1) {
        setShown(pre + fmt(start + (target - start) * eased) + post);
        raf = requestAnimationFrame(step);
      } else setShown(text);
    });
    return () => cancelAnimationFrame(raf);
  }, [text]);
  return shown;
}
