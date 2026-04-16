import { useState, useMemo } from "react";
import { Topbar } from "./Topbar";
import { PanelTitle } from "./PanelTitle";
import { TableView } from "@/tables/core/TableView";
import { stockTable } from "@/tables/stock/StockTable";
import { useEquityData } from "@/data/useEquityData";
import { colors } from "@/design/tokens";
import { DisplayOptionContent } from "@/tables/core/DisplayOptionContent";

const VN30_SYMBOLS = [
  "ACB", "BCM", "BID", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG", "LPB", "MBB", "MSN", "MWG", "PLX", "SAB", "SHB", "SSB", "SSI", "STB", "TCB", "TPB", "VCB", "VHM", "VIC", "VIB", "VJC", "VNM", "VPB", "VRE", "VPL"
];

type ViewMode = "table";

export function App() {
  const { rows, lastChanges, serverTimeOffset } = useEquityData();
  const [viewMode, setViewMode] = useState<ViewMode>("table");
  const [hiddenColumns, setHiddenColumns] = useState<string[]>([]);

  const toggleColumn = (key: string) => {
    setHiddenColumns((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    );
  };

  const resetColumns = () => {
    setHiddenColumns([]);
  };

  const filteredTableData = useMemo(() => {
    return rows.filter(r => VN30_SYMBOLS.includes(r.Symbol));
  }, [rows]);

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
        {/* VN30 Stock Table Tab */}
        <div
          style={{
            flex: 1,
            display: viewMode === "table" ? "flex" : "none",
            flexDirection: "column",
            minWidth: 0
          }}
        >
          <PanelTitle
            title="Stocks"
            displayOptionContent={
              <DisplayOptionContent
                columns={stockTable.getColumns().map((c) => ({ key: c.key, header: c.header }))}
                hiddenColumns={hiddenColumns}
                onToggleColumn={toggleColumn}
                onReset={resetColumns}
              />
            }
          />
          <TableView
            table={stockTable}
            data={filteredTableData}
            hiddenColumns={hiddenColumns}
            lastChanges={lastChanges}
          />
        </div>
      </div>
    </div>
  );
}
