import React, { useState, useMemo } from "react";
import { colors } from "@/design/tokens";

export interface FilterState {
    underlyings: string[]; // List of selected symbols or ["All"]
    issuers: string[];     // List of selected issuers or ["All"]
    tradingDate: string;   // Selected trading date (for Bubble Chart)
    fromDate: string;      // Start date (for Table range)
    toDate: string;        // End date (for Table range)
}

interface FilterCWProps {
    underlyings: string[];
    issuers: string[];
    tradingDates?: string[];
    filters: FilterState;
    onFilterChange: (filters: FilterState) => void;
    onClear: () => void;
    mode: "range" | "single"; // New prop to control date filter UI
}

export function FilterCW({
    underlyings,
    issuers,
    tradingDates: _tradingDates,
    filters,
    onFilterChange,
    onClear,
    mode,
}: FilterCWProps) {
    const [underlyingSearch, setUnderlyingSearch] = useState("");
    const [issuerSearch, setIssuerSearch] = useState("");

    const filteredUnderlyings = useMemo(() => {
        const sorted = [...underlyings].sort((a, b) => a.localeCompare(b));
        if (!underlyingSearch) return sorted;
        return sorted.filter(s => s.toLowerCase().includes(underlyingSearch.toLowerCase()));
    }, [underlyings, underlyingSearch]);

    const filteredIssuers = useMemo(() => {
        const sorted = [...issuers].sort((a, b) => a.localeCompare(b));
        if (!issuerSearch) return sorted;
        return sorted.filter(s => s.toLowerCase().includes(issuerSearch.toLowerCase()));
    }, [issuers, issuerSearch]);

    const handleToggleAll = (type: "underlying" | "issuer") => {
        if (type === "underlying") {
            const isAllSelected = filters.underlyings.includes("All");
            onFilterChange({
                ...filters,
                underlyings: isAllSelected ? [] : ["All", ...underlyings]
            });
        } else {
            const isAllSelected = filters.issuers.includes("All");
            onFilterChange({
                ...filters,
                issuers: isAllSelected ? [] : ["All", ...issuers]
            });
        }
    };

    const handleToggleItem = (type: "underlying" | "issuer", item: string) => {
        if (type === "underlying") {
            const isAllSelected = filters.underlyings.includes("All");
            let currentSet = isAllSelected ? [...underlyings] : [...filters.underlyings];
            
            let next: string[];
            if (currentSet.includes(item)) {
                next = currentSet.filter(i => i !== item);
            } else {
                next = [...currentSet, item];
            }

            // If everything is selected, add "All"
            if (next.length > 0 && underlyings.every(u => next.includes(u))) {
                next = ["All", ...underlyings];
            } else {
                next = next.filter(i => i !== "All");
            }
            
            onFilterChange({ ...filters, underlyings: next });
        } else {
            const isAllSelected = filters.issuers.includes("All");
            let currentSet = isAllSelected ? [...issuers] : [...filters.issuers];
            
            let next: string[];
            if (currentSet.includes(item)) {
                next = currentSet.filter(i => i !== item);
            } else {
                next = [...currentSet, item];
            }

            if (next.length > 0 && issuers.every(u => next.includes(u))) {
                next = ["All", ...issuers];
            } else {
                next = next.filter(i => i !== "All");
            }
            
            onFilterChange({ ...filters, issuers: next });
        }
    };

    const formatDateDisplay = (dateStr: string) => {
        if (!dateStr) return "DD/MM/YYYY";
        try {
            const date = new Date(dateStr);
            if (isNaN(date.getTime())) return dateStr;
            const d = date.getDate().toString().padStart(2, '0');
            const m = (date.getMonth() + 1).toString().padStart(2, '0');
            const y = date.getFullYear();
            return `${d}/${m}/${y}`;
        } catch (e) {
            return dateStr;
        }
    };

    const containerStyle: React.CSSProperties = {
        position: "absolute",
        top: "100%",
        right: 0,
        marginTop: 8,
        width: 400,
        backgroundColor: colors.panelBg,
        border: `1px solid ${colors.border}`,
        borderRadius: 8,
        padding: 16,
        zIndex: 1000,
        boxShadow: "0 10px 25px rgba(0,0,0,0.5)",
        display: "flex",
        flexDirection: "column",
        gap: 16,
        color: colors.textSecondary,
        fontSize: 12,
    };

    const sectionContainerStyle: React.CSSProperties = {
        display: "flex",
        gap: 16,
        height: 200,
    };

    const sectionStyle: React.CSSProperties = {
        flex: 1,
        display: "flex",
        flexDirection: "column",
        gap: 8,
        minWidth: 0,
    };

    const listContainerStyle: React.CSSProperties = {
        flex: 1,
        overflowY: "auto",
        paddingRight: 4,
        border: `1px solid ${colors.borderSubtle}`,
        borderRadius: 4,
        backgroundColor: "rgba(255,255,255,0.02)",
    };

    const inputStyle: React.CSSProperties = {
        backgroundColor: "rgba(255,255,255,0.05)",
        border: `1px solid ${colors.borderSubtle}`,
        borderRadius: 4,
        padding: "6px 8px",
        color: colors.textSecondary,
        fontSize: 11,
        outline: "none",
    };

    const radioRowStyle: React.CSSProperties = {
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "4px 8px",
        cursor: "pointer",
    };

    const footerStyle: React.CSSProperties = {
        display: "flex",
        alignItems: "flex-end",
        gap: 12,
        borderTop: `1px solid ${colors.borderSubtle}`,
        paddingTop: 12,
    };

    const dateSectionStyle: React.CSSProperties = {
        display: "flex",
        flexDirection: "column",
        gap: 4,
    };

    const buttonStyle: React.CSSProperties = {
        padding: "6px 12px",
        backgroundColor: "rgba(255,255,255,0.1)",
        border: "none",
        borderRadius: 4,
        color: colors.textSecondary,
        cursor: "pointer",
        fontSize: 11,
        transition: "background 0.2s",
    };

    return (
        <div style={containerStyle} onClick={(e) => e.stopPropagation()}>
            <div style={sectionContainerStyle}>
                {/* Underlying Section */}
                <div style={sectionStyle}>
                    <div style={{ fontWeight: 600 }}>Underlying</div>
                    <input
                        style={inputStyle}
                        placeholder="Search..."
                        value={underlyingSearch}
                        onChange={(e) => setUnderlyingSearch(e.target.value)}
                    />
                    <div style={listContainerStyle} className="custom-scrollbar">
                        <label
                            style={{
                                ...radioRowStyle,
                            }}
                        >
                            <input
                                type="checkbox"
                                checked={filters.underlyings.includes("All")}
                                onChange={() => handleToggleAll("underlying")}
                                style={{ accentColor: colors.textPrimary }}
                            />
                            <span style={{ color: filters.underlyings.includes("All") ? colors.textPrimary : colors.textSecondary }}>All</span>
                        </label>
                        {filteredUnderlyings.map(s => {
                            const isSelected = filters.underlyings.includes("All") || filters.underlyings.includes(s);
                            return (
                                <label
                                    key={s}
                                    style={{
                                        ...radioRowStyle,
                                    }}
                                >
                                    <input
                                        type="checkbox"
                                        checked={isSelected}
                                        onChange={() => handleToggleItem("underlying", s)}
                                        style={{ accentColor: colors.textPrimary }}
                                    />
                                    <span style={{ color: isSelected ? colors.textPrimary : colors.textSecondary }}>{s}</span>
                                </label>
                            );
                        })}
                    </div>
                </div>

                {/* Issuer Section */}
                <div style={sectionStyle}>
                    <div style={{ fontWeight: 600 }}>Issuer</div>
                    <input
                        style={inputStyle}
                        placeholder="Search..."
                        value={issuerSearch}
                        onChange={(e) => setIssuerSearch(e.target.value)}
                    />
                    <div style={listContainerStyle} className="custom-scrollbar">
                        <label
                            style={{
                                ...radioRowStyle,
                            }}
                        >
                            <input
                                type="checkbox"
                                checked={filters.issuers.includes("All")}
                                onChange={() => handleToggleAll("issuer")}
                                style={{ accentColor: colors.textPrimary }}
                            />
                            <span style={{ color: filters.issuers.includes("All") ? colors.textPrimary : colors.textSecondary }}>All</span>
                        </label>
                        {filteredIssuers.map(s => {
                            const isSelected = filters.issuers.includes("All") || filters.issuers.includes(s);
                            return (
                                <label
                                    key={s}
                                    style={{
                                        ...radioRowStyle,
                                    }}
                                >
                                    <input
                                        type="checkbox"
                                        checked={isSelected}
                                        onChange={() => handleToggleItem("issuer", s)}
                                        style={{ accentColor: colors.textPrimary }}
                                    />
                                    <span style={{ color: isSelected ? colors.textPrimary : colors.textSecondary }}>{s}</span>
                                </label>
                            );
                        })}
                    </div>
                </div>
            </div>

            <div style={{ ...footerStyle, gap: 12 }}>
                {mode === "single" ? (
                    <div style={{ ...dateSectionStyle, flex: 2 }}>
                        <span style={{ fontSize: 10, color: colors.textMuted }}>Select Date</span>
                        <div style={{ position: "relative" }}>
                            <input
                                type="date"
                                style={{ ...inputStyle, width: "100%", height: 28, opacity: 0, position: "absolute", zIndex: 2, cursor: "pointer" }}
                                value={filters.tradingDate}
                                onChange={(e) => onFilterChange({ ...filters, tradingDate: e.target.value })}
                                onClick={(e) => (e.target as any).showPicker?.()}
                            />
                            <div style={{ ...inputStyle, width: "100%", height: 28, display: "flex", alignItems: "center", pointerEvents: "none" }}>
                                {filters.tradingDate ? formatDateDisplay(filters.tradingDate) : "Latest"}
                            </div>
                        </div>
                    </div>
                ) : (
                    <>
                        <div style={{ ...dateSectionStyle, flex: 1.5 }}>
                            <span style={{ fontSize: 10, color: colors.textMuted }}>From Date</span>
                            <div style={{ position: "relative" }}>
                                <input
                                    type="date"
                                    style={{ ...inputStyle, width: "100%", height: 28, opacity: 0, position: "absolute", zIndex: 2, cursor: "pointer" }}
                                    value={filters.fromDate}
                                    onChange={(e) => onFilterChange({ ...filters, fromDate: e.target.value })}
                                    onClick={(e) => (e.target as any).showPicker?.()}
                                />
                                <div style={{ ...inputStyle, width: "100%", height: 28, display: "flex", alignItems: "center", pointerEvents: "none" }}>
                                    {formatDateDisplay(filters.fromDate)}
                                </div>
                            </div>
                        </div>
                        <div style={{ ...dateSectionStyle, flex: 1.5 }}>
                            <span style={{ fontSize: 10, color: colors.textMuted }}>To Date</span>
                            <div style={{ position: "relative" }}>
                                <input
                                    type="date"
                                    style={{ ...inputStyle, width: "100%", height: 28, opacity: 0, position: "absolute", zIndex: 2, cursor: "pointer" }}
                                    value={filters.toDate}
                                    onChange={(e) => onFilterChange({ ...filters, toDate: e.target.value })}
                                    onClick={(e) => (e.target as any).showPicker?.()}
                                />
                                <div style={{ ...inputStyle, width: "100%", height: 28, display: "flex", alignItems: "center", pointerEvents: "none", backgroundColor: colors.panelBg }}>
                                    {formatDateDisplay(filters.toDate)}
                                </div>
                            </div>
                        </div>
                    </>
                )}
                <div style={{ ...dateSectionStyle, flex: 1 }}>
                    <span style={{ fontSize: 10, opacity: 0 }}>Clear</span>
                    <button
                        style={{ ...buttonStyle, height: 28, width: "100%", padding: 0 }}
                        onClick={onClear}
                        onMouseOver={(e) => (e.currentTarget.style.backgroundColor = "rgba(255,255,255,0.2)")}
                        onMouseOut={(e) => (e.currentTarget.style.backgroundColor = "rgba(255,255,255,0.1)")}
                    >
                        Clear
                    </button>
                </div>
            </div>

            <style>
                {`
          .custom-scrollbar::-webkit-scrollbar {
            width: 4px;
          }
          .custom-scrollbar::-webkit-scrollbar-track {
            background: transparent;
          }
          .custom-scrollbar::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 2px;
          }
          .custom-scrollbar::-webkit-scrollbar-thumb:hover {
            background: rgba(255, 255, 255, 0.2);
          }
        `}
            </style>
        </div>
    );
}
