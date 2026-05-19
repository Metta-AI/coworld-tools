import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createServer } from "node:http";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import type { AddressInfo } from "node:net";

import { createApp } from "../../src/server/http.js";
import { createControllerRegistry } from "../../src/server/controllers/cog-controller.js";
import { createSimulationControls } from "../../src/server/simulation/control.js";
import { createSeedWorld } from "../../src/server/simulation/seed-world.js";
import { createSqliteSettingsStore, type SettingsStore } from "../../src/server/settings-store.js";
import { createJsonVenueEditorStore, type VenueEditorStore } from "../../src/server/venue-editor-store.js";
import { readDefaultVenueGraphFile } from "../../src/server/venue-graph.js";

let server: ReturnType<typeof createServer>;
let baseUrl: string;
let tempDir: string;
let store: VenueEditorStore;
let settingsStore: SettingsStore;

beforeEach(async () => {
  tempDir = mkdtempSync(path.join(tmpdir(), "cogshambo-venue-editor-"));
  settingsStore = createSqliteSettingsStore(":memory:");
  store = createJsonVenueEditorStore(path.join(tempDir, "venue-graph.json"));
  const app = createApp({
    world: createSeedWorld(),
    controllers: createControllerRegistry(),
    controls: createSimulationControls(),
    settingsStore,
    venueEditorStore: store,
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
  store.close();
  rmSync(tempDir, { recursive: true, force: true });
});

describe("venue editor API", () => {
  it("uses the tracked venue editor layout as the default venue graph", () => {
    const graph = readDefaultVenueGraphFile();

    expect(graph.rooms).toHaveLength(29);
    expect(graph.paths).toHaveLength(65);
    expect(graph.paths).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ id: "lobby_bar_queue__new_room", fromRoomId: "lobby_bar_queue", toRoomId: "new_room" }),
        expect.objectContaining({ id: "green_room__proscenium_apron", fromRoomId: "green_room", toRoomId: "proscenium_apron" }),
        expect.objectContaining({ id: "proscenium_apron__south_alley", fromRoomId: "proscenium_apron", toRoomId: "south_alley" }),
      ]),
    );
  });

  it("seeds the editor from the current venue image and spots", async () => {
    const response = await fetch(`${baseUrl}/api/venue-editor`);
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.state.imageUrl).toBe("/assets/cogshambo/venue/gray-area-floor-plan.png");
    expect(body.state.dimensions).toEqual({ width: 50, height: 28 });
    expect(body.state.rooms).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: "stage",
          label: "Main Stage",
          rect: expect.objectContaining({ width: expect.any(Number), height: expect.any(Number) }),
          spotIds: expect.arrayContaining(["stage_host"]),
        }),
      ]),
    );
    const stageHost = body.state.spots.find((spot: { id: string }) => spot.id === "stage_host");
    expect(stageHost).toMatchObject({ id: "stage_host", roomId: "stage" });
    expect(stageHost.position.x).toBeCloseTo(44.1);
    expect(stageHost.position.y).toBeCloseTo(13.5);
    expect(body.state.links).toEqual([]);
    expect(body.state.paths).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ id: "green_room__stage", fromRoomId: "green_room", toRoomId: "stage" }),
      ]),
    );
  });

  it("persists saved spots, room rectangles, and room paths to JSON while stripping legacy links", async () => {
    const initial = await fetch(`${baseUrl}/api/venue-editor`).then((response) => response.json());
    const state = {
      ...initial.state,
      rooms: initial.state.rooms.map((room: { id: string }) =>
        room.id === "stage" ? { ...room, rect: { x: 43, y: 11, width: 5, height: 8 } } : room,
      ),
      spots: initial.state.spots.map((spot: { id: string; position: { x: number; y: number } }) =>
        spot.id === "stage_host" ? { ...spot, position: { x: 45, y: 12 } } : spot,
      ),
      links: [{ id: "stage_host__stage_guest", fromSpotId: "stage_host", toSpotId: "stage_guest" }],
      paths: [{ id: "green_room__stage", fromRoomId: "green_room", toRoomId: "stage", points: [{ x: 45, y: 9 }] }],
    };

    const saveResponse = await fetch(`${baseUrl}/api/venue-editor`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(state),
    });
    const saveBody = await saveResponse.json();
    const reloadBody = await fetch(`${baseUrl}/api/venue-editor`).then((response) => response.json());

    expect(saveResponse.status).toBe(200);
    expect(saveBody.state.updatedAt).toEqual(expect.any(String));
    expect(reloadBody.state.spots.find((spot: { id: string }) => spot.id === "stage_host").position).toEqual({
      x: 45,
      y: 12,
    });
    expect(reloadBody.state.links).toEqual([]);
    expect(reloadBody.state.rooms.find((room: { id: string }) => room.id === "stage").rect).toEqual({
      x: 43,
      y: 11,
      width: 5,
      height: 8,
    });
    expect(reloadBody.state.paths).toEqual([
      { id: "green_room__stage", fromRoomId: "green_room", toRoomId: "stage", points: [{ x: 45, y: 9 }] },
    ]);
  });

  it("applies saved venue spots to the live world", async () => {
    const initialVenue = await fetch(`${baseUrl}/api/venue-editor`).then((response) => response.json());
    const initialWorld = await fetch(`${baseUrl}/api/world`).then((response) => response.json());
    const cog = initialWorld.cogs.find((candidate: { location?: { roomId: string; spotId: string } }) => candidate.location);
    if (!cog?.location) {
      throw new Error("Expected a venue cog in the seeded world");
    }
    const newPosition = { x: cog.position.x + 0.4, y: cog.position.y + 0.6 };
    const state = {
      ...initialVenue.state,
      spots: initialVenue.state.spots.map((spot: { id: string; roomId?: string }) =>
        spot.id === cog.location.spotId && spot.roomId === cog.location.roomId
          ? { ...spot, position: newPosition }
          : spot,
      ),
    };

    const saveResponse = await fetch(`${baseUrl}/api/venue-editor`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(state),
    });
    const worldBody = await fetch(`${baseUrl}/api/world`).then((response) => response.json());
    const updatedCog = worldBody.cogs.find((candidate: { id: string }) => candidate.id === cog.id);
    const updatedSpot = worldBody.venue.spots.find(
      (spot: { id: string; roomId?: string }) => spot.id === cog.location.spotId && spot.roomId === cog.location.roomId,
    );

    expect(saveResponse.status).toBe(200);
    expect(updatedSpot.position).toEqual(newPosition);
    expect(updatedCog.position).toEqual(newPosition);
  });

  it("keeps a dragged spot assigned to the same room after saving new coordinates", async () => {
    const initialVenue = await fetch(`${baseUrl}/api/venue-editor`).then((response) => response.json());
    const draggedPosition = { x: 8, y: 13 };
    const state = {
      ...initialVenue.state,
      spots: initialVenue.state.spots.map((spot: { id: string; roomId?: string }) =>
        spot.id === "stage_host" && spot.roomId === "stage"
          ? { ...spot, position: draggedPosition }
          : spot,
      ),
    };

    const saveResponse = await fetch(`${baseUrl}/api/venue-editor`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(state),
    });
    const saveBody = await saveResponse.json();

    expect(saveResponse.status).toBe(200);
    expect(saveBody.state.spots.find((spot: { id: string }) => spot.id === "stage_host")).toEqual(
      expect.objectContaining({
        roomId: "stage",
        position: draggedPosition,
      }),
    );
    expect(saveBody.state.rooms.find((room: { id: string }) => room.id === "stage").spotIds).toContain("stage_host");
  });

  it("applies persisted venue editor state when the server starts", async () => {
    const initialVenue = await fetch(`${baseUrl}/api/venue-editor`).then((response) => response.json());
    const initialWorld = await fetch(`${baseUrl}/api/world`).then((response) => response.json());
    const cog = initialWorld.cogs.find((candidate: { location?: { roomId: string; spotId: string } }) => candidate.location);
    if (!cog?.location) {
      throw new Error("Expected a venue cog in the seeded world");
    }
    const newPosition = { x: cog.position.x + 0.8, y: cog.position.y + 0.2 };
    store.save({
      ...initialVenue.state,
      spots: initialVenue.state.spots.map((spot: { id: string; roomId?: string }) =>
        spot.id === cog.location.spotId && spot.roomId === cog.location.roomId
          ? { ...spot, position: newPosition }
          : spot,
      ),
    });

    await new Promise<void>((resolve, reject) => {
      server.close((error) => (error ? reject(error) : resolve()));
    });
    const app = createApp({
      world: createSeedWorld(),
      controllers: createControllerRegistry(),
      controls: createSimulationControls(),
      settingsStore,
      venueEditorStore: store,
    });
    server = createServer(app);
    await new Promise<void>((resolve) => server.listen(0, resolve));
    const address = server.address() as AddressInfo;
    baseUrl = `http://127.0.0.1:${address.port}`;

    const worldBody = await fetch(`${baseUrl}/api/world`).then((response) => response.json());
    const updatedCog = worldBody.cogs.find((candidate: { name: string }) => candidate.name === cog.name);

    expect(updatedCog.position).toEqual(newPosition);
  });

  it("rejects spots without a room reference", async () => {
    const initial = await fetch(`${baseUrl}/api/venue-editor`).then((response) => response.json());
    const state = {
      ...initial.state,
      rooms: initial.state.rooms.map((room: { id: string; spotIds: string[] }) => ({
        ...room,
        spotIds: room.spotIds.filter((spotId) => spotId !== "stage_host"),
      })),
      spots: initial.state.spots.map((spot: { id: string; roomId?: string }) => {
        if (spot.id !== "stage_host") {
          return spot;
        }
        const { roomId: _roomId, ...unassignedSpot } = spot;
        return unassignedSpot;
      }),
    };

    const saveResponse = await fetch(`${baseUrl}/api/venue-editor`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(state),
    });
    const body = await saveResponse.json();

    expect(saveResponse.status).toBe(400);
    expect(body.error).toBe("Invalid venue editor request");
    expect(body.issues[0]).toEqual(expect.objectContaining({ message: "Required" }));
    expect(body.issues[0].path[0]).toBe("spots");
    expect(body.issues[0].path[2]).toBe("roomId");
  });

  it("strips legacy links that reference missing spots", async () => {
    const initial = await fetch(`${baseUrl}/api/venue-editor`).then((response) => response.json());

    const response = await fetch(`${baseUrl}/api/venue-editor`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        ...initial.state,
        links: [{ id: "missing", fromSpotId: "stage_host", toSpotId: "missing-spot" }],
      }),
    });
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.state.links).toEqual([]);
  });

  it("rejects room paths that reference missing rooms", async () => {
    const initial = await fetch(`${baseUrl}/api/venue-editor`).then((response) => response.json());

    const response = await fetch(`${baseUrl}/api/venue-editor`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        ...initial.state,
        paths: [{ id: "missing", fromRoomId: "stage", toRoomId: "missing-room", points: [] }],
      }),
    });
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(body.error).toBe("Invalid venue editor request");
    expect(body.issues).toEqual([
      expect.objectContaining({
        path: ["paths", 0],
        message: expect.stringContaining("unknown room"),
      }),
    ]);
  });
});
