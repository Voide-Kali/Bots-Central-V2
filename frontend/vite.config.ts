import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  // The panel is served under /painel (Caddy) — build assets with this base so they resolve to
  // /painel/assets/*. Keep in sync with BASE in src/app/navigation.ts and the Caddyfile.
  base: "/painel/",
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts"
  }
});
