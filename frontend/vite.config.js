import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // Proxy keeps the browser on one origin, so no CORS setup is needed.
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/health": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/documents": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/audit": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
