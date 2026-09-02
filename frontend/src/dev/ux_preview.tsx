/** Separate dev entry, excluded from production index.html and its module graph. */
import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MarketExplorer } from "@/features/market_overview/market_explorer";
import { SignInDialog } from "@/features/auth/sign_in_dialog";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-mono/600.css";
import "@/design/global.css";

const client = new QueryClient({
  defaultOptions: { queries: { retry: false, staleTime: 60_000 } },
});
function Preview() {
  const [scenario, setScenario] = useState("last-session");
  const [auth, setAuth] = useState(false);
  useEffect(() => {
    void fetch("http://127.0.0.1:8502/__scenario")
      .then((r) => r.json())
      .then((r) => setScenario(r.scenario));
  }, []);
  return (
    <>
      <div className="fixture-banner">
        <strong>UX preview · fixed test data</strong>
        <select
          aria-label="Fixture scenario"
          value={scenario}
          onChange={async (e) => {
            await fetch(`http://127.0.0.1:8502/__scenario/${e.target.value}`, {
              method: "POST",
            });
            window.location.reload();
          }}
        >
          <option value="last-session">Last session</option>
          <option value="live">Live</option>
          <option value="empty">Empty data</option>
          <option value="error">API error</option>
        </select>
        <button onClick={() => setAuth(true)}>Test sign-in</button>
      </div>
      <MarketExplorer />
      {auth && <SignInDialog onClose={() => setAuth(false)} />}
    </>
  );
}
if (!import.meta.env.DEV)
  throw new Error(
    "The fixture preview is only available in Vite development mode.",
  );
createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={client}>
    <Preview />
  </QueryClientProvider>,
);
