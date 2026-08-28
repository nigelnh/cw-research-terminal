import { useCallback, useSyncExternalStore } from "react";

/**
 * Minimal shareable-URL state over ``window.location.search``. No router dependency.
 *
 * - reads are reactive: a change to any tracked param (including browser back/forward)
 *   re-renders subscribers via ``useSyncExternalStore`` + a ``popstate`` listener;
 * - writes use ``history.pushState`` (new history entry -> back/forward works) or
 *   ``replaceState`` (no entry, for corrections/defaults);
 * - SSR / no-DOM safe: returns the provided default and no-ops on write.
 *
 * Target: copy the URL, open elsewhere -> the same research view reconstructs.
 */

const listeners = new Set<() => void>();
let cachedSearch = typeof window !== "undefined" ? window.location.search : "";

function notify() {
  cachedSearch = window.location.search;
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  if (listeners.size === 0) {
    window.addEventListener("popstate", notify);
  }
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      window.removeEventListener("popstate", notify);
    }
  };
}

function getSearchSnapshot(): string {
  return cachedSearch;
}

function getServerSnapshot(): string {
  return "";
}

export type UrlWriteMode = "push" | "replace";

function writeParams(mutate: (p: URLSearchParams) => void, mode: UrlWriteMode) {
  if (typeof window === "undefined") return;
  const params = new URLSearchParams(window.location.search);
  mutate(params);
  const qs = params.toString();
  const next = `${window.location.pathname}${qs ? `?${qs}` : ""}${window.location.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next === current) return;
  if (mode === "replace") window.history.replaceState(window.history.state, "", next);
  else window.history.pushState(window.history.state, "", next);
  notify();
}

/**
 * One string URL search param with a default. ``value`` is never the empty string -
 * when a set value equals ``defaultValue`` the param is removed (keeps URLs clean and
 * shareable views canonical).
 */
export function useSearchParam(
  key: string,
  defaultValue: string
): [string, (value: string, mode?: UrlWriteMode) => void] {
  const search = useSyncExternalStore(subscribe, getSearchSnapshot, getServerSnapshot);
  const raw = new URLSearchParams(search).get(key);
  const value = raw && raw.length > 0 ? raw : defaultValue;

  const setValue = useCallback(
    (next: string, mode: UrlWriteMode = "push") => {
      writeParams((p) => {
        if (!next || next === defaultValue) p.delete(key);
        else p.set(key, next);
      }, mode);
    },
    [key, defaultValue]
  );

  return [value, setValue];
}

/** Same, but for a param whose absence means ``null`` (e.g. selected symbol). */
export function useNullableSearchParam(
  key: string
): [string | null, (value: string | null, mode?: UrlWriteMode) => void] {
  const search = useSyncExternalStore(subscribe, getSearchSnapshot, getServerSnapshot);
  const raw = new URLSearchParams(search).get(key);
  const value = raw && raw.length > 0 ? raw : null;

  const setValue = useCallback(
    (next: string | null, mode: UrlWriteMode = "push") => {
      writeParams((p) => {
        if (!next) p.delete(key);
        else p.set(key, next);
      }, mode);
    },
    [key]
  );

  return [value, setValue];
}
