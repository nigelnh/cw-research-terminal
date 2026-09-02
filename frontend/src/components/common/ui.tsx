import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

const useBrowserLayoutEffect =
  typeof document === "undefined" ? useEffect : useLayoutEffect;

export function useStoredState<T>(key: string, fallback: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = window.localStorage.getItem(key);
      const parsed = stored == null ? fallback : JSON.parse(stored);
      return typeof parsed === typeof fallback ? parsed : fallback;
    } catch {
      return fallback;
    }
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* storage optional */
    }
  }, [key, value]);
  return [value, setValue] as const;
}

/** Portalled beyond table overflow; click/keyboard driven with collision handling. */
export function Popover({
  label,
  children,
  width = 360,
  active = false,
  icon,
  className = "",
}: {
  label: string;
  children: ReactNode | ((close: () => void) => ReactNode);
  width?: number;
  active?: boolean;
  icon?: ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0, maxHeight: 500 });
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const close = () => {
    setOpen(false);
    trigger.current?.focus();
  };
  useBrowserLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const r = trigger.current?.getBoundingClientRect();
      if (!r) return;
      const w = Math.min(width, window.innerWidth - 24);
      const height = Math.min(
        panel.current?.scrollHeight ?? 400,
        window.innerHeight - 24,
      );
      const below = window.innerHeight - r.bottom - 16;
      const top =
        below >= height || below >= r.top
          ? r.bottom + 6
          : Math.max(12, r.top - height - 6);
      setPosition({
        top,
        left: Math.max(12, Math.min(r.right - w, window.innerWidth - w - 12)),
        maxHeight: window.innerHeight - top - 12,
      });
    };
    place();
    const outside = (event: PointerEvent) => {
      if (
        !trigger.current?.contains(event.target as Node) &&
        !panel.current?.contains(event.target as Node)
      )
        setOpen(false);
    };
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        close();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", key);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", key);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, width]);
  useEffect(() => {
    if (open)
      panel.current?.querySelector<HTMLElement>("input,button,select")?.focus();
  }, [open]);
  return (
    <>
      <button
        ref={trigger}
        type="button"
        className={`btn ${active ? "is-active" : ""} ${className}`}
        aria-label={label}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={(e) => {
          e.stopPropagation();
          setOpen(!open);
        }}
      >
        {icon ?? label}
      </button>
      {open &&
        createPortal(
          <div
            ref={panel}
            role="dialog"
            aria-label={label}
            className="popover"
            style={{
              ...position,
              width: Math.min(width, window.innerWidth - 24),
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {typeof children === "function" ? children(close) : children}
          </div>,
          document.body,
        )}
    </>
  );
}

export function useDialogFocus(
  ref: RefObject<HTMLElement>,
  onClose: () => void,
) {
  const latestClose = useRef(onClose);
  latestClose.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const root = ref.current;
    const focusable = () =>
      Array.from(
        root?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), textarea, select, a[href], [tabindex="0"]',
        ) ?? [],
      );
    (
      root?.querySelector<HTMLElement>("input, textarea") ?? focusable()[0]
    )?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        latestClose.current();
      }
      if (e.key === "Tab") {
        const els = focusable();
        const first = els[0];
        const last = els[els.length - 1];
        if (
          e.shiftKey &&
          (document.activeElement === first ||
            !root?.contains(document.activeElement))
        ) {
          e.preventDefault();
          last?.focus();
        } else if (
          !e.shiftKey &&
          (document.activeElement === last ||
            !root?.contains(document.activeElement))
        ) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("keydown", key);
      previous?.focus();
    };
  }, [ref]);
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      {children && <p>{children}</p>}
      {action && <div className="actions">{action}</div>}
    </div>
  );
}
export function Notice({
  children,
  error = false,
  action,
}: {
  children: ReactNode;
  error?: boolean;
  action?: ReactNode;
}) {
  return (
    <div
      className={`notice ${error ? "notice-error" : ""}`}
      role={error ? "alert" : "status"}
    >
      <span>{children}</span>
      {action}
    </div>
  );
}
export function UndoNotice({
  text,
  undo,
  dismiss,
}: {
  text: string;
  undo: () => void;
  dismiss: () => void;
}) {
  return (
    <div className="undo-notice" role="status">
      <span>{text}</span>
      <button className="btn btn-link" onClick={undo}>
        Undo
      </button>
      <button
        className="icon-btn"
        aria-label="Dismiss notification"
        onClick={dismiss}
      >
        <X size={14} />
      </button>
    </div>
  );
}
export function HelpLabel({
  children,
  description,
}: {
  children: ReactNode;
  description: string;
}) {
  return (
    <span className="help-label" tabIndex={0}>
      {children}
      <span aria-hidden="true" className="help-dot">
        i
      </span>
      <span role="tooltip" className="help-tooltip">
        {description}
      </span>
    </span>
  );
}
