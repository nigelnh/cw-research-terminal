import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./app/App";
import { EquityDataProvider } from "./data/useEquityData";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "@material-design-icons/font";
import "./design/global.css";


ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <EquityDataProvider>
      <App />
    </EquityDataProvider>
  </React.StrictMode>
);

