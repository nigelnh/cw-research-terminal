import React, { useMemo, useState } from 'react';
import { colors } from '@/design/tokens';
import { EquityRow } from '@/tables/equity/types';

interface MarketShareData {
  label: string;
  tradingValue: string;
  cwVolume: number;
  cwCount: number;
  listedOs?: number;
  originalListedOs?: number;
  originalTradingVal?: number;
}

interface MarketShareTableProps {
  title: string;
  labelHeader: string;
  data: MarketShareData[];
  showListedOs?: boolean;
}

const MarketShareTable: React.FC<MarketShareTableProps> = ({ title, labelHeader, data, showListedOs }) => {
  const [sortConfig, setSortConfig] = useState<{
    key: keyof MarketShareData;
    direction: 'asc' | 'desc';
  } | null>(null); // Default sort is null, but we'll apply alphabetical in sortedData

  const handleSort = (key: keyof MarketShareData) => {
    setSortConfig(current => {
      if (!current || current.key !== key) {
        // First click: Always start with Ascending
        return { key, direction: 'asc' };
      }
      
      if (current.direction === 'asc') {
        // Second click: Toggle to Descending
        return { key, direction: 'desc' };
      }
      
      // Third click: Cycle back to Default (null)
      return null;
    });
  };

  const sortedData = useMemo(() => {
    // Apply default alphabetical sort if no explicit sortConfig
    const effectiveConfig = sortConfig || { key: 'label', direction: 'asc' };

    return [...data].sort((a, b) => {
      const valA = a[effectiveConfig.key as keyof MarketShareData];
      const valB = b[effectiveConfig.key as keyof MarketShareData];

      if (valA === valB) return 0;
      if (valA === undefined || valA === null) return 1;
      if (valB === undefined || valB === null) return -1;

      if (typeof valA === 'number' && typeof valB === 'number') {
        return effectiveConfig.direction === 'asc' ? valA - valB : valB - valA;
      }

      const strA = String(valA).toLowerCase();
      const strB = String(valB).toLowerCase();
      if (strA < strB) return effectiveConfig.direction === 'asc' ? -1 : 1;
      if (strA > strB) return effectiveConfig.direction === 'asc' ? 1 : -1;
      return 0;
    });
  }, [data, sortConfig]);

  const renderSortIcon = (key: keyof MarketShareData, position: 'left' | 'right' = 'left') => {
    // Only show icon if there's an explicit sort configuration for this key
    if (!sortConfig || sortConfig.key !== key) return null;
    
    return (
      <span 
        className="material-symbols-outlined" 
        style={{ 
          fontSize: '14px', 
          verticalAlign: 'middle', 
          marginLeft: position === 'right' ? '4px' : '0',
          marginRight: position === 'left' ? '4px' : '0',
          color: '#F3BA2F' // Always highlight since it's an explicit sort
        }}
      >
        {sortConfig.direction === 'asc' ? 'arrow_upward' : 'arrow_downward'}
      </span>
    );
  };

  return (
    <div style={{ 
      backgroundColor: 'rgba(255, 255, 255, 0.02)', 
      borderRadius: 8, 
      padding: '6px',
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      minHeight: 0
    }}>
      <div style={{ 
        color: colors.textSecondary, 
        fontSize: '14px', 
        fontWeight: 600, 
        marginBottom: '10px',
        paddingBottom: '4px'
      }}>
        {title}
      </div>
      <div style={{ flex: 1, overflowY: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '11px' }}>
          <thead>
            <tr>
              <th 
                onClick={() => handleSort('label')}
                style={{ 
                  textAlign: 'left', 
                  padding: '4px 4px', 
                  fontWeight: 600, 
                  cursor: 'pointer', 
                  userSelect: 'none',
                  position: 'sticky',
                  top: 0,
                  backgroundColor: '#1a1a1a', // Match darker background for sticky effect
                  zIndex: 10
                }}
              >
                {labelHeader}
                {renderSortIcon('label', 'right')}
              </th>
              <th 
                onClick={() => handleSort('originalTradingVal')}
                style={{ 
                  textAlign: 'right', 
                  padding: '4px 4px', 
                  fontWeight: 600, 
                  cursor: 'pointer', 
                  userSelect: 'none',
                  position: 'sticky',
                  top: 0,
                  backgroundColor: '#1a1a1a',
                  zIndex: 10
                }}
              >
                {renderSortIcon('originalTradingVal', 'left')}
                Trading Val
              </th>
              <th 
                onClick={() => handleSort('cwVolume')}
                style={{ 
                  textAlign: 'right', 
                  padding: '4px 4px', 
                  fontWeight: 600, 
                  cursor: 'pointer', 
                  userSelect: 'none',
                  position: 'sticky',
                  top: 0,
                  backgroundColor: '#1a1a1a',
                  zIndex: 10
                }}
              >
                {renderSortIcon('cwVolume', 'left')}
                CW Qty
              </th>
              {showListedOs && (
                <th 
                  onClick={() => handleSort('listedOs')}
                  style={{ 
                    textAlign: 'right', 
                    padding: '4px 4px', 
                    fontWeight: 600, 
                    cursor: 'pointer', 
                    userSelect: 'none',
                    position: 'sticky',
                    top: 0,
                    backgroundColor: '#1a1a1a',
                    zIndex: 10
                  }}
                >
                  {renderSortIcon('listedOs', 'left')}
                  Listed/OS
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {sortedData.map((item, idx) => (
              <tr key={idx} style={{ borderBottom: `1px solid ${colors.borderSubtle}`, color: colors.textSecondary }}>
                <td style={{ padding: '8px 4px', textAlign: 'left' }}>{item.label}</td>
                <td 
                  className="trading-val-cell"
                  style={{ 
                    padding: '8px 4px', 
                    textAlign: 'right',
                    position: 'relative'
                  }}
                >
                  <div className="percentage-value">{item.tradingValue}</div>
                  {item.originalTradingVal !== undefined && (
                    <div className="trading-val-tooltip">
                      {item.originalTradingVal.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                    </div>
                  )}
                </td>
                <td 
                  className="cw-quantity-cell"
                  style={{ 
                    padding: '8px 4px', 
                    textAlign: 'right', 
                    position: 'relative',
                  }}
                >
                  <div className="percentage-value">{item.cwVolume.toFixed(2)}%</div>
                  <div className="cw-count-tooltip">
                    {item.cwCount} CWs
                  </div>
                </td>
                {showListedOs && (
                  <td 
                    className="listed-os-cell"
                    style={{ 
                      padding: '8px 4px', 
                      textAlign: 'right', 
                      position: 'relative',
                    }}
                  >
                    <div className="percentage-value">
                      {item.listedOs !== undefined ? `${item.listedOs.toFixed(2)}%` : '-'}
                    </div>
                    {item.originalListedOs !== undefined && (
                      <div className="listed-os-tooltip">
                        {item.originalListedOs.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                      </div>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <style>{`
        .percentage-value {
          font-weight: 600;
          color: ${colors.textSecondary};
        }
        .cw-quantity-cell:hover .cw-count-tooltip,
        .listed-os-cell:hover .listed-os-tooltip,
        .trading-val-cell:hover .trading-val-tooltip {
          display: block;
        }
        .cw-count-tooltip,
        .listed-os-tooltip,
        .trading-val-tooltip {
          display: none;
          position: absolute;
          bottom: 0;
          right: 0;
          background-color: rgba(0, 0, 0, 0.9);
          color: ${colors.textPrimary};
          padding: 4px 8px;
          border-radius: 4px;
          border: 1px solid ${colors.border};
          font-size: 10px;
          white-space: nowrap;
          z-index: 1000;
          pointer-events: none;
          margin-bottom: 4px;
          box-shadow: 0 2px 4px rgba(0,0,0,0.5);
        }
      `}</style>
    </div>
  );
};

interface MarketShareContainerProps {
  data: EquityRow[];
  allRows: EquityRow[];
}

export const MarketShareContainer: React.FC<MarketShareContainerProps> = ({ data, allRows }) => {
  // Create a map of Symbol -> Outstanding_Vol for quick lookup
  const osMap = useMemo(() => {
    const map = new Map<string, number>();
    allRows.forEach(r => {
      const sym = String(r.Symbol || '').trim().toUpperCase();
      // VN market: Stocks are 3 chars, ETFs are 4. Indices are not underlyings.
      if (sym.length >= 3 && sym.length <= 4 && r.Outstanding_Vol) {
        map.set(sym, Number(r.Outstanding_Vol));
      }
    });
    return map;
  }, [allRows]);

  // MSI Calculation
  const msiData = useMemo(() => {
    const issuerCountMap = new Map<string, number>();
    const issuerTradingValMap = new Map<string, number>();
    let totalTradingVal = 0;
    const totalCount = data.length;

    data.forEach(row => {
      const issuer = String(row.Issuer || '').trim();
      if (issuer) {
        // For CW Quantity percentage
        issuerCountMap.set(issuer, (issuerCountMap.get(issuer) || 0) + 1);
        
        // For Trading Val percentage
        const val = Number(row.Trading_Val || 0);
        issuerTradingValMap.set(issuer, (issuerTradingValMap.get(issuer) || 0) + val);
        totalTradingVal += val;
      }
    });

    const result: MarketShareData[] = Array.from(issuerCountMap.entries())
      .map(([issuer, count]) => {
        const issuerTradingVal = issuerTradingValMap.get(issuer) || 0;
        const tradingValPercentage = totalTradingVal > 0 ? (issuerTradingVal / totalTradingVal) * 100 : 0;
        
        return {
          label: issuer,
          tradingValue: `${tradingValPercentage.toFixed(2)}%`,
          originalTradingVal: issuerTradingVal,
          cwVolume: totalCount > 0 ? (count / totalCount) * 100 : 0,
          cwCount: count
        };
      });

    return result;
  }, [data]);

  // MSUS Calculation
  const msusData = useMemo(() => {
    const underlyingCountMap = new Map<string, number>();
    const underlyingTradingValMap = new Map<string, number>();
    const underlyingVolRatioMap = new Map<string, number>();
    let totalTradingVal = 0;
    const totalCount = data.length;

    data.forEach(row => {
      const uSym = String(row.Under_Symbol || '').trim().toUpperCase();
      if (uSym) {
        // For CW Quantity percentage
        underlyingCountMap.set(uSym, (underlyingCountMap.get(uSym) || 0) + 1);
        
        // For Trading Val percentage
        const val = Number(row.Trading_Val || 0);
        underlyingTradingValMap.set(uSym, (underlyingTradingValMap.get(uSym) || 0) + val);
        totalTradingVal += val;
        
        // For Listed/OS calculation: sum(Listed_Vol / Ratio)
        const listedVol = Number(row.Listed_Vol || 0);
        const ratio = Number(row.Ratio || 1);
        const m = ratio !== 0 ? listedVol / ratio : 0;
        underlyingVolRatioMap.set(uSym, (underlyingVolRatioMap.get(uSym) || 0) + m);
      }
    });

    const result: MarketShareData[] = Array.from(underlyingCountMap.entries())
      .map(([underlying, count]) => {
        const totalVolRatio = underlyingVolRatioMap.get(underlying) || 0;
        const osVol = osMap.get(underlying);
        
        let listedOs: number | undefined;
        if (osVol && osVol > 0) {
          listedOs = (totalVolRatio / osVol) * 100;
        }

        const underlyingTradingVal = underlyingTradingValMap.get(underlying) || 0;
        const tradingValPercentage = totalTradingVal > 0 ? (underlyingTradingVal / totalTradingVal) * 100 : 0;

        return {
          label: underlying,
          tradingValue: `${tradingValPercentage.toFixed(2)}%`,
          originalTradingVal: underlyingTradingVal,
          cwVolume: totalCount > 0 ? (count / totalCount) * 100 : 0,
          cwCount: count,
          listedOs,
          originalListedOs: totalVolRatio
        };
      });

    return result;
  }, [data, osMap]);

  return (
    <div style={{ 
      display: 'flex', 
      flexDirection: 'column', 
      gap: '16px', 
      flex: 1, 
      height: '100%',
      minWidth: 0
    }}>
      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <div style={{ 
          color: colors.textSecondary, 
          fontSize: '12px', 
          marginBottom: '8px',
          fontWeight: 500
        }}>
          Total Listing: <span style={{ color: colors.textSecondary, fontWeight: 600 }}>{data.length}</span>
        </div>
        <div style={{ flex: 1, minHeight: 0 }}>
          <MarketShareTable 
            title="Market Share by Issuers" 
            labelHeader="Issuer" 
            data={msiData} 
          />
        </div>
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
        <MarketShareTable 
          title="Market Share by Underlying" 
          labelHeader="Symbol" 
          data={msusData} 
          showListedOs={true}
        />
      </div>
    </div>
  );
};
