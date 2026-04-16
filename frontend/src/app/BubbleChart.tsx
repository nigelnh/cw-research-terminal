import React, { useMemo } from "react";
import {
  Chart as ChartJS,
  LinearScale,
  PointElement,
  Tooltip,
  Legend,
  ChartOptions,
} from "chart.js";
import { Bubble } from "react-chartjs-2";
import { EquityRow } from "@/tables/equity/types";
import { colors } from "@/design/tokens";

ChartJS.register(LinearScale, PointElement, Tooltip, Legend);

interface BubbleChartProps {
  data: EquityRow[];
}

// Predefined colors for different issuers
const ISSUER_COLORS = [
  "rgba(243, 186, 47, 0.7)", // Gold
  "rgba(54, 162, 235, 0.7)",  // Blue
  "rgba(255, 99, 132, 0.7)",  // Pink/Red
  "rgba(75, 192, 192, 0.7)",  // Teal
  "rgba(153, 102, 255, 0.7)", // Purple
  "rgba(255, 159, 64, 0.7)",  // Orange
  "rgba(201, 203, 207, 0.7)", // Grey
  "rgba(0, 204, 102, 0.7)",   // Green
  "rgba(204, 0, 204, 0.7)",   // Magenta
  "rgba(0, 102, 204, 0.7)",   // Dark Blue
  "rgba(166, 206, 22, 0.7)",  // Lime
  "rgba(255, 127, 80, 0.7)",  // Coral
  "rgba(0, 191, 255, 0.7)",   // Sky Blue
  "rgba(184, 115, 51, 0.7)",  // Brown
];

export const BubbleChart = React.memo(({ data }: BubbleChartProps) => {
  // Extract issuer information for the legend and chart
  const { issuerColorMap, issuerList } = useMemo(() => {
    const list = Array.from(new Set(data.map(r => r.Issuer).filter(Boolean))).sort();
    const colorMap: Record<string, string> = {};
    list.forEach((issuer, index) => {
      colorMap[issuer!] = ISSUER_COLORS[index % ISSUER_COLORS.length];
    });
    return { issuerColorMap: colorMap, issuerList: list };
  }, [data]);

  const chartData = useMemo(() => {
    const today = new Date();
    
    const points = data.map((row) => {
      // 1. Calculate T in days and format maturity date
      let tDays = 0;
      let formattedDate = "";
      const dateToUse = row.MaturityDate;
      if (dateToUse) {
        const maturityDate = new Date(dateToUse);
        const diffTime = maturityDate.getTime() - today.getTime();
        tDays = Math.max(0, Math.ceil(diffTime / (1000 * 60 * 60 * 24)));
        
        const d = maturityDate.getDate().toString().padStart(2, '0');
        const m = (maturityDate.getMonth() + 1).toString().padStart(2, '0');
        const y = maturityDate.getFullYear();
        formattedDate = `${d}/${m}/${y}`;
      }

      // 2. Calculate m = listed_volume / ratio
      const listedVol = Number(row.Listed_Vol || 0);
      const ratio = Number(row.Ratio || 1);
      const m = ratio !== 0 ? listedVol / ratio : 0;

      return {
        x: tDays,
        y: m,
        m: m, // Keep raw value for scaling
        symbol: row.Symbol,
        issuer: row.Issuer || "Unknown",
        maturityDate: formattedDate,
        listedVol: listedVol,
        ratio: ratio,
        backgroundColor: issuerColorMap[row.Issuer || ""] || "rgba(255, 255, 255, 0.5)",
      };
    });

    // 3. Dynamic scaling for bubble radius
    const mValues = points.map(p => p.m).filter(m => m > 0);
    const maxM = mValues.length > 0 ? Math.max(...mValues) : 1;
    const minM = mValues.length > 0 ? Math.min(...mValues) : 0;
    
    return {
      datasets: [
        {
          label: "Covered Warrants",
          data: points.map(p => ({
            x: p.x,
            y: p.y,
            // Map m linearly to a radius between 4px and 40px
            r: maxM === minM 
              ? (p.m > 0 ? 10 : 0)
              : p.m > 0 
                ? 4 + ((p.m - minM) / (maxM - minM)) * 36 
                : 0,
            symbol: p.symbol,
            issuer: p.issuer,
            maturityDate: p.maturityDate,
            listedVol: p.listedVol,
            ratio: p.ratio,
          })),
          backgroundColor: points.map(p => p.backgroundColor),
          borderColor: points.map(p => p.backgroundColor.replace("0.7", "1")),
          borderWidth: 1,
        },
      ],
    };
  }, [data, issuerColorMap]);

  const options: ChartOptions<"bubble"> = useMemo(() => ({
    responsive: true,
    maintainAspectRatio: false,
    scales: {
      x: {
        title: {
          display: true,
          text: "Times to Maturity",
          color: colors.textSecondary,
        },
        grid: {
          color: "rgba(255, 255, 255, 0.1)",
        },
        ticks: {
          color: colors.textSecondary,
          callback: function(value) {
            const today = new Date();
            const tickDate = new Date(today);
            tickDate.setDate(today.getDate() + Number(value));
            
            const d = tickDate.getDate().toString().padStart(2, '0');
            const m = (tickDate.getMonth() + 1).toString().padStart(2, '0');
            const y = tickDate.getFullYear();
            return `${d}/${m}/${y}`;
          }
        },
      },
      y: {
        title: {
          display: true,
          text: "Listed Vol / Ratio",
          color: colors.textSecondary,
        },
        grid: {
          color: "rgba(255, 255, 255, 0.1)",
        },
        ticks: {
          color: colors.textSecondary,
        },
      },
    },
    plugins: {
      legend: {
        display: false,
      },
      tooltip: {
        callbacks: {
          label: (context: any) => {
            const point = context.raw;
            return [
              `${point.symbol} (${point.issuer})`,
              `Vol: ${point.listedVol.toLocaleString()}`,
              `Ratio: ${point.ratio.toLocaleString()}`,
              `Maturity: ${point.maturityDate}`,
              `Vol/Ratio: ${point.y.toLocaleString()}`
            ];
          },
        },
      },
    },
  }), []);

  return (
    <div style={{ width: "100%", height: "100%", minHeight: 400, position: "relative" }}>
      <Bubble options={options} data={chartData} />
      
      {/* Custom Issuer Legend */}
      <div 
        style={{ 
          position: "absolute", 
          top: 10, 
          right: 10, 
          backgroundColor: "rgba(0, 0, 0, 0.6)", 
          padding: "10px", 
          borderRadius: "6px",
          border: `1px solid ${colors.border}`,
          zIndex: 10,
          display: "flex",
          flexDirection: "column",
          gap: "6px",
          maxWidth: "300px"
        }}
      >
        <div style={{ fontSize: "11px", fontWeight: 600, color: colors.textPrimary, marginBottom: "2px", borderBottom: `1px solid ${colors.borderSubtle}`, paddingBottom: "4px" }}>
          Issuers
        </div>
        <div style={{ 
          display: "grid", 
          gridTemplateColumns: "1fr 1fr", 
          gap: "8px 16px"
        }}>
          {issuerList.map(issuer => (
            <div key={issuer} style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <div style={{ 
                width: "10px", 
                height: "10px", 
                borderRadius: "50%", 
                backgroundColor: issuerColorMap[issuer!],
                border: `1px solid ${issuerColorMap[issuer!].replace("0.7", "1")}`,
                flexShrink: 0
              }} />
              <span style={{ fontSize: "10px", color: colors.textSecondary, whiteSpace: "nowrap" }}>
                {issuer}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
});
