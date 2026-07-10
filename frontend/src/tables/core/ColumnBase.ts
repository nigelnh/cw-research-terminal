/**
 * Base column class with flexible or fixed width and formatting
 */

import type { Alignment, ColumnConfig } from "./types";

export class ColumnBase<T> {
  readonly key: string;
  readonly dataKey: keyof T & string;
  readonly header: string;
  readonly widthPx?: number;  // Optional fixed width
  readonly flex: number;      // Flex grow factor
  readonly align: Alignment;
  readonly semanticColor?: string;
  readonly color?: string | ((row: T) => string);
  readonly bgColor?: string | ((row: T) => string | undefined);
  readonly sortable: boolean;
  readonly sortArrowOnRight: boolean;
  readonly colorDependencies?: string[];
  private readonly customFormat?: (value: unknown, row?: T) => string;

  constructor(config: ColumnConfig<T>) {
    this.key = config.key;
    this.dataKey = config.dataKey ?? (config.key as keyof T & string);
    this.header = config.header;
    this.widthPx = config.widthPx;
    this.flex = config.flex ?? 1;  // Default flex: 1
    this.align = config.align;
    this.semanticColor = config.semanticColor;
    this.color = config.color;
    this.bgColor = config.bgColor;
    this.sortable = config.sortable ?? true;
    this.sortArrowOnRight = config.sortArrowOnRight ?? false;
    this.colorDependencies = config.colorDependencies;
    this.customFormat = config.format;
  }

  /**
   * Get text color for the cell
   */
  getColor(row: T, getRow?: (symbol: string) => any | undefined): string {
    if (typeof this.color === "function") {
      return (this.color as any)(row, getRow);
    }
    if (this.color) {
      return this.color;
    }
    return this.semanticColor ?? "inherit";
  }

  /**
   * Get background color for the cell
   */
  getBgColor(row: T, getRow?: (symbol: string) => any | undefined): string | undefined {
    if (typeof this.bgColor === "function") {
      return (this.bgColor as any)(row, getRow);
    }
    return this.bgColor;
  }

  /**
   * Get raw value from row
   */
  getValue(row: T): unknown {
    return row[this.dataKey];
  }

  /**
   * Format value for display
   * Override in subclasses for custom formatting
   */
  format(value: unknown, row?: T): string {
    if (this.customFormat) {
      return this.customFormat(value, row);
    }
    if (value === null || value === undefined || value === 0 || value === "0") {
      return "";
    }
    return String(value);
  }

  /**
   * Get formatted display value from row
   */
  getDisplayValue(row: T): string {
    return this.format(this.getValue(row), row);
  }
}

/**
 * Column for price values (2 decimal places)
 */
export class PriceColumn<T> extends ColumnBase<T> {
  format(value: unknown, row?: T): string {
    const custom = super.format(value, row);
    // If super.format returned something other than String(value), it means customFormat was used
    if ((this as any).customFormat) return custom;

    if (value === null || value === undefined) {
      return "";
    }
    const num = typeof value === "number" ? value : parseFloat(String(value));
    if (isNaN(num) || num === 0) return "";
    return (num / 1000).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
}

/**
 * Column for quantity values (divided by 1000, with 2 decimal places)
 */
export class QuantityColumn<T> extends ColumnBase<T> {
  format(value: unknown, row?: T): string {
    const custom = super.format(value, row);
    if ((this as any).customFormat) return custom;

    if (value === null || value === undefined) {
      return "";
    }
    const num = typeof value === "number" ? value : parseFloat(String(value));
    if (isNaN(num) || num === 0) return "";
    return (num / 1000).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
}

/**
 * Column for large numbers (with thousand separators)
 */
export class LargeNumberColumn<T> extends ColumnBase<T> {
  format(value: unknown, row?: T): string {
    const custom = super.format(value, row);
    if ((this as any).customFormat) return custom;

    if (value === null || value === undefined) {
      return "";
    }
    const num = typeof value === "number" ? value : parseInt(String(value), 10);
    if (isNaN(num) || num === 0) return "";
    return num.toLocaleString();
  }
}
