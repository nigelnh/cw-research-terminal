import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
  type RefObject,
} from "react";
import { prefersReducedMotion, spring } from "@/design/motion";

const useBrowserLayoutEffect =
  typeof document === "undefined" ? useEffect : useLayoutEffect;

/** Fixed overlays never enlarge the table's scroll area when a calendar opens. */
export function useFixedPopover(
  open: boolean,
  anchor: RefObject<HTMLElement>,
  panel: RefObject<HTMLElement>,
  width: number,
): CSSProperties {
  const [position, setPosition] = useState({
    left: 0,
    top: 0,
    width,
    maxHeight: 600,
  });
  useBrowserLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const rect = anchor.current?.getBoundingClientRect();
      if (!rect) return;
      const w = Math.min(width, window.innerWidth - 24);
      const maxHeight = Math.max(80, window.innerHeight - 24);
      const h = Math.min(panel.current?.offsetHeight ?? 260, maxHeight);
      const below = window.innerHeight - rect.bottom - 12;
      const preferred =
        below >= h || below >= rect.top ? rect.bottom + 6 : rect.top - h - 6;
      const next = {
        left: Math.max(
          12,
          Math.min(rect.right - w, window.innerWidth - w - 12),
        ),
        top: Math.max(12, Math.min(preferred, window.innerHeight - h - 12)),
        width: w,
        maxHeight,
      };
      setPosition((current) =>
        Object.keys(next).every(
          (key) =>
            current[key as keyof typeof next] ===
            next[key as keyof typeof next],
        )
          ? current
          : next,
      );
    };
    place();
    const observer = new ResizeObserver(place);
    if (panel.current) observer.observe(panel.current);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, anchor, panel, width]);
  return { position: "fixed", ...position };
}

export function FilterPopover({
  active,
  label,
  children,
}: {
  active: boolean;
  label: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [closing, setClosing] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const closeTimer = useRef<number | undefined>(undefined);
  const id = useId();
  const position = useFixedPopover(open, trigger, panel, 360);

  // Let the panel play its lift-out before it leaves the DOM.
  const close = useCallback(() => {
    window.clearTimeout(closeTimer.current);
    if (prefersReducedMotion()) {
      setClosing(false);
      setOpen(false);
      return;
    }
    setClosing(true);
    closeTimer.current = window.setTimeout(() => {
      setClosing(false);
      setOpen(false);
    }, spring("snap").duration);
  }, []);

  useEffect(() => () => window.clearTimeout(closeTimer.current), []);

  useEffect(() => {
    if (!open || closing) return;
    const outside = (e: PointerEvent) => {
      if (
        !trigger.current?.contains(e.target as Node) &&
        !panel.current?.contains(e.target as Node)
      )
        close();
    };
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      close();
      trigger.current?.focus({ preventScroll: true });
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", key);
    panel.current
      ?.querySelector<HTMLInputElement>("input")
      ?.focus({ preventScroll: true });
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", key);
    };
  }, [open, closing, close]);

  return (
    <div className="filter-anchor">
      <button
        ref={trigger}
        type="button"
        className={`filter-trigger focus-ring${active ? " is-active" : ""}`}
        aria-expanded={open && !closing}
        aria-controls={open ? id : undefined}
        aria-haspopup="dialog"
        onClick={() => (open ? close() : setOpen(true))}
      >
        FILTER <span className="filter-caret">▾</span>
      </button>
      {open && (
        <div
          ref={panel}
          id={id}
          role="dialog"
          aria-label={label}
          className={`filter-panel mono${closing ? " is-closing" : ""}`}
          style={position}
        >
          {children}
        </div>
      )}
    </div>
  );
}
