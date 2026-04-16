/**
 * Core table framework types
 */

export type Alignment = "left" | "center" | "right";

export type ChangeDirection = "up" | "down" | "same";

export interface CellChange {
  rowKey: string;
  colKey: string;
  direction: ChangeDirection;
  prevValue: unknown;
  newValue: unknown;
}

export interface ColumnConfig<T> {
  key: keyof T & string;
  header: string;
  widthPx?: number;  // Optional fixed width
  flex?: number;     // Flex grow factor (default: 1)
  align: Alignment;
  semanticColor?: string;
  color?: string | ((row: T, getRow?: (symbol: string) => any | undefined) => string);
  colorDependencies?: (keyof T & string)[];
  bgColor?: string | ((row: T, getRow?: (symbol: string) => any | undefined) => string | undefined);
  format?: (value: unknown) => string;
  sortable?: boolean;
  sortArrowOnRight?: boolean;
}

export interface TableConfig {
  headerHeightPx: number;
  rowHeightPx: number;
  maxRows: number;
  fontSize: number;
  headerFontSize: number;
}

