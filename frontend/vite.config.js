import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `vite --host` (see package.json) binds to 0.0.0.0, so any device on
// the same WiFi — including a phone — can open http://<your-PC-IP>:5173
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
});
