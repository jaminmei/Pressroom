import path from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { configDefaults, defineConfig } from "vitest/config";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function resolveManualChunk(id: string) {
  if (!id.includes("node_modules")) {
    return undefined;
  }

  if (
    id.includes("/react-markdown/") ||
    id.includes("/remark-gfm/") ||
    id.includes("/rehype-sanitize/") ||
    id.includes("/remark-parse/") ||
    id.includes("/remark-rehype/") ||
    id.includes("/mdast-util-") ||
    id.includes("/micromark") ||
    id.includes("/hast-util-") ||
    id.includes("/unist-util-") ||
    id.includes("/decode-named-character-reference")
  ) {
    return "vendor-markdown";
  }

  if (id.includes("/@xyflow/")) {
    return "vendor-xyflow";
  }

  if (id.includes("/@ant-design/icons/")) {
    return "vendor-antd";
  }

  if (id.includes("/antd/")) {
    return "vendor-antd";
  }

  if (id.includes("/rc-") || id.includes("/@rc-component/") || id.includes("/@ant-design/")) {
    return "vendor-antd";
  }

  if (id.includes("/react-router/") || id.includes("/react-router-dom/") || id.includes("/react-dom/")) {
    return "vendor-react-router";
  }

  if (id.includes("/react/")) {
    return "vendor-react";
  }

  return undefined;
}

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          return resolveManualChunk(id);
        }
      }
    }
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src")
    }
  },
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true
      },
      "/ws": {
        target: "http://localhost:8000",
        changeOrigin: true,
        ws: true
      }
    }
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    exclude: [...configDefaults.exclude, "e2e/**"],
    testTimeout: 10_000
  }
});
