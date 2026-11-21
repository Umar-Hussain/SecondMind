import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend runs on :8000; requests to /api are proxied there so the
// browser only ever talks to one origin during development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        ws: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
});
