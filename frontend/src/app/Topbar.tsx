/**
 * Topbar component with clock and branding
 */

import { useEffect, useState } from "react";
import { colors } from "@/design/tokens";

function formatDate(d: Date): string {
  const months = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];
  const day = String(d.getDate()).padStart(2, "0");
  const month = months[d.getMonth()];
  const year = d.getFullYear();
  return `${day} ${month} ${year}`;
}

function formatTime(d: Date): string {
  const h = String(d.getHours()).padStart(2, "0");
  const m = String(d.getMinutes()).padStart(2, "0");
  const s = String(d.getSeconds()).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

interface TopbarProps {
  currentView: "table" | "chart" | "ta";
  onViewChange: (view: "table" | "chart" | "ta") => void;
  serverTimeOffset?: number;
}

export function Topbar({ currentView, onViewChange, serverTimeOffset = 0 }: TopbarProps) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const interval = setInterval(() => {
      setNow(Date.now());
    }, 500);
    return () => clearInterval(interval);
  }, []);

  const adjustedNow = new Date(now + serverTimeOffset);

  const navButtonStyle = (isActive: boolean) => ({
    padding: "6px 16px",
    borderRadius: "6px",
    fontSize: "14px",
    fontWeight: 500,
    cursor: "pointer",
    transition: "all 0.2s",
    backgroundColor: isActive ? "rgba(243, 186, 47, 0.15)" : "transparent",
    color: isActive ? "#F3BA2F" : colors.textSecondary,
    border: `1px solid ${isActive ? "#F3BA2F" : "transparent"}`,
  });

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        height: 48,
        padding: "0 24px",
        backgroundColor: colors.background,
        borderBottom: `1px solid ${colors.border}`,
      }}
    >
      {/* Left - Spacer */}
      <div style={{ flex: 1 }} />

      {/* Center - Navigation */}
      <div
        style={{
          flex: 1,
          display: "flex",
          justifyContent: "center",
          gap: 8,
        }}
      >
        <div 
          style={navButtonStyle(currentView === "table")}
          onClick={() => onViewChange("table")}
        >
          Covered Warrants
        </div>
        <div 
          style={navButtonStyle(currentView === "chart")}
          onClick={() => onViewChange("chart")}
        >
          Chart
        </div>
        <div 
          style={navButtonStyle(currentView === "ta")}
          onClick={() => onViewChange("ta")}
        >
          TA
        </div>
      </div>

      {/* Right - Date, Time, Notifications */}
      <div
        style={{
          flex: 1,
          display: "flex",
          alignItems: "center",
          justifyContent: "flex-end",
          gap: 16,
        }}
      >
        <span style={{ color: colors.textSecondary, fontSize: 14 }}>
          {formatDate(adjustedNow)}
        </span>
        <span
          style={{
            color: colors.textSecondary,
            fontSize: 14,
            fontWeight: 500,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {formatTime(adjustedNow)}
        </span>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            width: 32,
            height: 32,
            borderRadius: 8,
            backgroundColor: "rgba(255, 255, 255, 0.05)",
            cursor: "pointer",
          }}
          title="Notifications"
        >
          <span
            className="material-symbols-outlined"
            style={{ fontSize: 19, color: colors.textSecondary }}
          >
            notifications
          </span>
        </div>
      </div>
    </div>
  );
}

