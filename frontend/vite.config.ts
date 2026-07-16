import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, proxy /api -> the local backend and strip the /api prefix.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
