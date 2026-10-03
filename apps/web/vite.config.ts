import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    allowedHosts: ["involve-works-transport-phoenix.trycloudflare.com", "non-generally-taxes-complex.trycloudflare.com", "approach-william-whose-girlfriend.trycloudflare.com", "thereby-examines-reggae-tiles.trycloudflare.com"],
    proxy: { "/api": process.env.FALKRONA_DEV_API_URL ?? "http://127.0.0.1:8000", "/health": process.env.FALKRONA_DEV_API_URL ?? "http://127.0.0.1:8000" },
  },
});
