import { defineConfig, devices } from "@playwright/test";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { resolveCogshamboPorts } from "./src/server/ports";

const ports = resolveCogshamboPorts();
const smokeSqlitePath = join(tmpdir(), `cogshambo-smoke-${ports.serverPort}.sqlite`);
const resetSmokeSqlite = `node -e 'require("node:fs").rmSync(${JSON.stringify(smokeSqlitePath)}, { force: true })'`;

export default defineConfig({
  testDir: "tests/smoke",
  timeout: 30_000,
  use: {
    baseURL: ports.backendOrigin,
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions: {
          args: ["--enable-unsafe-webgpu"],
        },
      },
    },
  ],
  webServer: {
    command: `${resetSmokeSqlite} && npm run build && COGSHAMBO_DISABLE_SPRITE_PIPELINE=1 COGSHAMBO_SQLITE_PATH=${JSON.stringify(smokeSqlitePath)} PORT=${ports.serverPort} npm run start`,
    url: ports.backendOrigin,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
