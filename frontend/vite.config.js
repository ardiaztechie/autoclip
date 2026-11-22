import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Semua permintaan ke /api diteruskan ke backend FastAPI (port 8000) dengan awalan /api dibuang.
// Karena browser hanya bicara dengan satu alamat (localhost:5173), cookie login bekerja tanpa pengaturan CORS.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
