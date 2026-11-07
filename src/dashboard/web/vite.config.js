import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  // Base relative : le bundle fonctionne sous tout préfixe d'URL.
  base: "./",
  plugins: [react(), tailwindcss()],
  // Serveur de développement : /api part vers le service dashboard-api.
  server: { proxy: { "/api": "http://dashboard-api:8000" } },
  build: {
    outDir: "dist",
    // Content-hashed names (assets/[name]-[hash].js): nginx can cache /assets/ for a year.
    assetsDir: "assets",
  },
});
