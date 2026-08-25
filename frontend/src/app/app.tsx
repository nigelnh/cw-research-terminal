import { MarketExplorer } from "@/components/MarketExplorer/market_explorer";

/**
 * Main Application Shell for Covered Warrant Research Platform.
 * Renders the MarketExplorer workspace unconditionally in all data modes (mock and live).
 * Provider resolution is strictly delegated to ProviderFactory.
 */
export function App() {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        width: "100vw",
        overflow: "hidden",
        backgroundColor: "#0f172a",
      }}
    >
      <MarketExplorer />
    </div>
  );
}
