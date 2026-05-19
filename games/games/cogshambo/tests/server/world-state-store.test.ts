import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { startCogshamboServer, type RunningCogshamboServer } from "../../src/server/runtime.js";
import { createSeedWorld } from "../../src/server/simulation/seed-world.js";
import { GridWorld } from "../../src/server/simulation/world.js";
import { createSqliteWorldStateStore } from "../../src/server/world-state-store.js";
import type { CogAction, VenueLayout, WorldObject } from "../../src/shared/types.js";

let servers: RunningCogshamboServer[] = [];

afterEach(async () => {
  await Promise.all(servers.map((server) => server.close()));
  servers = [];
});

describe("world state persistence", () => {
  it("round-trips the full GridWorld state including venue location and movement", async () => {
    const world = new GridWorld({ width: 10, height: 4 }, { debateDoubt: 37 }, testVenue());
    const ada = world.addCog({
      name: "Ada",
      behaviorPrompt: "persist me",
      controllerId: "stub",
      color: "red",
      defensiveTrait: "stubborn",
      activeTrait: "avenger",
      attributes: { focus: 9 },
      location: { roomId: "room-a", spotId: "room-a-left" },
    });
    const blue = world.addCog({
      name: "Blue",
      controllerId: "stub",
      color: "blue",
      location: { roomId: "room-a", spotId: "room-a-right" },
    });

    await world.step(new Map<string, CogAction>([[ada.id, { type: "move", roomId: "room-b", intent: "relocate" }]]));
    world.recordCogConversation(ada.id, [
      { role: "user", content: "where are you" },
      { role: "assistant", content: "moving to room-b" },
    ]);

    const restored = GridWorld.fromState(world.exportState());

    expect(restored.snapshot()).toEqual(world.snapshot());
    expect(restored.gameConfig().debateDoubt).toBe(37);
    expect(restored.snapshot().cogs.find((cog) => cog.id === blue.id)?.location).toEqual({
      roomId: "room-a",
      spotId: "room-a-right",
    });
    expect(restored.snapshot().cogs.find((cog) => cog.id === ada.id)?.moving?.to).toEqual({
      roomId: "room-b",
      spotId: "room-b-left",
    });
  });

  it("reloads the exact saved world from sqlite", async () => {
    const tempDir = mkdtempSync(path.join(tmpdir(), "cogshambo-world-"));
    const dbPath = path.join(tempDir, "cogshambo.sqlite");
    const world = createSeedWorld({ debateDoubt: 29 });
    const ada = world.snapshot().cogs.find((cog) => cog.name === "Ada");
    if (!ada) {
      throw new Error("Expected Ada in seed world");
    }
    await world.step(new Map<string, CogAction>([[ada.id, { type: "move", roomId: "green_room" }]]));

    const store = createSqliteWorldStateStore(dbPath);
    store.save(world);
    store.close();

    const reloaded = createSqliteWorldStateStore(dbPath);
    const restored = reloaded.load();

    expect(restored?.snapshot()).toEqual(world.snapshot());
    expect(restored?.gameConfig().debateDoubt).toBe(29);

    reloaded.close();
    rmSync(tempDir, { recursive: true, force: true });
  });

  it("drops legacy speech and doubt state while restoring old snapshots", () => {
    const world = new GridWorld({ width: 6, height: 6 });
    const cog = world.addCog({ name: "Legacy", color: "red", position: { x: 1, y: 1 } });
    const state = world.exportState() as unknown as ReturnType<GridWorld["exportState"]> & {
      cogs: Array<
        ReturnType<GridWorld["snapshot"]>["cogs"][number] & {
          ticksAlive?: number;
          doubt?: { red: number; blue: number };
          speech?: { text: string; expiresAtTick: number };
        }
      >;
    };
    state.tick = 17;
    state.cogs[0] = {
      ...state.cogs[0],
      doubt: { red: 0, blue: 12 },
      speech: { text: "old bubble", expiresAtTick: 10 },
      achievements: [
        { assignmentId: "legacy-speech", achievementId: "firstSpeech", assignedTick: 0, timeoutTick: 20 },
        { assignmentId: "debate-three", achievementId: "debateThreeCogs", assignedTick: 0, timeoutTick: 20 },
        {
          assignmentId: "legacy-reasoner-beat",
          achievementId: "beatTrait",
          parameters: { trait: "reasoner" },
          assignedTick: 0,
          timeoutTick: 20,
        },
      ],
      completedAchievements: [
        {
          assignmentId: "legacy-long-speech",
          achievementId: "longSpeech",
          assignedTick: 0,
          timeoutTick: 20,
          completedTick: 1,
          points: 10,
        },
        {
          assignmentId: "legacy-reasoner-hunter",
          achievementId: "traitHunter",
          parameters: { trait: "reasoner" },
          assignedTick: 0,
          timeoutTick: 20,
          completedTick: 2,
          points: 25,
        },
      ],
      failedAchievements: [
        {
          assignmentId: "legacy-reasoner-nemesis",
          achievementId: "traitNemesis",
          parameters: { trait: "reasoner" },
          assignedTick: 0,
          timeoutTick: 20,
          failedTick: 3,
        },
      ],
    } as typeof state.cogs[number];
    delete state.cogs[0].ticksAlive;
    state.recentEvents.push({
      id: "legacy-speech-event",
      tick: 1,
      type: "speech",
      actorId: cog.id,
      message: "Legacy: old bubble",
      position: { x: 1, y: 1 },
    } as (typeof state.recentEvents)[number]);
    state.achievementCounts = [
      { achievementId: "firstSpeech", assigned: 1, completed: 0, current: 1, expired: 0 },
      { achievementId: "debateThreeCogs", assigned: 1, completed: 0, current: 1, expired: 0 },
      {
        achievementId: "beatTrait",
        parameters: { trait: "reasoner" },
        assigned: 1,
        completed: 0,
        current: 1,
        expired: 0,
      },
    ] as typeof state.achievementCounts;

    const snapshot = GridWorld.fromState(state).snapshot();
    const restoredCog = snapshot.cogs.find((candidate) => candidate.id === cog.id);

    expect(restoredCog).not.toHaveProperty("speech");
    expect(restoredCog).not.toHaveProperty("doubt");
    expect(restoredCog?.achievements.map((achievement) => achievement.achievementId)).toEqual(["debateThreeCogs", "beatTrait"]);
    expect(restoredCog?.achievements.find((achievement) => achievement.achievementId === "beatTrait")?.parameters?.trait).toBe(
      "rationalist",
    );
    expect(restoredCog?.completedAchievements.map((achievement) => achievement.parameters?.trait)).toEqual(["rationalist"]);
    expect(restoredCog?.failedAchievements.map((achievement) => achievement.parameters?.trait)).toEqual(["rationalist"]);
    expect(restoredCog?.ticksAlive).toBe(17);
    expect(snapshot.recentEvents.map((event) => event.type)).not.toContain("speech");
    expect(snapshot.achievementCounts.map((count) => count.achievementId)).toEqual(
      expect.arrayContaining(["debateThreeCogs", "beatTrait", "traitHunter", "traitNemesis"]),
    );
    expect(snapshot.achievementCounts.find((count) => count.achievementId === "beatTrait")?.parameters?.trait).toBe(
      "rationalist",
    );
    expect(snapshot.achievementCounts.map((count) => count.parameters?.trait).filter(Boolean)).not.toContain("reasoner");
  });

  it("drops retired map objects while restoring old snapshots", () => {
    const world = new GridWorld({ width: 6, height: 6 });
    const state = world.exportState() as unknown as ReturnType<GridWorld["exportState"]> & {
      objects: Array<WorldObject & { type: string }>;
    };
    state.objects = [
      {
        id: "retired-map-object",
        type: "retired-object",
        position: { x: 1, y: 1 },
        spriteKey: "map-object-marker",
        attributes: {},
      },
      {
        id: "bench-object",
        type: "bench",
        position: { x: 2, y: 2 },
        spriteKey: "map-object-marker",
        attributes: {},
      },
    ];

    expect(GridWorld.fromState(state).snapshot().objects.map((object) => object.id)).toEqual(["bench-object"]);
  });

  it("normalizes legacy reasoner traits while restoring old snapshots", async () => {
    const world = new GridWorld({ width: 6, height: 6 });
    const cog = world.addCog({ name: "Legacy", color: "red", position: { x: 1, y: 1 }, activeTrait: "rationalist" });
    const state = world.exportState() as unknown as ReturnType<GridWorld["exportState"]> & {
      cogs: Array<ReturnType<GridWorld["snapshot"]>["cogs"][number] & { activeTrait: string }>;
    };
    state.cogs[0] = { ...state.cogs[0]!, activeTrait: "reasoner" };

    const restored = GridWorld.fromState(state);
    const restoredCog = restored.snapshot().cogs.find((candidate) => candidate.id === cog.id);

    expect(restoredCog?.activeTrait).toBe("rationalist");
    await expect(restored.step(new Map([[cog.id, { type: "wait" }]]))).resolves.toBeTruthy();
  });

  it("loads persisted sqlite state when the server restarts", async () => {
    const tempDir = mkdtempSync(path.join(tmpdir(), "cogshambo-runtime-"));
    const dbPath = path.join(tempDir, "cogshambo.sqlite");
    const world = createSeedWorld({ debateDoubt: 41 });
    const ada = world.snapshot().cogs.find((cog) => cog.name === "Ada");
    if (!ada) {
      throw new Error("Expected Ada in seed world");
    }
    await world.step(new Map<string, CogAction>([[ada.id, { type: "move", roomId: "green_room" }]]));
    const expected = JSON.parse(JSON.stringify(world.snapshot()));

    const store = createSqliteWorldStateStore(dbPath);
    store.save(world);
    store.close();

    const server = await startCogshamboServer({ port: 0, tickMs: 60_000, sqlitePath: dbPath, scripted: true });
    servers.push(server);

    const body = await fetch(`${server.url}/api/world`).then((response) => response.json());

    expect(withoutVenue(body)).toEqual(withoutVenue(expected));

    await server.close();
    servers = servers.filter((running) => running !== server);
    rmSync(tempDir, { recursive: true, force: true });
  });

  it("persists HTTP world mutations across a server restart", async () => {
    const tempDir = mkdtempSync(path.join(tmpdir(), "cogshambo-http-world-"));
    const dbPath = path.join(tempDir, "cogshambo.sqlite");
    const firstServer = await startCogshamboServer({ port: 0, tickMs: 60_000, sqlitePath: dbPath, scripted: true });
    servers.push(firstServer);

    const createResponse = await fetch(`${firstServer.url}/api/cogs`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        name: "Persisted",
        controllerId: "stub",
        color: "blue",
      }),
    });
    const createBody = await createResponse.json();

    expect(createResponse.status).toBe(201);
    await firstServer.close();
    servers = servers.filter((server) => server !== firstServer);

    const secondServer = await startCogshamboServer({ port: 0, tickMs: 60_000, sqlitePath: dbPath, scripted: true });
    servers.push(secondServer);
    const reloaded = await fetch(`${secondServer.url}/api/world`).then((response) => response.json());

    expect(reloaded).toEqual(createBody.snapshot);
    expect(reloaded.cogs.find((cog: { name: string }) => cog.name === "Persisted")?.location).toBeDefined();

    await secondServer.close();
    servers = servers.filter((server) => server !== secondServer);
    rmSync(tempDir, { recursive: true, force: true });
  });

  it("allows only one running server per sqlite database", async () => {
    const tempDir = mkdtempSync(path.join(tmpdir(), "cogshambo-single-db-"));
    const dbPath = path.join(tempDir, "cogshambo.sqlite");
    const firstServer = await startCogshamboServer({ port: 0, tickMs: 60_000, sqlitePath: dbPath, scripted: true });
    servers.push(firstServer);

    await expect(startCogshamboServer({ port: 0, tickMs: 60_000, sqlitePath: dbPath, scripted: true })).rejects.toThrow(
      /already running for sqlite database/,
    );

    await firstServer.close();
    servers = servers.filter((server) => server !== firstServer);
    const secondServer = await startCogshamboServer({ port: 0, tickMs: 60_000, sqlitePath: dbPath, scripted: true });
    servers.push(secondServer);

    expect((await fetch(`${secondServer.url}/health`)).status).toBe(200);

    await secondServer.close();
    servers = servers.filter((server) => server !== secondServer);
    rmSync(tempDir, { recursive: true, force: true });
  });
});

function withoutVenue<T extends { venue?: unknown }>(snapshot: T): Omit<T, "venue"> {
  const { venue: _venue, ...rest } = snapshot;
  return rest;
}

function testVenue(): VenueLayout {
  return {
    rooms: [
      {
        id: "room-a",
        label: "Room A",
        kind: "walkway",
        spotIds: ["room-a-left", "room-a-right"],
        neighborIds: ["room-b"],
      },
      {
        id: "room-b",
        label: "Room B",
        kind: "walkway",
        spotIds: ["room-b-left", "room-b-right"],
        neighborIds: ["room-a"],
      },
    ],
    spots: [
      { id: "room-a-left", roomId: "room-a", label: "left", position: { x: 1, y: 1 } },
      { id: "room-a-right", roomId: "room-a", label: "right", position: { x: 2, y: 1 } },
      { id: "room-b-left", roomId: "room-b", label: "left", position: { x: 7, y: 1 } },
      { id: "room-b-right", roomId: "room-b", label: "right", position: { x: 8, y: 1 } },
    ],
    spotLinks: [
      { id: "room-a-link", fromSpotId: "room-a-left", toSpotId: "room-a-right" },
      { id: "room-b-link", fromSpotId: "room-b-left", toSpotId: "room-b-right" },
    ],
  };
}
