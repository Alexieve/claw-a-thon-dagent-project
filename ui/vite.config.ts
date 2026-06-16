import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import path from "path";
import { defineConfig } from "vite";
import svgr from "vite-plugin-svgr";

export default defineConfig({
  plugins: [tailwindcss(), react(), svgr(), tanstackRouter()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") }
  },
  server: { port: 5177, host: true },
  build: { target: "esnext", outDir: "dist", sourcemap: true }
});
