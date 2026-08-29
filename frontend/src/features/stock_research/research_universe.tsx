import React, { useState, useMemo } from "react";
import { Search, Plus, Check } from "lucide-react";
import type { CoveredWarrant } from "@/domain/models";
import { useWatchlist } from "@/data/watchlist";
import { useActiveWarrants } from "@/data/query";
import { useQuote, useCoveredWarrant } from "@/data/use_research_market";
import { deriveSelectedInstrument } from "@/data/selected_instrument";
import { useInstrumentSpecs } from "@/data/instruments/use_instrument_specs";
import { InstrumentDrawer } from "@/features/warrant_info/instrument_drawer";

interface ResearchUniverseProps {
  onNavigateToDashboard?: () => void;
  selectedSymbol?: string | null;
  onSelectSymbol?: (symbol: string | null) => void;
}

const H = ({ children, right }: { children: React.ReactNode; right?: boolean }) => (
  <th
    className="col-head"
    style={{
      whiteSpace: "nowrap",
      borderBottom: "1px solid var(--border-strong)",
      backgroundColor: "var(--background)",
      padding: "8px 12px",
      fontWeight: 500,
      textAlign: right ? "right" : "left",
    }}
  >
    {children}
  </th>
);

const selectStyle: React.CSSProperties = {
  cursor: "pointer",
  backgroundColor: "transparent",
  border: "none",
  fontSize: "12px",
  color: "var(--foreground)",
  outline: "none",
  padding: "2px 4px",
};

export function ResearchUniverse({
  onNavigateToDashboard,
  selectedSymbol = null,
  onSelectSymbol,
}: ResearchUniverseProps) {
  // Local, transient UI state - search/filter are not shareable navigation state.
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedIssuer, setSelectedIssuer] = useState<string>("all");
  const [selectedUnderlying, setSelectedUnderlying] = useState<string>("all");

  const setSelectedSymbol = onSelectSymbol ?? (() => {});
  const { isInWatchlist, addToWatchlist, removeFromWatchlist, canAdd } = useWatchlist();

  // Static universe metadata: server state owned by TanStack Query (cached, deduped).
  const { instruments, isLoading: loading, isError } = useActiveWarrants();
  const { getSpec } = useInstrumentSpecs();

  // Drawer instrument DERIVED from the universe record + realtime store (not stored).
  const selectedQuote = useQuote(selectedSymbol);
  const selectedCw = useCoveredWarrant(selectedSymbol);
  const selectedUniverseCw = useMemo(
    () => instruments.find((cw) => cw.symbol.toUpperCase() === (selectedSymbol ?? "").toUpperCase()) ?? null,
    [instruments, selectedSymbol]
  );
  const selectedInstrument = useMemo(
    () =>
      deriveSelectedInstrument(selectedSymbol, {
        instrumentSpec: getSpec(selectedSymbol),
        universeCw: selectedUniverseCw,
        quote: selectedQuote,
        cw: selectedCw,
      }),
    [selectedSymbol, selectedUniverseCw, selectedQuote, selectedCw, getSpec]
  );

  const underlyings = useMemo(() => {
    const set = new Set<string>();
    instruments.forEach((cw) => {
      if (cw.underlyingSymbol) set.add(cw.underlyingSymbol.toUpperCase());
    });
    return ["all", ...Array.from(set).sort()];
  }, [instruments]);

  const issuers = useMemo(() => {
    const set = new Set<string>();
    instruments.forEach((cw) => {
      if (cw.issuer) set.add(cw.issuer.toUpperCase());
    });
    return ["all", ...Array.from(set).sort()];
  }, [instruments]);

  const filteredInstruments = useMemo(() => {
    const term = searchTerm.trim().toUpperCase();
    return instruments.filter((cw) => {
      const matchSearch =
        !term ||
        cw.symbol.toUpperCase().includes(term) ||
        (cw.underlyingSymbol && cw.underlyingSymbol.toUpperCase().includes(term)) ||
        (cw.issuer && cw.issuer.toUpperCase().includes(term));

      const matchIssuer = selectedIssuer === "all" || cw.issuer?.toUpperCase() === selectedIssuer;
      const matchUnderlying = selectedUnderlying === "all" || cw.underlyingSymbol?.toUpperCase() === selectedUnderlying;

      return matchSearch && matchIssuer && matchUnderlying;
    });
  }, [instruments, searchTerm, selectedIssuer, selectedUnderlying]);

  const formatPrice = (val?: number | null) => {
    if (val === null || val === undefined || isNaN(val)) return "—";
    return val.toLocaleString("en-US");
  };

  const calculateDTE = (lastTradingDate?: string | null, maturityDate?: string | null) => {
    const target = lastTradingDate || maturityDate;
    if (!target) return "—";
    const targetTime = new Date(target).getTime();
    if (isNaN(targetTime)) return "—";
    const diff = Math.ceil((targetTime - Date.now()) / (1000 * 60 * 60 * 24));
    return diff >= 0 ? `${diff}d` : "Expired";
  };

  const handleToggle = (e: React.MouseEvent, cw: CoveredWarrant) => {
    e.stopPropagation();
    if (isInWatchlist(cw.symbol)) {
      removeFromWatchlist(cw.symbol);
      return;
    }

    const check = canAdd({
      symbol: cw.symbol,
      instrumentType: "CW",
      underlyingSymbol: cw.underlyingSymbol,
    });

    if (!check.allowed && check.reason) {
      alert(check.reason);
      return;
    }

    addToWatchlist({
      symbol: cw.symbol,
      instrumentType: "CW",
      underlyingSymbol: cw.underlyingSymbol,
      issuer: cw.issuer,
      strikePrice: cw.strikePrice,
      exerciseRatio: cw.exerciseRatio,
      maturityDate: cw.maturityDate,
      lastTradingDate: cw.lastTradingDate,
    });
  };

  const isFiltered = searchTerm !== "" || selectedIssuer !== "all" || selectedUnderlying !== "all";

  return (
    <div>
      <h1 style={{ fontSize: "15px", fontWeight: 500, letterSpacing: "-0.01em", color: "var(--foreground)", margin: 0 }}>
        Research
      </h1>

      {/* Search Line */}
      <div
        style={{
          marginTop: "16px",
          display: "flex",
          alignItems: "center",
          gap: "8px",
          borderBottom: "1px solid var(--border)",
          paddingBottom: "12px",
        }}
      >
        <Search size={15} strokeWidth={1.5} className="text-subtle" />
        <input
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          placeholder="Search symbol, underlying, or issuer…"
          className="focus-ring"
          style={{
            width: "100%",
            backgroundColor: "transparent",
            fontSize: "14px",
            color: "var(--foreground)",
            border: "none",
            outline: "none",
          }}
        />
      </div>

      {/* Filters Bar */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: "20px",
          padding: "12px 0",
          fontSize: "12px",
          color: "var(--muted-foreground)",
        }}
      >
        <label style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          Underlying:
          <select
            value={selectedUnderlying}
            onChange={(e) => setSelectedUnderlying(e.target.value)}
            className="focus-ring"
            style={selectStyle}
          >
            {underlyings.map((u) => (
              <option key={u} value={u} style={{ backgroundColor: "var(--surface)", color: "var(--foreground)" }}>
                {u === "all" ? "All" : u}
              </option>
            ))}
          </select>
        </label>

        <label style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          Issuer:
          <select
            value={selectedIssuer}
            onChange={(e) => setSelectedIssuer(e.target.value)}
            className="focus-ring"
            style={selectStyle}
          >
            {issuers.map((i) => (
              <option key={i} value={i} style={{ backgroundColor: "var(--surface)", color: "var(--foreground)" }}>
                {i === "all" ? "All" : i}
              </option>
            ))}
          </select>
        </label>

        {isFiltered && (
          <button
            onClick={() => {
              setSearchTerm("");
              setSelectedUnderlying("all");
              setSelectedIssuer("all");
            }}
            className="focus-ring"
            style={{
              background: "transparent",
              border: "none",
              cursor: "pointer",
              fontSize: "12px",
              color: "var(--subtle-foreground)",
            }}
          >
            Clear
          </button>
        )}

        <span className="tnum" style={{ marginLeft: "auto", color: "var(--subtle-foreground)" }}>
          {filteredInstruments.length} results
        </span>
      </div>

      {/* Research Table */}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", minWidth: "860px", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <H>Symbol</H>
              <H>Issuer</H>
              <H>Underlying</H>
              <H right>Strike</H>
              <H right>Ratio</H>
              <H right>Maturity</H>
              <H right>DTE</H>
              <H right>Status</H>
              <th style={{ width: "32px", borderBottom: "1px solid var(--border-strong)", backgroundColor: "var(--background)" }} />
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={9} style={{ padding: "64px 0", textAlign: "center", fontSize: "12px", color: "var(--subtle-foreground)" }}>
                  Loading research universe...
                </td>
              </tr>
            ) : isError ? (
              <tr>
                <td colSpan={9} style={{ padding: "64px 0", textAlign: "center", fontSize: "12px", color: "var(--destructive)" }}>
                  Could not load the research universe. Retry shortly.
                </td>
              </tr>
            ) : filteredInstruments.length === 0 ? (
              <tr>
                <td colSpan={9} style={{ padding: "64px 0", textAlign: "center", fontSize: "12px", color: "var(--subtle-foreground)" }}>
                  No instruments match.
                </td>
              </tr>
            ) : (
              filteredInstruments.map((cw) => {
                const watched = isInWatchlist(cw.symbol);
                const isSelected = selectedSymbol === cw.symbol;

                return (
                  <tr
                    key={cw.symbol}
                    tabIndex={0}
                    onClick={() => setSelectedSymbol(cw.symbol)}
                    onKeyDown={(e) => e.key === "Enter" && setSelectedSymbol(cw.symbol)}
                    className={`table-row ${isSelected ? "table-row-selected" : ""}`}
                    style={{
                      height: "40px",
                      cursor: "pointer",
                      borderBottom: "1px solid var(--border)",
                    }}
                  >
                    <td className="tnum text-primary" style={{ padding: "0 12px", fontSize: "13px" }}>
                      {cw.symbol}
                    </td>
                    <td style={{ padding: "0 12px", fontSize: "12px", color: "var(--muted-foreground)" }}>
                      {cw.issuer || "—"}
                    </td>
                    <td className="tnum" style={{ padding: "0 12px", fontSize: "12px", color: "var(--foreground)" }}>
                      {cw.underlyingSymbol || "—"}
                    </td>
                    <td className="tnum" style={{ padding: "0 12px", textAlign: "right", fontSize: "12px", color: "var(--foreground)" }}>
                      {formatPrice(cw.strikePrice)}
                    </td>
                    <td className="tnum" style={{ padding: "0 12px", textAlign: "right", fontSize: "12px", color: "var(--muted-foreground)" }}>
                      {cw.exerciseRatio ? `${cw.exerciseRatio}:1` : "—"}
                    </td>
                    <td className="tnum" style={{ padding: "0 12px", textAlign: "right", fontSize: "12px", color: "var(--muted-foreground)" }}>
                      {cw.maturityDate || "—"}
                    </td>
                    <td className="tnum" style={{ padding: "0 12px", textAlign: "right", fontSize: "12px", color: "var(--subtle-foreground)" }}>
                      {calculateDTE(cw.lastTradingDate, cw.maturityDate)}
                    </td>
                    <td style={{ padding: "0 12px", textAlign: "right", fontSize: "12px" }}>
                      {watched ? (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            if (onNavigateToDashboard) onNavigateToDashboard();
                          }}
                          className="focus-ring"
                          title="Active in Live Dashboard. Click to view dashboard."
                          style={{
                            background: "transparent",
                            border: "none",
                            padding: "2px 4px",
                            cursor: onNavigateToDashboard ? "pointer" : "default",
                            display: "inline-flex",
                            alignItems: "center",
                            gap: "6px",
                            color: "var(--muted-foreground)",
                          }}
                        >
                          <span style={{ width: "4px", height: "4px", borderRadius: "50%", backgroundColor: "var(--primary)" }} />
                          Live
                        </button>
                      ) : (
                        <span style={{ color: "var(--subtle-foreground)" }}>Static</span>
                      )}
                    </td>
                    <td style={{ paddingRight: "8px", textAlign: "right" }}>
                      <button
                        title={watched ? "Remove from dashboard" : "Add to dashboard"}
                        aria-label={watched ? `Remove ${cw.symbol} from dashboard` : `Add ${cw.symbol} to dashboard`}
                        onClick={(e) => handleToggle(e, cw)}
                        className="focus-ring"
                        style={{
                          background: "transparent",
                          border: "none",
                          cursor: "pointer",
                          padding: "4px",
                          borderRadius: "2px",
                          color: watched ? "var(--primary)" : "var(--subtle-foreground)",
                          display: "inline-flex",
                          alignItems: "center",
                          transition: "color 0.15s ease",
                        }}
                      >
                        {watched ? <Check size={14} strokeWidth={1.5} /> : <Plus size={14} strokeWidth={1.5} />}
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Detail Drawer */}
      <InstrumentDrawer
        instrument={selectedInstrument}
        onClose={() => setSelectedSymbol(null)}
      />
    </div>
  );
}
