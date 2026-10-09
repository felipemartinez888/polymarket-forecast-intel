import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Relative base so the static build works on Cloudflare Pages, GitHub Pages sub-paths, or a local file server.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 900 },
});
