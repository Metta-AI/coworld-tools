import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createServer } from "node:http";
import { AddressInfo } from "node:net";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { WebSocket } from "ws";
import { CLIENT_COG_CONVERSATION_LOG_LIMIT } from "../../src/server/client-snapshot.js";
import { compactGenerationError, createApp } from "../../src/server/http.js";
import type { ControllerRegistry } from "../../src/server/controllers/cog-controller.js";
import { createControllerRegistry } from "../../src/server/controllers/cog-controller.js";
import { createSimulationControls } from "../../src/server/simulation/control.js";
import { createSeedWorld } from "../../src/server/simulation/seed-world.js";
import { GridWorld } from "../../src/server/simulation/world.js";
import { createSqliteSettingsStore, type SettingsStore } from "../../src/server/settings-store.js";
import { createJsonVenueEditorStore, type VenueEditorStore } from "../../src/server/venue-editor-store.js";
import {
  attachWorldSocketServer,
  MAX_WEBSOCKET_BUFFERED_BYTES,
  sendEncoded,
} from "../../src/server/websocket.js";
import type { WorldStateStore } from "../../src/server/world-state-store.js";
import type { GenerateCogSpritesRequest } from "../../src/shared/protocol.js";
import type { CogAction, WorldSnapshot } from "../../src/shared/types.js";

let server: ReturnType<typeof createServer>;
let baseUrl: string;
let generatedSpriteRequests: GenerateCogSpritesRequest[];
let settingsStore: SettingsStore;
let venueEditorStore: VenueEditorStore;
let tempDir: string;

beforeEach(async () => {
  tempDir = mkdtempSync(path.join(tmpdir(), "cogshambo-api-"));
  settingsStore = createSqliteSettingsStore(":memory:");
  venueEditorStore = createJsonVenueEditorStore(path.join(tempDir, "venue-graph.json"));
  const world = createSeedWorld();
  generatedSpriteRequests = [];
  const app = createApp({
    world,
    controllers: createControllerRegistry(),
    controls: createSimulationControls(),
    settingsStore,
    venueEditorStore,
    deployVersion: () => ({
      commit: "0123456789abcdef",
      shortCommit: "0123456",
      deployId: "0123456-20260515T183000Z",
      deployedAt: "2026-05-15T18:30:00Z",
      ref: "main",
      source: "file",
    }),
    spriteGenerator: async (request) => {
      generatedSpriteRequests.push(request);
      return Array.from({ length: request.count }, (_value, index) => ({
        key: `generated-test-${index + 1}`,
        label: `Sprite ${index + 1}`,
        url: `/assets/cogshambo/cogs/generated-test-${index + 1}.png`,
        spriteUrls: {
          red: `/assets/cogshambo/cogs/generated-test-${index + 1}-red.png`,
          blue: `/assets/cogshambo/cogs/generated-test-${index + 1}-blue.png`,
        },
      }));
    },
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

describe("HTTP API", () => {
  it("prioritizes actionable sprite generator stderr over progress output", () => {
    const detail = compactGenerationError({
      message: "Command failed: npm run art:sheet",
      stdout: "Generating with retro-diffusion/rd-plus\n  Size: 192x192\n  Category: cogs",
      stderr:
        'Traceback\nreplicate.exceptions.ReplicateError: ReplicateError Details:\ntitle: Input validation failed\nstatus: 422\ndetail: - input.style: style must be one of the following: "topdown_asset"',
    });

    expect(detail).toContain("input.style");
    expect(detail).toContain("topdown_asset");
    expect(detail).not.toContain("Size: 192x192");
  });

  it("returns health status", async () => {
    const response = await fetch(`${baseUrl}/health`);
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.ok).toBe(true);
    expect(body.snapshot.cogs.length).toBeGreaterThan(0);
  });

  it("returns deployment version metadata", async () => {
    const response = await fetch(`${baseUrl}/version`);
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({
      commit: "0123456789abcdef",
      shortCommit: "0123456",
      deployId: "0123456-20260515T183000Z",
      deployedAt: "2026-05-15T18:30:00Z",
      ref: "main",
      source: "file",
    });
  });

  it("returns the latest world snapshot", async () => {
    const response = await fetch(`${baseUrl}/api/world`);
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.tick).toBe(0);
    expect(body.dimensions).toEqual({ width: 50, height: 28 });
    expect(body).not.toHaveProperty("activeColors");
    expect(body).not.toHaveProperty("colorScores");
    expect(body.cogs.every((cog: { color: string }) => ["red", "blue"].includes(cog.color))).toBe(true);
  });

  it("returns and updates editable game config", async () => {
    const initialResponse = await fetch(`${baseUrl}/api/config`);
    const initialBody = await initialResponse.json();

    expect(initialResponse.status).toBe(200);
    expect(initialBody.config.conversionThreshold).toBe(100);
    expect(initialBody.parameters.some((parameter: { key: string }) => parameter.key === "maxDebateRounds")).toBe(true);
    expect(initialBody.parameters.some((parameter: { key: string }) => parameter.key === "maxDebatesPerTick")).toBe(true);
    expect(initialBody.parameters.some((parameter: { key: string }) => parameter.key === "charismaticDoubt")).toBe(
      false,
    );
    expect(initialBody.traits.length).toBeGreaterThan(0);
    expect(
      initialBody.traits.some((trait: { id: string; parameters?: Array<{ key: string }> }) =>
        trait.id === "charismatic" && trait.parameters?.some((parameter) => parameter.key === "witnessDoubt"),
      ),
    ).toBe(true);
    for (const [traitId, parameterKey] of [
      ["stubborn", "directDoubtMultiplier"],
      ["insular", "indirectDoubtMultiplier"],
      ["iconoclast", "dominantDoubtMultiplier"],
      ["conformist", "fringeDoubtMultiplier"],
      ["forceful", "winDoubtMultiplier"],
      ["contrarian", "debateCooldownMultiplier"],
      ["rationalist", "winDoubtMultiplier"],
      ["spinner", "winDoubtMultiplier"],
      ["passionate", "winDoubtMultiplier"],
    ]) {
      expect(
        initialBody.traits.some((trait: { id: string; parameters?: Array<{ key: string }> }) =>
          trait.id === traitId && trait.parameters?.some((parameter) => parameter.key === parameterKey),
        ),
      ).toBe(true);
    }
    expect(initialBody.goals).toEqual([]);

    const updateResponse = await fetch(`${baseUrl}/api/config`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        debateDoubt: 30,
        maxDebateRounds: 4,
        maxDebatesPerTick: 2,
        traitConfig: {
          charismatic: {
            witnessDoubt: 5,
          },
        },
      }),
    });
    const updateBody = await updateResponse.json();

    expect(updateResponse.status).toBe(200);
    expect(updateBody.config.debateDoubt).toBe(30);
    expect(updateBody.config.maxDebateRounds).toBe(4);
    expect(updateBody.config.maxDebatesPerTick).toBe(2);
    expect(updateBody.config.traitConfig.charismatic.witnessDoubt).toBe(5);

    const reloadBody = await fetch(`${baseUrl}/api/config`).then((response) => response.json());
    expect(reloadBody.settingsDb).toBe("default");
    expect(reloadBody.config.debateDoubt).toBe(30);
    expect(reloadBody.presets).toEqual([
      expect.objectContaining({
        settingsDb: "default",
        name: "Default",
      }),
    ]);
  });

  it("creates and selects settings presets backed by sqlite", async () => {
    await fetch(`${baseUrl}/api/config`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ debateDoubt: 33 }),
    });

    const createResponse = await fetch(`${baseUrl}/api/config/presets`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "Fast Certainty" }),
    });
    const createBody = await createResponse.json();

    expect(createResponse.status).toBe(201);
    expect(createBody.settingsDb).toBe("fast-certainty");
    expect(createBody.config.debateDoubt).toBe(33);
    expect(createBody.presets.map((preset: { settingsDb: string }) => preset.settingsDb)).toEqual([
      "default",
      "fast-certainty",
    ]);

    await fetch(`${baseUrl}/api/config`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ debateDoubt: 44 }),
    });

    const selectResponse = await fetch(`${baseUrl}/api/config/current`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ settingsDb: "default" }),
    });
    const selectBody = await selectResponse.json();

    expect(selectResponse.status).toBe(200);
    expect(selectBody.settingsDb).toBe("default");
    expect(selectBody.config.debateDoubt).toBe(33);
  });

  it("rejects cogs outside the red and blue teams", async () => {
    const response = await fetch(`${baseUrl}/api/cogs`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        name: "Green",
        spriteSheetKey: "cog-green",
        controllerId: "stub",
        color: "green",
        attributes: { energy: 9 },
      }),
    });
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(body.error).toBe("Invalid create cog request");
    expect(body.issues).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          path: ["color"],
        }),
      ]),
    );
  });

  it("creates a cog through the API", async () => {
    const response = await fetch(`${baseUrl}/api/cogs`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        name: "Grace",
        spriteSheetKey: "cog-grace",
        spriteUrl: "data:image/png;base64,abc",
        spriteUrls: {
          red: "/assets/cogshambo/cogs/grace-red.png",
          blue: "/assets/cogshambo/cogs/grace-blue.png",
        },
        controllerId: "stub",
        color: "blue",
        defensiveTrait: "stubborn",
        activeTrait: "passionate",
        personalGoal: "underdog",
        attributes: { energy: 9 },
      }),
    });
    const body = await response.json();

    expect(response.status).toBe(201);
    expect(body.cogId).toMatch(/^cog_/);
    const grace = body.snapshot.cogs.find((cog: { name: string }) => cog.name === "Grace");
    expect(grace?.spriteUrl).toBe("data:image/png;base64,abc");
    expect(grace?.spriteUrls).toEqual({
      red: "/assets/cogshambo/cogs/grace-red.png",
      blue: "/assets/cogshambo/cogs/grace-blue.png",
    });
  });

  it("assigns unique names to duplicate cogs through the API", async () => {
    const createGrace = () =>
      fetch(`${baseUrl}/api/cogs`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: "Grace",
          controllerId: "stub",
          color: "blue",
        }),
      });

    const firstResponse = await createGrace();
    const secondResponse = await createGrace();
    const body = await secondResponse.json();

    expect(firstResponse.status).toBe(201);
    expect(secondResponse.status).toBe(201);
    expect(body.snapshot.cogs.map((cog: { name: string }) => cog.name)).toEqual(
      expect.arrayContaining(["Grace", "Grace 2"]),
    );
  });

  it("shuffles every cog team through the API", async () => {
    const before = await fetch(`${baseUrl}/api/world`).then((response) => response.json());
    const beforeColors = new Map(before.cogs.map((cog: { id: string; color: string }) => [cog.id, cog.color]));

    const response = await fetch(`${baseUrl}/api/cogs/shuffle-teams`, {
      method: "POST",
    });
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.snapshot.cogs).toHaveLength(before.cogs.length);
    expect(body.snapshot.cogs.filter((cog: { color: string }) => cog.color === "red")).toHaveLength(5);
    expect(body.snapshot.cogs.filter((cog: { color: string }) => cog.color === "blue")).toHaveLength(5);
    expect(
      body.snapshot.cogs.some((cog: { id: string; color: string }) => cog.color !== beforeColors.get(cog.id)),
    ).toBe(true);
    for (const cog of body.snapshot.cogs as Array<{ id: string; color: string }>) {
      expect(["red", "blue"]).toContain(cog.color);
    }

    const reload = await fetch(`${baseUrl}/api/world`).then((worldResponse) => worldResponse.json());
    expect(reload.cogs.map((cog: { id: string; color: string }) => [cog.id, cog.color])).toEqual(
      body.snapshot.cogs.map((cog: { id: string; color: string }) => [cog.id, cog.color]),
    );
  });

  it("keeps abandon as a compatibility no-op through the API", async () => {
    const before = await fetch(`${baseUrl}/api/world`).then((response) => response.json());
    const cog = before.cogs[0] as { id: string; name: string };

    const response = await fetch(`${baseUrl}/api/cogs/${encodeURIComponent(cog.id)}/abandon`, {
      method: "POST",
    });
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.cogId).toBe(cog.id);
    expect(body.snapshot.cogs.some((candidate: { id: string }) => candidate.id === cog.id)).toBe(true);
    expect(body.snapshot.recentEvents).not.toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          actorId: cog.id,
          type: "abandon",
        }),
      ]),
    );

    const reload = await fetch(`${baseUrl}/api/world`).then((worldResponse) => worldResponse.json());
    expect(reload.cogs.some((candidate: { id: string }) => candidate.id === cog.id)).toBe(true);
  });

  it("kicks a cog home through the API and removes it from active snapshots", async () => {
    const before = await fetch(`${baseUrl}/api/world`).then((response) => response.json());
    const cog = before.cogs[0] as { id: string; name: string };

    const response = await fetch(`${baseUrl}/api/cogs/${encodeURIComponent(cog.id)}/kick`, {
      method: "POST",
    });
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.cogId).toBe(cog.id);
    expect(body.snapshot.cogs.some((candidate: { id: string }) => candidate.id === cog.id)).toBe(false);
    expect(body.snapshot.recentEvents).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          actorId: cog.id,
          message: `${cog.name} was kicked home`,
          type: "kick",
        }),
      ]),
    );

    const reload = await fetch(`${baseUrl}/api/world`).then((worldResponse) => worldResponse.json());
    expect(reload.cogs.some((candidate: { id: string }) => candidate.id === cog.id)).toBe(false);
  });

  it("generates cog sprites through the Nano Banana API", async () => {
    const response = await fetch(`${baseUrl}/api/cog-sprites`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        name: "Helix",
        description: "brass passionate cog with a teal glass eye",
        defensiveTrait: "stubborn",
        activeTrait: "passionate",
        personalGoal: "underdog",
        spriteRoll: 2,
        count: 5,
      }),
    });
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.source).toBe("nano-banana");
    expect(body.sprites).toHaveLength(5);
    expect(body.sprites[0]).toEqual({
      key: "generated-test-1",
      label: "Sprite 1",
      url: "/assets/cogshambo/cogs/generated-test-1.png",
      spriteUrls: {
        red: "/assets/cogshambo/cogs/generated-test-1-red.png",
        blue: "/assets/cogshambo/cogs/generated-test-1-blue.png",
      },
    });
    expect(generatedSpriteRequests).toEqual([
      expect.objectContaining({
        name: "Helix",
        description: "brass passionate cog with a teal glass eye",
        count: 5,
      }),
    ]);
  });

  it("updates cog profile prompt, attributes, and rule traits through the API", async () => {
    const world = await fetch(`${baseUrl}/api/world`).then((response) => response.json());
    const cogId = world.cogs.find((cog: { defensiveTrait: string }) => cog.defensiveTrait !== "zealot").id;

    const response = await fetch(`${baseUrl}/api/cogs/${encodeURIComponent(cogId)}/profile`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        name: "Renamed Cog",
        behaviorPrompt: "use rule traits",
        attributes: { focus: 9 },
        defensiveTrait: "iconoclast",
        activeTrait: "passionate",
        personalGoal: "underdog",
      }),
    });
    const body = await response.json();
    const updated = body.snapshot.cogs.find((cog: { id: string }) => cog.id === cogId);

    expect(response.status).toBe(200);
    expect(updated.name).toBe("Renamed Cog");
    expect(updated.behaviorPrompt).toBe("use rule traits");
    expect(updated.attributes.focus).toBe(9);
    expect(updated.defensiveTrait).toBe("iconoclast");
    expect(updated.activeTrait).toBe("passionate");
    expect(updated.personalGoal).toBe("underdog");
  });

  it("records a cog poke through the API", async () => {
    const world = await fetch(`${baseUrl}/api/world`).then((response) => response.json());
    const cogId = world.cogs[0].id;

    const response = await fetch(`${baseUrl}/api/cogs/${encodeURIComponent(cogId)}/poke`, {
      method: "POST",
    });
    const body = await response.json();

    expect(response.status).toBe(200);
    const event = body.snapshot.recentEvents.at(-1);
    expect(body.cogId).toBe(cogId);
    expect(event).toMatchObject({
      type: "poke",
      actorId: cogId,
    });
  });

  it("returns structured validation errors", async () => {
    const response = await fetch(`${baseUrl}/api/cogs`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "" }),
    });
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(body.error).toBe("Invalid create cog request");
    expect(body.issues).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          path: ["name"],
          message: expect.any(String),
        }),
      ]),
    );
  });

  it("returns structured validation errors for malformed JSON", async () => {
    const response = await fetch(`${baseUrl}/api/cogs`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{",
    });
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(response.headers.get("content-type")).toContain("application/json");
    expect(body.error).toBe("Invalid JSON request body");
    expect(body.issues).toEqual([
      expect.objectContaining({
        path: [],
        message: expect.any(String),
      }),
    ]);
  });

  it("returns structured domain errors for out-of-bounds cog positions", async () => {
    const response = await fetch(`${baseUrl}/api/cogs`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        name: "Boundary",
        spriteSheetKey: "cog-boundary",
        controllerId: "stub",
        attributes: { energy: 5 },
        position: { x: 50, y: 0 },
      }),
    });
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(body.error).toBe("Invalid create cog request");
    expect(body.issues).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          path: ["position"],
          message: expect.stringContaining("outside bounds"),
        }),
      ]),
    );
  });

  it("returns structured domain errors for occupied cog positions", async () => {
    const worldResponse = await fetch(`${baseUrl}/api/world`);
    const worldSnapshot = await worldResponse.json();
    const occupiedLocation = worldSnapshot.cogs[0].location;
    expect(occupiedLocation).toBeDefined();

    const response = await fetch(`${baseUrl}/api/cogs`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        name: "Crowded",
        spriteSheetKey: "cog-crowded",
        controllerId: "stub",
        attributes: { energy: 5 },
        location: occupiedLocation,
      }),
    });
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(body.error).toBe("Invalid create cog request");
    expect(body.issues).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          path: ["position"],
          message: expect.stringContaining("occupied"),
        }),
      ]),
    );
  });

  it("returns JSON 404 for unknown API routes", async () => {
    const response = await fetch(`${baseUrl}/api/missing`);
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body.error).toBe("Not found");
  });

  it("accepts simulation control commands", async () => {
    const pause = await fetch(`${baseUrl}/api/control`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ command: "pause" }),
    });
    const pauseBody = await pause.json();

    expect(pause.status).toBe(200);
    expect(pauseBody.status.simulationMode).toBe("paused");

    const step = await fetch(`${baseUrl}/api/control`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ command: "step" }),
    });
    const stepBody = await step.json();

    expect(step.status).toBe(200);
    expect(stepBody.status.simulationMode).toBe("paused");
    expect(stepBody.status.stepRequested).toBe(true);

    const play = await fetch(`${baseUrl}/api/control`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ command: "play" }),
    });
    const playBody = await play.json();

    expect(play.status).toBe(200);
    expect(playBody.status.simulationMode).toBe("playing");
  });

  it("returns structured validation errors for invalid control commands", async () => {
    const response = await fetch(`${baseUrl}/api/control`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ command: "rewind" }),
    });
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(body.error).toBe("Invalid control request");
    expect(body.issues).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          path: ["command"],
          message: expect.any(String),
        }),
      ]),
    );
  });
});

describe("WebSocket server", () => {
  it("terminates clients with backed-up send buffers", () => {
    const socket = {
      readyState: WebSocket.OPEN,
      bufferedAmount: MAX_WEBSOCKET_BUFFERED_BYTES + 1,
      send: vi.fn(),
      terminate: vi.fn(),
    } as unknown as WebSocket;

    expect(sendEncoded(socket, "{\"type\":\"serverStatus\"}")).toBe(false);
    expect(socket.send).not.toHaveBeenCalled();
    expect(socket.terminate).toHaveBeenCalledTimes(1);
  });

  it("sends compact snapshots to new clients", async () => {
    const world = createSeedWorld();
    for (const cog of world.snapshot().cogs) {
      for (let index = 0; index < CLIENT_COG_CONVERSATION_LOG_LIMIT + 5; index += 1) {
        world.recordCogConversation(cog.id, [{ role: "assistant", content: `message ${index}` }]);
      }
    }
    const wsHttpServer = createServer();
    const socketServer = attachWorldSocketServer({
      server: wsHttpServer,
      world,
      controllers: createControllerRegistry(),
      controls: createSimulationControls(),
      tickMs: 1_000,
    });
    await new Promise<void>((resolve) => wsHttpServer.listen(0, resolve));
    const address = wsHttpServer.address() as AddressInfo;
    const socket = new WebSocket(`ws://127.0.0.1:${address.port}/ws`);

    try {
      const snapshot = await waitForSnapshot(socket);

      expect(snapshot.cogs.every((cog) => cog.conversationLog.length <= CLIENT_COG_CONVERSATION_LOG_LIMIT)).toBe(
        true,
      );
      expect(world.snapshot().cogs.every((cog) => cog.conversationLog.length > CLIENT_COG_CONVERSATION_LOG_LIMIT)).toBe(
        true,
      );
    } finally {
      socket.close();
      await socketServer.close();
      await new Promise<void>((resolve) => {
        wsHttpServer.close(() => resolve());
      });
    }
  });

  it("serializes slow simulation ticks and closes active clients", async () => {
    const world = createSeedWorld();
    let activeDecisions = 0;
    let maxActiveDecisions = 0;
    let decisions = 0;
    const slowController = {
      async decide(): Promise<CogAction> {
        decisions += 1;
        activeDecisions += 1;
        maxActiveDecisions = Math.max(maxActiveDecisions, activeDecisions);
        await delay(40);
        activeDecisions -= 1;
        return { type: "wait", intent: "slow" };
      },
    };
    const controllers: ControllerRegistry = {
      stub: slowController,
      wander: slowController,
      llm: slowController,
    };
    const wsHttpServer = createServer();
    const socketServer = attachWorldSocketServer({
      server: wsHttpServer,
      world,
      controllers,
      controls: createSimulationControls(),
      tickMs: 5,
    });
    await new Promise<void>((resolve) => wsHttpServer.listen(0, resolve));
    const address = wsHttpServer.address() as AddressInfo;
    const socket = new WebSocket(`ws://127.0.0.1:${address.port}/ws`);
    let closed = false;
    let messagesAfterClose = 0;
    socket.on("message", () => {
      if (closed) {
        messagesAfterClose += 1;
      }
    });

    try {
      await once(socket, "open");
      await delay(90);

      expect(decisions).toBeGreaterThan(0);
      expect(maxActiveDecisions).toBeGreaterThanOrEqual(1);
      expect(maxActiveDecisions).toBeLessThanOrEqual(10);

      const closePromise = once(socket, "close");
      closed = true;
      await socketServer.close();
      messagesAfterClose = 0;
      socketServer.broadcast({ type: "snapshot", snapshot: world.snapshot() });
      await closePromise;
      await delay(10);
      expect(socketServer.clientCount()).toBe(0);
      expect(messagesAfterClose).toBe(0);
    } finally {
      await socketServer.close();

      await new Promise<void>((resolve) => {
        wsHttpServer.close(() => resolve());
      });
    }
  });

  it("does not step the world when closed during an active controller decision", async () => {
    const world = createSeedWorld();
    const decisionStarted = deferred<void>();
    const releaseDecisions = deferred<void>();
    const slowController = {
      async decide(): Promise<CogAction> {
        decisionStarted.resolve();
        await releaseDecisions.promise;
        return { type: "wait", intent: "released after close" };
      },
    };
    const controllers: ControllerRegistry = {
      stub: slowController,
      wander: slowController,
      llm: slowController,
    };
    const wsHttpServer = createServer();
    const socketServer = attachWorldSocketServer({
      server: wsHttpServer,
      world,
      controllers,
      controls: createSimulationControls(),
      tickMs: 5,
    });
    await new Promise<void>((resolve) => wsHttpServer.listen(0, resolve));

    try {
      await decisionStarted.promise;
      const closePromise = socketServer.close();
      releaseDecisions.resolve();
      await closePromise;
      await delay(20);

      expect(world.snapshot().tick).toBe(0);
    } finally {
      releaseDecisions.resolve();
      await socketServer.close();

      await new Promise<void>((resolve) => {
        wsHttpServer.close(() => resolve());
      });
    }
  });

  it("pauses, steps once, and resumes the authoritative tick loop", async () => {
    const world = createSeedWorld();
    const controls = createSimulationControls();
    const controllers = createControllerRegistry({ scriptLlm: true });
    const wsHttpServer = createServer();
    const socketServer = attachWorldSocketServer({ server: wsHttpServer, world, controllers, controls, tickMs: 10 });
    await new Promise<void>((resolve) => wsHttpServer.listen(0, resolve));

    try {
      await delay(35);
      expect(world.snapshot().tick).toBeGreaterThan(0);

      controls.pause();
      const pausedTick = world.snapshot().tick;
      await delay(35);
      expect(world.snapshot().tick).toBe(pausedTick);

      controls.step();
      await delay(25);
      expect(world.snapshot().tick).toBe(pausedTick + 1);

      await delay(25);
      expect(world.snapshot().tick).toBe(pausedTick + 1);

      controls.play();
      await delay(35);
      expect(world.snapshot().tick).toBeGreaterThan(pausedTick + 1);
    } finally {
      await socketServer.close();

      await new Promise<void>((resolve) => {
        wsHttpServer.close(() => resolve());
      });
    }
  });

  it("applies manual move messages on the authoritative tick path while paused", async () => {
    const world = createSeedWorld();
    const controls = createSimulationControls("paused");
    const controllers = createControllerRegistry({ scriptLlm: true });
    const wsHttpServer = createServer();
    const socketServer = attachWorldSocketServer({ server: wsHttpServer, world, controllers, controls, tickMs: 10 });
    await new Promise<void>((resolve) => wsHttpServer.listen(0, resolve));
    const address = wsHttpServer.address() as AddressInfo;
    const socket = new WebSocket(`ws://127.0.0.1:${address.port}/ws`);
    const initialSnapshot = waitForSnapshot(socket);

    try {
      await once(socket, "open");
      const initial = await initialSnapshot;
      const babbage = initial.cogs.find((cog) => cog.name === "Babbage");
      if (!babbage) {
        throw new Error("Expected Babbage in seed world");
      }

      socket.send(JSON.stringify({ type: "manualMove", cogId: babbage.id, direction: "west" }));
      const moving = await waitForSnapshot(
        socket,
        (snapshot) => snapshot.cogs.find((cog) => cog.id === babbage.id)?.moving?.to.roomId === "proscenium_apron",
      );

      const movingBabbage = moving.cogs.find((cog) => cog.id === babbage.id);
      expect(moving.tick).toBe(initial.tick + 1);
      expect(movingBabbage?.location).toBeUndefined();
      expect(movingBabbage?.moving?.to).toEqual({ roomId: "proscenium_apron", spotId: "apron_left" });
      expect(movingBabbage?.moving?.toPosition).toEqual({
        x: 42,
        y: 9,
      });
      expect(movingBabbage?.position).toEqual(babbage.position);
    } finally {
      socket.close();
      await socketServer.close();

      await new Promise<void>((resolve) => {
        wsHttpServer.close(() => resolve());
      });
    }
  });

  it("applies manual room action messages on the authoritative tick path while paused", async () => {
    const world = createSeedWorld();
    const controls = createSimulationControls("paused");
    const controllers = createControllerRegistry({ scriptLlm: true });
    const wsHttpServer = createServer();
    const socketServer = attachWorldSocketServer({ server: wsHttpServer, world, controllers, controls, tickMs: 10 });
    await new Promise<void>((resolve) => wsHttpServer.listen(0, resolve));
    const address = wsHttpServer.address() as AddressInfo;
    const socket = new WebSocket(`ws://127.0.0.1:${address.port}/ws`);
    const initialSnapshot = waitForSnapshot(socket);

    try {
      await once(socket, "open");
      const initial = await initialSnapshot;
      const babbage = initial.cogs.find((cog) => cog.name === "Babbage");
      if (!babbage) {
        throw new Error("Expected Babbage in seed world");
      }

      socket.send(JSON.stringify({ type: "manualAction", cogId: babbage.id, action: { type: "move", roomId: "green_room" } }));
      const moving = await waitForSnapshot(
        socket,
        (snapshot) => snapshot.cogs.find((cog) => cog.id === babbage.id)?.moving?.to.roomId === "green_room",
      );

      const movingBabbage = moving.cogs.find((cog) => cog.id === babbage.id);
      expect(moving.tick).toBe(initial.tick + 1);
      expect(movingBabbage?.location).toBeUndefined();
      expect(movingBabbage?.moving?.to.roomId).toBe("green_room");
    } finally {
      socket.close();
      await socketServer.close();

      await new Promise<void>((resolve) => {
        wsHttpServer.close(() => resolve());
      });
    }
  });

  it("ignores manual debate-exit messages while a cog is debating", async () => {
    const world = new GridWorld({ width: 8, height: 8 });
    const red = world.addCog({ name: "Red", color: "red", controllerId: "stub", position: { x: 2, y: 2 } });
    const blue = world.addCog({ name: "Blue", color: "blue", controllerId: "stub", position: { x: 3, y: 2 } });
    await world.step(new Map<string, CogAction>([[red.id, { type: "debate", targetId: blue.id }]]));
    expect(world.snapshot().cogs.find((cog) => cog.id === red.id)?.debate).toEqual(
      expect.objectContaining({ opponentId: blue.id }),
    );

    const controls = createSimulationControls("paused");
    const controllers = createControllerRegistry({ scriptLlm: true });
    const wsHttpServer = createServer();
    const socketServer = attachWorldSocketServer({ server: wsHttpServer, world, controllers, controls, tickMs: 10 });
    await new Promise<void>((resolve) => wsHttpServer.listen(0, resolve));
    const address = wsHttpServer.address() as AddressInfo;
    const socket = new WebSocket(`ws://127.0.0.1:${address.port}/ws`);
    const initialSnapshot = waitForSnapshot(socket);

    try {
      await once(socket, "open");
      await initialSnapshot;

      socket.send(JSON.stringify({ type: "manualTalkToTheHand", cogId: red.id }));
      await delay(30);
      const resolved = world.snapshot();

      expect(resolved.cogs.find((cog) => cog.id === red.id)?.debate?.opponentId).toBe(blue.id);
      expect(resolved.cogs.find((cog) => cog.id === blue.id)?.debate?.opponentId).toBe(red.id);
    } finally {
      socket.close();
      await socketServer.close();

      await new Promise<void>((resolve) => {
        wsHttpServer.close(() => resolve());
      });
    }
  });

  it("records per-cog controller conversations", async () => {
    const world = createSeedWorld();
    const controllers = createControllerRegistry({ scriptLlm: true });
    const wsHttpServer = createServer();
    const socketServer = attachWorldSocketServer({
      server: wsHttpServer,
      world,
      controllers,
      controls: createSimulationControls(),
      tickMs: 10,
    });
    await new Promise<void>((resolve) => wsHttpServer.listen(0, resolve));

    try {
      const cog = await waitForFirstCogWithConversation(world);

      expect(cog.conversationLog).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            role: "user",
            content: expect.stringContaining(`Your name is ${cog.name}`),
          }),
          expect.objectContaining({
            role: "user",
            content: expect.stringContaining("Instructions:"),
          }),
          expect.objectContaining({
            role: "user",
            content: expect.stringContaining("Pick an action:"),
          }),
          expect.objectContaining({
            role: "assistant",
            content: expect.stringContaining('"type"'),
          }),
        ]),
      );
    } finally {
      await socketServer.close();

      await new Promise<void>((resolve) => {
        wsHttpServer.close(() => resolve());
      });
    }
  });

  it("keeps broadcasting ticks when world state persistence is locked", async () => {
    const world = new GridWorld({ width: 6, height: 6 });
    world.addCog({ name: "Ada", color: "red", controllerId: "stub", position: { x: 2, y: 2 } });
    const failingWorldStateStore: WorldStateStore = {
      load: () => undefined,
      save: () => {
        throw Object.assign(new Error("database is locked"), {
          code: "ERR_SQLITE_ERROR",
          errcode: 5,
          errstr: "database is locked",
        });
      },
      close: () => undefined,
    };
    const wsHttpServer = createServer();
    const socketServer = attachWorldSocketServer({
      server: wsHttpServer,
      world,
      controllers: createControllerRegistry({ scriptLlm: true }),
      controls: createSimulationControls(),
      worldStateStore: failingWorldStateStore,
      tickMs: 10,
    });
    await new Promise<void>((resolve) => wsHttpServer.listen(0, resolve));
    const address = wsHttpServer.address() as AddressInfo;
    const socket = new WebSocket(`ws://127.0.0.1:${address.port}/ws`);
    const advancedSnapshot = waitForSnapshot(socket, (snapshot) => snapshot.tick > 0);
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);

    try {
      await once(socket, "open");

      await expect(advancedSnapshot).resolves.toEqual(expect.objectContaining({ tick: expect.any(Number) }));
    } finally {
      consoleError.mockRestore();
      socket.close();
      await socketServer.close();

      await new Promise<void>((resolve) => {
        wsHttpServer.close(() => resolve());
      });
    }
  });
});

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForFirstCogWithConversation(world: GridWorld): Promise<WorldSnapshot["cogs"][number]> {
  const deadline = Date.now() + 1_000;
  while (Date.now() < deadline) {
    const cog = world.snapshot().cogs[0];
    if (cog && cog.conversationLog.length > 0) {
      return cog;
    }
    await delay(10);
  }
  throw new Error("Timed out waiting for controller conversation");
}

function once(socket: WebSocket, eventName: "open" | "close"): Promise<void> {
  return new Promise((resolve, reject) => {
    socket.once(eventName, () => resolve());
    socket.once("error", reject);
  });
}

function waitForSnapshot(
  socket: WebSocket,
  predicate: (snapshot: WorldSnapshot) => boolean = () => true,
): Promise<WorldSnapshot> {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      cleanup();
      reject(new Error("Timed out waiting for snapshot"));
    }, 1_000);
    const onMessage = (data: WebSocket.RawData): void => {
      try {
        const message = JSON.parse(data.toString()) as { type?: string; snapshot?: WorldSnapshot };
        if (message.type === "snapshot" && message.snapshot && predicate(message.snapshot)) {
          cleanup();
          resolve(message.snapshot);
        }
      } catch {
        // Ignore malformed test messages.
      }
    };
    const cleanup = (): void => {
      clearTimeout(timeout);
      socket.off("message", onMessage);
    };
    socket.on("message", onMessage);
  });
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T | PromiseLike<T>) => void } {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((innerResolve) => {
    resolve = innerResolve;
  });
  return { promise, resolve };
}
