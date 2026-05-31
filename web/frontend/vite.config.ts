import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";
import fs from "fs";

/**
 * Detect parent project overrides.
 *
 * When this framework is used as a submodule at my_project/framework/,
 * __dirname is my_project/framework/web/frontend/.
 * Parent root is 3 levels up: my_project/
 *
 * We look for:
 *   my_project/web/project-config.ts  → @project/config
 *   my_project/web/pages/index.ts     → @project/pages
 *   my_project/web/public/            → publicDir
 */
const parentRoot = process.env.VITE_PROJECT_ROOT
  ? path.resolve(process.env.VITE_PROJECT_ROOT)
  : path.resolve(__dirname, "../../..");

// Read BACKEND_PORT from project .env (process.env doesn't include .env files)
function readBackendPort(): number {
  const envPath = path.join(parentRoot, ".env");
  try {
    const content = fs.readFileSync(envPath, "utf8");
    const match = content.match(/^BACKEND_PORT\s*=\s*(\d+)/m);
    if (match) return parseInt(match[1], 10);
  } catch {}
  return 8000;
}
const backendPort = readBackendPort();

const parentConfigPath = path.join(parentRoot, "web", "project-config.ts");
const parentPagesPath = path.join(parentRoot, "web", "pages", "index.ts");
const parentPublicDir = path.join(parentRoot, "web", "public");

const hasParentConfig = fs.existsSync(parentConfigPath);
const hasParentPages = fs.existsSync(parentPagesPath);
const hasParentPublic = fs.existsSync(parentPublicDir);

export default defineConfig({
  plugins: [react(), tailwindcss()],
  publicDir: hasParentPublic ? parentPublicDir : "public",
  resolve: {
    alias: {
      "@project/config": hasParentConfig
        ? parentConfigPath
        : path.resolve(__dirname, "src/config/projectOverrides.ts"),
      "@project/pages": hasParentPages
        ? parentPagesPath
        : path.resolve(__dirname, "src/pages/defaultPages.ts"),
      // Parent-project files (web/pages/**) live outside this Vite root, so
      // Node's walk-up resolution can't reach our node_modules at build
      // time. Pin the bare specifiers they import to this package's copy.
      // Aliasing react + react-dom also dedupes them — without this, a
      // parent file importing React directly could pull a different copy
      // than the framework and break hooks with "invalid hook call".
      "lucide-react": path.resolve(__dirname, "node_modules/lucide-react"),
      "react": path.resolve(__dirname, "node_modules/react"),
      "react-dom": path.resolve(__dirname, "node_modules/react-dom"),
    },
  },
  server: {
    port: 5173,
    fs: {
      // Allow Vite to serve project-level files (e.g. web/pages/**) that
      // live above the framework/web/frontend root when this framework is
      // used as a submodule. Without this, requests for parent files are
      // rejected with "outside of Vite serving allow list".
      allow: [path.resolve(__dirname), parentRoot],
    },
    proxy: {
      "/api": `http://localhost:${backendPort}`,
      "/ws": {
        target: `ws://localhost:${backendPort}`,
        ws: true,
      },
      "/files": `http://localhost:${backendPort}`,
    },
  },
});
