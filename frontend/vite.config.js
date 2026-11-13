import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: chạy backend ở :8000, Vite proxy /api sang đó. Build: dist/ được FastAPI phục vụ.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://localhost:8000" } },
});
