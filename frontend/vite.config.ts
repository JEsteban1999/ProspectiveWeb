import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies every backend surface to FastAPI on :8000 so the
// frontend can use same-origin URLs (/api/…, /data/sessions/…, /static/…).
export default defineConfig({
  plugins: [react()],
  // vtk.js imports Node's "events" module; without the browser polyfill Vite
  // externalizes it and vtk.js's macro base class becomes undefined.
  resolve: {
    alias: { events: "events" },
  },
  optimizeDeps: {
    include: ["events"],
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/data": "http://127.0.0.1:8000",
      "/static": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
});
