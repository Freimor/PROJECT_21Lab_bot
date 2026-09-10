import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/app/",
  build: {
    outDir: "../src/lab21_bot/miniapp/static",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api/miniapp": "http://localhost:8080",
      "/uploads": "http://localhost:8080",
    },
  },
});
