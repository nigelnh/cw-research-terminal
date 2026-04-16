import { memo } from 'react';
import { colors } from '@/design/tokens';

interface TradingViewWidgetProps {
  symbol?: string;
}

/**
 * TradingViewWidget - A robust iframe-based implementation of the TradingView Advanced Chart.
 * 
 * We use an iframe instead of the script-based "External Embedding" to avoid:
 * 1. Uncaught TypeError: Cannot read properties of null (reading 'querySelector')
 *    (Caused by document.currentScript being null in Cross-Origin Isolated environments)
 * 2. net::ERR_BLOCKED_BY_RESPONSE.NotSameOriginAfterDefaultedToSameOriginByCoep
 *    (Caused by the script's injected iframe not having proper CORP/COEP headers)
 */
function TradingViewWidget({ symbol = "NASDAQ:AAPL" }: TradingViewWidgetProps) {
  // TradingView symbols usually require a prefix (e.g., NASDAQ:AAPL).
  // If no prefix is provided, we default to NASDAQ for US markets.
  const hasPrefix = symbol.includes(':');
  const tvSymbol = hasPrefix ? symbol : `NASDAQ:${symbol}`;
  const encodedSymbol = encodeURIComponent(tvSymbol);
  
  // Direct iframe URL for the Advanced Chart widget
  const iframeUrl = `https://s.tradingview.com/embed-widget/advanced-chart/?symbol=${encodedSymbol}&interval=D&hidesidetoolbar=1&hidetoptoolbar=0&symboledit=1&saveimage=1&toolbarbg=%230F0F0F&studies=%5B%5D&theme=dark&style=1&timezone=Etc%2FUTC&studies_overrides=%7B%7D&overrides=%7B%7D&enabled_features=%5B%5D&disabled_features=%5B%5D&locale=en`;

  return (
    <div className="tradingview-widget-container" style={{ 
      height: "100%", 
      width: "100%", 
      backgroundColor: "#0F0F0F",
      display: 'flex',
      flexDirection: 'column'
    }}>
      <iframe
        src={iframeUrl}
        style={{ flex: 1, width: '100%', border: 'none' }}
        title={`TradingView Chart ${symbol}`}
        allowFullScreen
      />
      <div className="tradingview-widget-copyright" style={{ 
        padding: '2px 8px', 
        fontSize: '10px', 
        backgroundColor: '#0F0F0F',
        borderTop: `1px solid ${colors.borderSubtle}`,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center'
      }}>
        <span style={{ color: colors.textMuted }}>{tvSymbol}</span>
        <span style={{ color: colors.textMuted, fontSize: '9px' }}>by TradingView</span>
      </div>
    </div>
  );
}

export default memo(TradingViewWidget);
