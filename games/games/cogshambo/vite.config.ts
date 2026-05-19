import { defineConfig } from "vite";
import { resolveCogshamboPorts } from "./src/server/ports";

const ports = resolveCogshamboPorts();

export default defineConfig({
  server: {
    host: "127.0.0.1",
    port: ports.vitePort,
    strictPort: true,
    allowedHosts: ["redvblue.dbloom.in"],
    proxy: {
      "/api": ports.backendOrigin,
      "/ws": {
        target: ports.backendOrigin,
        ws: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
