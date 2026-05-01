import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiTarget = process.env.VITE_API_URL || "http://localhost:8787";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 3125,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  preview: {
    host: "0.0.0.0",
    port: 3125,
  },
});
