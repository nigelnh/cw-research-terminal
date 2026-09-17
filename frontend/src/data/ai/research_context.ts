import type { WatchlistItem } from "@/domain/models";

/** Phải nhỏ hơn hoặc bằng giới hạn context envelope của backend. */
export const AI_CONTEXT_SYMBOL_LIMIT = 200;

function canonicalSymbol(value: string | null | undefined): string | null {
  const symbol = value?.trim().toUpperCase();
  return symbol || null;
}

/**
 * Tạo danh sách mã gọn để gửi cùng request AI. Mã đang chọn và mã cơ sở được ưu tiên;
 * model có thể lấy các mã khác qua tool. Giới hạn này giúp universe lớn không làm hỏng
 * toàn bộ request chat.
 */
export function buildAiContextSymbols(
  items: readonly Pick<WatchlistItem, "symbol">[],
  selectedSymbol?: string | null,
  selectedUnderlyingSymbol?: string | null,
): string[] {
  const unique = new Set<string>();

  for (const candidate of [
    selectedSymbol,
    selectedUnderlyingSymbol,
    ...items.map((item) => item.symbol),
  ]) {
    const symbol = canonicalSymbol(candidate);
    if (symbol) unique.add(symbol);
    if (unique.size >= AI_CONTEXT_SYMBOL_LIMIT) break;
  }

  return [...unique];
}
