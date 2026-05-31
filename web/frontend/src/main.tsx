import "./index.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { project } from "./config/project";

// Apply project theme as CSS custom properties
const root = document.documentElement;
Object.entries(project.theme).forEach(([key, value]) => {
  // camelCase → kebab-case: bgPrimary → bg-primary
  const cssVar = `--${key.replace(/[A-Z]/g, (m) => `-${m.toLowerCase()}`)}`;
  root.style.setProperty(cssVar, value);
});

// Set page title
document.title = project.pageTitle;

// Set favicon dynamically
const faviconEl = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
if (faviconEl) faviconEl.href = project.favicon;

createRoot(document.getElementById("root")!).render(<App />);
