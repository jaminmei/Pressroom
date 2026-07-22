import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "@xyflow/react/dist/style.css";
import App from "@/app/App";
import "@/styles/global.css";
import "@/styles/workspace-shell.css";
import "@/styles/workspace-settings.css";
import "@/styles/workspace-polish.css";

import.meta.glob("./types/*Register.ts", { eager: true });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
