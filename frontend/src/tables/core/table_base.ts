/**
 * Abstract base table class
 * Provides OOP structure with fixed sizing and change detection
 */

import type { ColumnBase } from "./column_base";
import type { TableConfig, CellChange, ChangeDirection } from "./types";

export abstract class TableBase<T extends Record<string, unknown>> {
  abstract readonly config: TableConfig;
  readonly needsLiveHydration?: boolean;

  /**
   * Get column definitions
   * Must be implemented by subclasses
   */
  abstract getColumns(): ColumnBase<T>[];

  /**
   * Get unique row key
   * Must be implemented by subclasses
   */
  abstract getRowKey(row: T, index?: number): string;

  /**
   * Calculate total table width from columns
   */
  getTotalWidth(): number {
    return this.getColumns().reduce((sum, col) => sum + (col.widthPx || 0), 0);
  }

  /**
   * Calculate total table height
   */
  getTotalHeight(): number {
    return this.config.headerHeightPx + this.config.rowHeightPx * this.config.maxRows;
  }

  /**
   * Detect changes between previous and current rows
   * Returns list of changed cells with direction (up/down)
   */
  diff(prevRows: T[], nextRows: T[]): Map<string, CellChange> {
    const changes = new Map<string, CellChange>();
    const prevMap = new Map<string, T>();

    // Build lookup for previous rows
    for (const row of prevRows) {
      prevMap.set(this.getRowKey(row), row);
    }

    // Compare each new row with previous
    for (const nextRow of nextRows) {
      const rowKey = this.getRowKey(nextRow);
      const prevRow = prevMap.get(rowKey);

      if (!prevRow) {
        // New row - mark all cells as "same" (no flash for new rows)
        continue;
      }

      // Compare each column
      for (const col of this.getColumns()) {
        const prevValue = col.getValue(prevRow);
        const newValue = col.getValue(nextRow);

        if (prevValue !== newValue) {
          const direction = this.getChangeDirection(prevValue, newValue);
          const cellKey = `${rowKey}:${col.key}`;

          changes.set(cellKey, {
            rowKey,
            colKey: col.key,
            direction,
            prevValue,
            newValue,
          });
        }
      }
    }

    return changes;
  }

  /**
   * Determine if value went up or down
   */
  private getChangeDirection(prev: unknown, next: unknown): ChangeDirection {
    const prevNum = typeof prev === "number" ? prev : parseFloat(String(prev));
    const nextNum = typeof next === "number" ? next : parseFloat(String(next));

    if (isNaN(prevNum) || isNaN(nextNum)) {
      return "same";
    }

    if (nextNum > prevNum) {
      return "up";
    } else if (nextNum < prevNum) {
      return "down";
    }
    return "same";
  }

  /**
   * Get row flash color override
   * Returns undefined to use default flash logic (green/red based on direction)
   */
  getFlashColor(
    _row: T,
    _colKey: string,
    _direction: "up" | "down",
    _getRow?: (symbol: string) => any | undefined
  ): string | undefined {
    return undefined;
  }
}

