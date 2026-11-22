import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";
import "./lichess.css";
import "./landing.css";

// Theme: dark by default (Lichess style); the light theme is a saved per-browser preference.
try {
  if (localStorage.getItem("secondmind.theme") === "light") document.documentElement.dataset.theme = "light";
} catch {
  /* storage unavailable: stay dark */
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
