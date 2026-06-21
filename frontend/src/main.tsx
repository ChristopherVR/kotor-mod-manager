import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { LanguageProvider } from "@/lib/i18n";
import { initUiSounds } from "@/lib/sound";
import "./index.css";

// Attach the global menu-click sound (no-op until enabled in Settings).
initUiSounds();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <LanguageProvider>
      <App />
    </LanguageProvider>
  </React.StrictMode>
);
