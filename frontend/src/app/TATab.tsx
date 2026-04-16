import { TradingView } from './TradingView';
import TradingViewWidget from './TradingViewWidget';

export function TATab() {
    const originalSymbols = ['VNINDEX', 'VN30', 'HPG', 'SSI', 'VIC', 'VNM'];
    
    const CHART_ROW_HEIGHT = 420;
    const GRID_ROWS = 3;
    const GAP = 12;
    const gridMinHeight = GRID_ROWS * CHART_ROW_HEIGHT + (GRID_ROWS - 1) * GAP;

    return (
        <div style={{ 
            flex: 1,
            overflowY: 'auto',
            overflowX: 'hidden',
            padding: '6px 0',
        }}>
        <div style={{ 
            display: 'grid', 
            gridTemplateColumns: 'repeat(3, 1fr)', 
            gridTemplateRows: `repeat(${GRID_ROWS}, ${CHART_ROW_HEIGHT}px)`,
            gap: GAP,
            minHeight: gridMinHeight,
            width: '100%',
        }}>
            {/* Top row: 3 TradingView Widgets (Advanced External Charts) */}
            {['AAPL', 'GOOG', 'NVDA'].map((symbol, index) => (
                <div 
                    key={`tv-${index}`} 
                    style={{ 
                        height: '100%', 
                        width: '100%',
                        backgroundColor: 'rgba(255, 255, 255, 0.02)',
                        borderRadius: 8,
                        overflow: 'hidden',
                        border: '1px solid rgba(255, 255, 255, 0.1)'
                    }}
                >
                    <TradingViewWidget 
                        symbol={symbol}
                    />
                </div>
            ))}
            
            {/* Bottom row: 3 TradingView Widgets (Original Charts) */}
            {originalSymbols.map((symbol, index) => (
                <TradingView 
                    key={`original-${index}`} 
                    initialSymbol={symbol}
                />
            ))}
        </div>
        </div>
    );
}
