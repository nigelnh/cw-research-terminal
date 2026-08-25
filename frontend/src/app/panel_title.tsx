import { colors } from "@/design/tokens";
import React, { useRef, useState, useEffect } from "react";

interface PanelTitleProps {
  title: string;
  icon?: string;
  onDateChange?: (date: string) => void;
  filterContent?: React.ReactNode;
  displayOptionContent?: React.ReactNode;
  onExportCsv?: () => void;
}

export function PanelTitle({ title, icon, onDateChange, filterContent, displayOptionContent, onExportCsv }: PanelTitleProps) {
  const dateInputRef = useRef<HTMLInputElement>(null);
  const [showFilter, setShowFilter] = useState(false);
  const [showDisplayOption, setShowDisplayOption] = useState(false);
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const displayOptionCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Cleanup timers on unmount
  useEffect(() => {
    return () => {
      if (closeTimerRef.current) clearTimeout(closeTimerRef.current);
      if (displayOptionCloseTimerRef.current) clearTimeout(displayOptionCloseTimerRef.current);
    };
  }, []);

  const handleMouseEnter = () => {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    setShowFilter(true);
  };

  const handleMouseLeave = () => {
    closeTimerRef.current = setTimeout(() => {
      setShowFilter(false);
    }, 300); // 300ms persistence delay
  };

  const handleDisplayOptionMouseEnter = () => {
    if (displayOptionCloseTimerRef.current) {
      clearTimeout(displayOptionCloseTimerRef.current);
      displayOptionCloseTimerRef.current = null;
    }
    setShowDisplayOption(true);
  };

  const handleDisplayOptionMouseLeave = () => {
    displayOptionCloseTimerRef.current = setTimeout(() => {
      setShowDisplayOption(false);
    }, 300);
  };

  const handleIconClick = () => {
    if (dateInputRef.current) {
      if ('showPicker' in HTMLInputElement.prototype) {
        try {
          dateInputRef.current.showPicker();
        } catch (e) {
          dateInputRef.current.click();
        }
      } else {
        dateInputRef.current.click();
      }
    }
  };

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        marginBottom: 8,
        position: "relative",
      }}
    >
      <span
        style={{
          fontSize: 13,
          fontWeight: 500,
          color: colors.textSecondary,
        }}
      >
        {title}
      </span>
      <span
        style={{
          color: colors.textSecondary,
          fontSize: 14,
        }}
      >
        ›
      </span>

      <div style={{ flex: 1 }} />

      {/* Export CSV Button */}
      {onExportCsv && (
        <span
          className="material-symbols-outlined"
          title="Export CSV"
          onClick={onExportCsv}
          style={{
            fontSize: 18,
            color: colors.textSecondary,
            opacity: 0.8,
            cursor: "pointer",
            marginRight: 4,
            transition: "color 0.2s, opacity 0.2s",
            userSelect: "none",
          }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = colors.textPrimary; (e.currentTarget as HTMLElement).style.opacity = "1"; }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = colors.textSecondary; (e.currentTarget as HTMLElement).style.opacity = "0.8"; }}
        >
          file_download
        </span>
      )}

      {/* Display Option Button */}
      {displayOptionContent && (
        <div
          style={{ position: 'relative' }}
          onMouseEnter={handleDisplayOptionMouseEnter}
          onMouseLeave={handleDisplayOptionMouseLeave}
        >
          <span
            className="material-symbols-outlined"
            style={{
              fontSize: 18,
              color: showDisplayOption ? colors.textPrimary : colors.textSecondary,
              opacity: 0.8,
              cursor: "pointer",
              marginRight: 4, // Tighter gap for "next to filter_alt"
              transition: "color 0.2s",
            }}
          >
            more_vert
          </span>
          {showDisplayOption && displayOptionContent}
        </div>
      )}

      {/* Filter Button */}
      {filterContent && (
        <div
          style={{ position: 'relative' }}
          onMouseEnter={handleMouseEnter}
          onMouseLeave={handleMouseLeave}
        >
          <span
            className="material-symbols-outlined"
            style={{
              fontSize: 18,
              color: showFilter ? colors.textPrimary : colors.textSecondary,
              opacity: 0.8,
              cursor: "pointer",
              marginRight: 8,
              transition: "color 0.2s",
            }}
          >
            filter_alt
          </span>
          {showFilter && filterContent}
        </div>
      )}

      {icon && (
        <div style={{ display: 'flex', alignItems: 'center', position: 'relative' }}>
          <span
            className="material-symbols-outlined"
            onClick={onDateChange ? handleIconClick : undefined}
            style={{
              fontSize: 16,
              color: colors.textSecondary,
              opacity: 0.8,
              cursor: onDateChange ? "pointer" : "default",
            }}
          >
            {icon}
          </span>
          {onDateChange && (
            <input
              ref={dateInputRef}
              type="date"
              onChange={(e) => onDateChange(e.target.value)}
              style={{
                position: 'absolute',
                opacity: 0,
                width: 0,
                height: 0,
                pointerEvents: 'none',
              }}
            />
          )}
        </div>
      )}
    </div>
  );
}

