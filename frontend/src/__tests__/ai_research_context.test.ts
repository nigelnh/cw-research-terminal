import { describe, expect, it } from "vitest";
import {
  AI_CONTEXT_SYMBOL_LIMIT,
  buildAiContextSymbols,
} from "@/data/ai/research_context";

describe("AI research context symbols", () => {
  it("bounds a large universe and prioritizes the selected CW and underlying", () => {
    const items = Array.from({ length: 319 }, (_, index) => ({
      symbol: `CW${String(index).padStart(4, "0")}`,
    }));

    const symbols = buildAiContextSymbols(items, " chpg2625 ", "hpg");

    expect(symbols).toHaveLength(AI_CONTEXT_SYMBOL_LIMIT);
    expect(symbols.slice(0, 2)).toEqual(["CHPG2625", "HPG"]);
    expect(symbols[symbols.length - 1]).toBe("CW0197");
  });

  it("normalizes and de-duplicates symbols without moving selected context", () => {
    const symbols = buildAiContextSymbols(
      [{ symbol: "hpg" }, { symbol: "CHPG2625" }, { symbol: " HPG " }],
      "chpg2625",
      "HPG",
    );

    expect(symbols).toEqual(["CHPG2625", "HPG"]);
  });
});
