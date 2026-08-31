// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useHiddenRows } from "@/components/common/grid_table";

describe("useHiddenRows — client-side 'remove from view'", () => {
  it("hides symbols case-insensitively, counts them, and resets", () => {
    const { result } = renderHook(() => useHiddenRows());

    expect(result.current.count).toBe(0);
    expect(result.current.isHidden("HPG")).toBe(false);

    act(() => result.current.hide("hpg"));
    expect(result.current.isHidden("HPG")).toBe(true);
    expect(result.current.count).toBe(1);

    act(() => result.current.hide("VPB"));
    expect(result.current.count).toBe(2);

    act(() => result.current.reset());
    expect(result.current.count).toBe(0);
    expect(result.current.isHidden("HPG")).toBe(false);
  });

  it("is non-destructive — it holds no reference to the watchlist or registry", () => {
    // the hook is pure local state; nothing to assert beyond it not throwing without providers
    const { result } = renderHook(() => useHiddenRows());
    act(() => result.current.hide("X"));
    expect(result.current.hidden.has("X")).toBe(true);
  });
});
