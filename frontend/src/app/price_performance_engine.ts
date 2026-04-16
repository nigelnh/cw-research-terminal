import Holidays from 'date-holidays';

/**
 * Price Performance Engine
 * Logic for calculating $P_{prev}$ (baseline) based on interval/view_indicator
 */

export type ViewIndicator = '1m' | '5m' | '15m' | '30m' | '1h' | 'D' | 'W' | 'M';

export interface HistoricalDataPoint {
    t: string; // Time string from API (e.g., "01-01-2023 09:00")
    o: string | number;
    h: string | number;
    l: string | number;
    c: string | number;
    v?: string | number;
}

export interface PerformanceResult {
    baselinePrice: number;
    currentPrice: number;
    deltaP: number;
    percentDeltaP: number;
    indicator: ViewIndicator;
    timestamp: number;
}

/**
 * Reimplement a dynamic price-performance engine
 */
export class PricePerformanceEngine {
    private static hd = new Holidays('VN');

    /**
     * Parse the time string from API to milliseconds
     */
    static parseTime(t: string): number {
        if (!t) return 0;
        const parts = t.split(' ');
        const dateParts = parts[0].split(/[/-]|\./);
        if (dateParts.length < 3) return 0;
        
        let d, m, y;
        if (dateParts[0].length === 4) {
            y = parseInt(dateParts[0], 10); 
            m = parseInt(dateParts[1], 10) - 1; 
            d = parseInt(dateParts[2], 10);
        } else {
            d = parseInt(dateParts[0], 10); 
            m = parseInt(dateParts[1], 10) - 1; 
            y = parseInt(dateParts[2], 10);
        }
        
        if (parts.length > 1 && parts[1]) {
            const timeParts = parts[1].split(':');
            const hh = parseInt(timeParts[0], 10) || 0;
            const mm = parseInt(timeParts[1], 10) || 0;
            const ss = parseInt(timeParts[2], 10) || 0;
            // Use Date.UTC to treat API wall-clock time as UTC for consistent x-axis display.
            // This ensures 09:15 in API always shows as 09:15 on chart regardless of browser timezone.
            return Date.UTC(y, m, d, hh, mm, ss);
        } else {
            return Date.UTC(y, m, d);
        }
    }

    /**
     * Robust field extractor for OHLCV data to handle various API response formats
     */
    static extractOHLCV(item: any): { o: number, h: number, l: number, c: number, v: number, t: string } {
        const get = (keys: string[]) => {
            for (const key of keys) {
                if (item[key] !== undefined && item[key] !== null) return item[key];
            }
            return undefined;
        };

        return {
            o: PricePerformanceEngine.parseNum(get(['o', 'O', 'open', 'Open', 'openIndex', 'openPrice'])),
            h: PricePerformanceEngine.parseNum(get(['h', 'H', 'high', 'High', 'highIndex', 'highPrice'])),
            l: PricePerformanceEngine.parseNum(get(['l', 'L', 'low', 'Low', 'lowIndex', 'lowPrice'])),
            c: PricePerformanceEngine.parseNum(get(['c', 'C', 'close', 'Close', 'closeIndex', 'closePrice', 'index', 'lastIndex', 'matchPrice'])),
            v: PricePerformanceEngine.parseNum(get(['v', 'V', 'volume', 'Volume', 'vol', 'Vol', 'totalVol', 'totalVolume', 'totalQtty'])),
            t: get(['t', 'T', 'time', 'Time', 'date', 'Date']) || ''
        };
    }

    /**
     * Helper to parse number strings that might have commas
     */
    static parseNum(v: any): number {
        if (v === null || v === undefined) return 0;
        if (typeof v === 'number') return v;
        const s = String(v).replace(/,/g, '');
        return parseFloat(s) || 0;
    }

    /**
     * Helper to check if a date is a non-trading day (weekend or VN holiday)
     */
    static isNonTradingDay(date: Date): boolean {
        // Use UTC day as we're treating timestamps as UTC
        const day = date.getUTCDay();
        const isWeekend = day === 0 || day === 6; // Sunday = 0, Saturday = 6
        if (isWeekend) return true;

        // Check for holidays
        // date-holidays works with local time, so we convert UTC date to a local date object
        // for consistent holiday check against VN rules.
        const d = new Date(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
        const holiday = PricePerformanceEngine.hd.isHoliday(d);
        return !!holiday;
    }

    /**
     * Helper to check if a date is weekend (Sat/Sun)
     */
    static isWeekend(date: Date): boolean {
        // Use UTC day as we're treating timestamps as UTC
        const day = date.getUTCDay();
        return day === 0 || day === 6; // Sunday = 0, Saturday = 6
    }

    /**
     * Calculate performance based on indicator and data
     * Simplified: Absolute change = value(T) - value(T-1)
     * This logic applies consistently across all timeframes (1m, 5m, 15m, 30m, 1h, D, W, M)
     */
    static calculate(
        indicator: ViewIndicator, 
        sortedData: HistoricalDataPoint[], 
        targetIndex?: number,
        currentPrice?: number
    ): PerformanceResult | null {
        if (!sortedData || sortedData.length === 0) return null;

        const idx = targetIndex !== undefined ? targetIndex : (sortedData.length - 1);
        if (idx < 0 || idx >= sortedData.length) return null;

        const targetPoint = sortedData[idx];
        const targetOHLCV = PricePerformanceEngine.extractOHLCV(targetPoint);
        const pCurrent = currentPrice ?? targetOHLCV.c;
        const targetTs = PricePerformanceEngine.parseTime(targetOHLCV.t);
        const targetDate = new Date(targetTs);
        
        let pPrev = 0;
        
        // --- Intelligent Baseline Selection ---
        // If it's an intraday timeframe (1m to 1h), we usually want 
        // performance relative to the Previous DAY's Close.
        const isIntraday = ['1m', '5m', '15m', '30m', '1h'].includes(indicator);
        
        if (isIntraday) {
            // Scan backwards from targetIndex to find the last bar of the PREVIOUS trading day
            let found = false;
            for (let i = idx - 1; i >= 0; i--) {
                const prevTs = PricePerformanceEngine.parseTime(PricePerformanceEngine.extractOHLCV(sortedData[i]).t);
                const prevDate = new Date(prevTs);
                
                // If the bar has a DIFFERENT day, it's from a previous session.
                // We take the CLOSE of that session.
                // Since we use UTC for parsing, use getUTC methods
                if (prevDate.getUTCDate() !== targetDate.getUTCDate() || 
                    prevDate.getUTCMonth() !== targetDate.getUTCMonth() ||
                    prevDate.getUTCFullYear() !== targetDate.getUTCFullYear()) {
                    pPrev = PricePerformanceEngine.extractOHLCV(sortedData[i]).c;
                    found = true;
                    break;
                }
            }
            
            // If no previous session found in data (e.g. only 1 day loaded), 
            // fallback to the OPEN of the current day.
            if (!found) {
                // Find the first bar of the current day
                let firstBarIdx = idx;
                for (let i = idx - 1; i >= 0; i--) {
                    const bTs = PricePerformanceEngine.parseTime(PricePerformanceEngine.extractOHLCV(sortedData[i]).t);
                    const bDate = new Date(bTs);
                    if (bDate.getUTCDate() === targetDate.getUTCDate()) firstBarIdx = i;
                    else break;
                }
                pPrev = PricePerformanceEngine.extractOHLCV(sortedData[firstBarIdx]).o;
            }
        } else {
            // Standard timeframe (D, W, M): Baseline is the Previous Bar (T-1)
            if (idx > 0) {
                pPrev = PricePerformanceEngine.extractOHLCV(sortedData[idx - 1]).c;
            } else {
                pPrev = targetOHLCV.o;
            }
        }

        if (pPrev === 0) return null;

        // --- CALCULATION FORMULAS ---
        const deltaP = pCurrent - pPrev;
        const percentDeltaP = (deltaP / pPrev) * 100;

        return {
            baselinePrice: pPrev,
            currentPrice: pCurrent,
            deltaP,
            percentDeltaP,
            indicator,
            timestamp: targetTs
        };
    }
}

