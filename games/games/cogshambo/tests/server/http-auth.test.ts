import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createServer } from "node:http";
import { AddressInfo } from "node:net";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { createApp } from "../../src/server/http.js";
import type { ControllerRegistry } from "../../src/server/controllers/cog-controller.js";
import { createSimulationControls } from "../../src/server/simulation/control.js";
import { GridWorld } from "../../src/server/simulation/world.js";
import { createSqliteSettingsStore, type SettingsStore } from "../../src/server/settings-store.js";
import { createJsonVenueEditorStore, type VenueEditorStore } from "../../src/server/venue-editor-store.js";

let server: ReturnType<typeof createServer>;
let baseUrl: string;
let settingsStore: SettingsStore;
let venueEditorStore: VenueEditorStore;
let tempDir: string;

beforeEach(async () => {
  tempDir = mkdtempSync(path.join(tmpdir(), "cogshambo-http-auth-"));
  settingsStore = createSqliteSettingsStore(":memory:");
  venueEditorStore = createJsonVenueEditorStore(path.join(tempDir, "venue-graph.json"));
  const app = createApp({
    world: new GridWorld({ width: 1, height: 1 }),
    controllers: {} as ControllerRegistry,
    controls: createSimulationControls(),
    settingsStore,
    venueEditorStore,
    spriteGenerator: async () => [],
  });
  server = createServer(app);
  await new Promise<void>((resolve) => server.listen(0, resolve));
  const address = server.address() as AddressInfo;
  baseUrl = `http://127.0.0.1:${address.port}`;
});

afterEach(async () => {
  await new Promise<void>((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
  settingsStore.close();
  venueEditorStore.close();
  rmSync(tempDir, { recursive: true, force: true });
});

describe("main game HTTP auth", () => {
  it("requires basic auth for the main game screen only", async () => {
    const challenge = await fetch(`${baseUrl}/`);

    expect(challenge.status).toBe(401);
    expect(challenge.headers.get("www-authenticate")).toContain('Basic realm="Cogshambo"');
    expect(await challenge.text()).toBe("Authentication required");

    const badCredentials = await fetch(`${baseUrl}/`, {
      headers: {
        authorization: `Basic ${Buffer.from("daveey:wrong").toString("base64")}`,
      },
    });
    expect(badCredentials.status).toBe(401);

    const authorized = await fetch(`${baseUrl}/`, {
      headers: {
        authorization: `Basic ${Buffer.from("daveey:daviddavid").toString("base64")}`,
      },
    });
    expect(authorized.status).not.toBe(401);
    expect(authorized.headers.get("www-authenticate")).toBeNull();

    const directIndex = await fetch(`${baseUrl}/index.html`);
    expect(directIndex.status).toBe(401);

    for (const route of ["/builder", "/config", "/profile/red-1"]) {
      const response = await fetch(`${baseUrl}${route}`);
      expect(response.status).not.toBe(401);
      expect(response.headers.get("www-authenticate")).toBeNull();
    }
  });
});
