import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./app/App";
import { EquityDataProvider } from "./data/useEquityData";
import "./design/global.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <EquityDataProvider>
      <App />
    </EquityDataProvider>
  </React.StrictMode>
);

