
import { colors } from "@/design/tokens";
import type { EquityRow } from "./types";

/**
 * Get color based on a specific price relative to reference, ceiling, and floor
 */
export function getPriceColor(price: number, ref: number, ceil: number, floor: number): string {
    if (!price) {
        return colors.textSecondary;
    }
    if (price === ceil) {
        return colors.purple; // Ceiling
    }
    if (price === floor) {
        return colors.cyan; // Floor
    }
    if (price > ref) {
        return colors.increase; // Green
    }
    if (price < ref) {
        return colors.decrease; // Red
    }
    return colors.yellow; // Reference / No Change
}

/**
 * Get color based on price trend relative to reference, ceiling, and floor
 * (Defaults to using Traded price)
 */
export function getTrendColor(row: EquityRow): string {
    return getPriceColor(row.Traded, row.Ref, row.Ceil, row.Floor);
}
