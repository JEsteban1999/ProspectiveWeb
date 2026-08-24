/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

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
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    // The 3D components pull in WebGL and Node's "events" and are not unit
    // tested; the pure helpers beside them (marker sizing) are.
    exclude: ["node_modules/**", "dist/**", "src/vtk/*View.test.*"],
  },
  server: {
    port: 5173,
    proxy: {
      // Override with BACKEND_URL when :8000 is taken — on Windows the socket
      // can survive the uvicorn process and stay bound to a PID that is gone.
      "/api": backend,
      "/data": backend,
      "/static": backend,
    },
  },
});
