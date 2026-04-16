import { useState, useMemo, useEffect } from "react";
import { Topbar } from "./Topbar";
import { PanelTitle } from "./PanelTitle";
import { TableView } from "@/tables/core/TableView";
import { cwTable } from "@/tables/cw/CWTable";
import { useEquityData } from "@/data/useEquityData";
import { colors } from "@/design/tokens";
import { FilterCW, FilterState } from "@/tables/cw/FilterCW";
import { BubbleChart } from "./BubbleChart";
import { MarketShareContainer } from "./MarketShareTables";
import { DisplayOptionContent } from "@/tables/core/DisplayOptionContent";
import { TATab } from "./TATab";

const INITIAL_FILTERS: FilterState = {
  underlyings: ["All"],
  issuers: ["All"],
  tradingDate: "",
  fromDate: "",
  toDate: "",
};

type ViewMode = "table" | "chart" | "ta";

export function App() {
  const { rows, tradingDates, requestListedVolumes, listedVolumes, lastChanges, serverTimeOffset } = useEquityData();
  const [viewMode, setViewMode] = useState<ViewMode>("table");
  const [hiddenColumns, setHiddenColumns] = useState<string[]>([]);
  
  // Independent filter states
  const [tableFilters, setTableFilters] = useState<FilterState>(INITIAL_FILTERS);
  const [chartFilters, setChartFilters] = useState<FilterState>(INITIAL_FILTERS);

  // Request listed volumes when chart trading date changes
  useEffect(() => {
    if (chartFilters.tradingDate) {
      requestListedVolumes(chartFilters.tradingDate);
    }
  }, [chartFilters.tradingDate, requestListedVolumes]);

  // Request listed volumes when table trading date changes
  useEffect(() => {
    if (tableFilters.tradingDate) {
      requestListedVolumes(tableFilters.tradingDate);
    }
  }, [tableFilters.tradingDate, requestListedVolumes]);

  const toggleColumn = (key: string) => {
    setHiddenColumns((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    );
  };

  const resetColumns = () => {
    setHiddenColumns([]);
  };

  // Extract unique underlyings and issuers from data
  const { underlyings, issuers } = useMemo(() => {
    const u = new Set<string>();
    const i = new Set<string>();
    rows.forEach(r => {
      if (r.Under_Symbol) u.add(r.Under_Symbol);
      if (r.Issuer) i.add(r.Issuer);
    });
    return {
      underlyings: Array.from(u).sort(),
      issuers: Array.from(i).sort(),
    };
  }, [rows]);

  const filterData = (data: any[], filters: FilterState, historicalVolumes?: Record<string, number>) => {
    return data.map(r => {
      // If historical volumes are provided for a specific date, override Listed_Vol
      if (filters.tradingDate && historicalVolumes && historicalVolumes[r.Symbol] !== undefined) {
        return { ...r, Listed_Vol: historicalVolumes[r.Symbol] };
      }
      return r;
    }).filter(r => {
      if (r.Symbol.length <= 3) return false;

      // Multi-select Filter by Underlying
      if (filters.underlyings.length > 0) {
        if (!filters.underlyings.includes("All") && !filters.underlyings.includes(r.Under_Symbol)) {
          return false;
        }
      } else {
        // If nothing is selected, show nothing
        return false;
      }

      // Multi-select Filter by Issuer
      if (filters.issuers.length > 0) {
        if (!filters.issuers.includes("All") && !filters.issuers.includes(r.Issuer)) {
          return false;
        }
      } else {
        return false;
      }

      if (!r.LastTradingDate) return false;

      const rowDate = new Date(r.LastTradingDate);
      if (isNaN(rowDate.getTime())) return false;

      const today = new Date();
      today.setHours(0, 0, 0, 0);
      
      // If a specific trading date is selected (Chart view), only show CWs that were active then
      if (filters.tradingDate) {
        const selDate = new Date(filters.tradingDate);
        // Symbol must not have expired before the selected date
        if (rowDate < selDate) return false;
        
        // Also check if we have historical volume for it on that date
        // If the date is selected but symbol isn't in historicalVolumes, it might not have been listed yet
        if (historicalVolumes && historicalVolumes[r.Symbol] === undefined) {
          return false;
        }
      } else {
        // Basic rule for real-time table: don't show expired warrants unless specifically requested via filters
        if (rowDate < today && !filters.fromDate && !filters.toDate) return false;
      }

      // Range filtering by Last Trading Date
      if (filters.fromDate) {
        const from = new Date(filters.fromDate);
        if (rowDate < from) return false;
      }
      if (filters.toDate) {
        const to = new Date(filters.toDate);
        if (rowDate > to) return false;
      }

      return true;
    });
  };

  const filteredTableData = useMemo(() => filterData(rows, tableFilters, listedVolumes), [rows, tableFilters, listedVolumes]);
  const filteredChartData = useMemo(() => filterData(rows, chartFilters, listedVolumes), [rows, chartFilters, listedVolumes]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        backgroundColor: colors.background,
      }}
    >
      <Topbar currentView={viewMode} onViewChange={setViewMode} serverTimeOffset={serverTimeOffset} />

      <div
        style={{
          flex: 1,
          display: "flex",
          padding: "6px 18px 6px 18px",
          overflow: "auto",
        }}
      >
        {/* Covered Warrant Table Tab */}
        <div 
          style={{ 
            flex: 1, 
            display: viewMode === "table" ? "flex" : "none", 
            flexDirection: "column", 
            minWidth: 0 
          }}
        >
          <PanelTitle
            title="Covered Warrant"
            displayOptionContent={
              <DisplayOptionContent
                columns={cwTable.getColumns().map((c) => ({ key: c.key, header: c.header }))}
                hiddenColumns={hiddenColumns}
                onToggleColumn={toggleColumn}
                onReset={resetColumns}
              />
            }
            filterContent={
              <FilterCW
                underlyings={underlyings}
                issuers={issuers}
                tradingDates={tradingDates}
                filters={tableFilters}
                onFilterChange={setTableFilters}
                onClear={() => setTableFilters(INITIAL_FILTERS)}
                mode="range"
              />
            }
          />
          <TableView
            table={cwTable}
            data={filteredTableData}
            hiddenColumns={hiddenColumns}
            lastChanges={lastChanges}
          />
        </div>

        {/* Chart (Bubble Chart) Tab */}
        <div 
          style={{ 
            flex: 1, 
            display: viewMode === "chart" ? "flex" : "none", 
            flexDirection: "column", 
            minWidth: 0 
          }}
        >
          <PanelTitle
            title="Bubble Chart"
            filterContent={
              <FilterCW
                underlyings={underlyings}
                issuers={issuers}
                tradingDates={tradingDates}
                filters={chartFilters}
                onFilterChange={setChartFilters}
                onClear={() => setChartFilters(INITIAL_FILTERS)}
                mode="single"
              />
            }
          />
          <div style={{ flex: 1, display: "flex", gap: 20, minHeight: 0 }}>
            <div style={{ flex: 5, backgroundColor: "rgba(255, 255, 255, 0.02)", borderRadius: 8, padding: 10, minWidth: 0 }}>
              <BubbleChart data={filteredChartData} />
            </div>
            <MarketShareContainer data={filteredChartData} allRows={rows} />
          </div>
        </div>

        {/* TA (Technical Analysis) Tab */}
        <div 
          style={{ 
            flex: 1, 
            display: viewMode === "ta" ? "flex" : "none", 
            flexDirection: "column", 
            minWidth: 0 
          }}
        >
          <TATab />
        </div>
      </div>
    </div>
  );
}
