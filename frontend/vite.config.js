import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true, // si el 5173 está ocupado, falla en vez de cambiarse
  },
});
