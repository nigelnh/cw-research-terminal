import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { REALTIME_FLASH_DURATION_MS } from "@/components/common/realtime_value";

const css = fs.readFileSync(path.resolve(__dirname, "../design/global.css"), "utf8");

function rule(selector: string): string {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`${selector} not found in global.css`);
  return css.slice(start, css.indexOf("}", start) + 1);
}

function keyframes(name: string): string {
  const start = css.indexOf(`@keyframes ${name} {`);
  if (start < 0) throw new Error(`@keyframes ${name} not found in global.css`);
  return css.slice(start, css.indexOf("\n}", start) + 2);
}

describe("value flash timing", () => {
  it("flashes for the component's duration and stops there", () => {
    // The component removes the flash after REALTIME_FLASH_DURATION_MS; the animation must
    // end at the same moment or one of them cuts the other short.
    expect(REALTIME_FLASH_DURATION_MS).toBe(300);
    expect(rule(".realtime-flash")).toContain(`animation-duration: ${REALTIME_FLASH_DURATION_MS}ms;`);
  });

  it("has no fade: on at full colour, off at the end", () => {
    expect(rule(".realtime-flash")).toContain("animation-timing-function: step-end;");
    for (const tone of ["up", "down", "flat", "ceiling", "floor", "neutral"]) {
      const frames = keyframes(`realtime-flash-${tone}`);
      // Only `from` and `to`: an intermediate stop (the old "0%, 35%") is a hold-then-fade.
      expect(frames, tone).not.toMatch(/^\s*\d+%(\s*,\s*\d+%)*\s*\{/m);
      expect(frames, tone).toMatch(/from \{ background-color: color-mix/);
      expect(frames, tone).toMatch(/to \{ background-color: transparent; \}/);
    }
  });
});
