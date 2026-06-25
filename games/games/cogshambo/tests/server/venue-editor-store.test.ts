import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { VenueEditorState } from "../../src/shared/types.js";
import { createJsonVenueEditorStore, type VenueEditorStore } from "../../src/server/venue-editor-store.js";

let tempDir: string;
let store: VenueEditorStore;
let graphPath: string;

const seedState: Omit<VenueEditorState, "updatedAt"> = {
  imageUrl: "/assets/cogshambo/venue/gray-area-floor-plan.png",
  dimensions: { width: 30, height: 10 },
  rooms: [
    {
      id: "left",
      label: "Left",
      kind: "lounge",
      rect: { x: 0, y: 0, width: 5, height: 5 },
      spotIds: ["left-spot", "right-spot"],
      neighborIds: [],
    },
    {
      id: "right",
      label: "Right",
      kind: "lounge",
      rect: { x: 20, y: 0, width: 5, height: 5 },
      spotIds: [],
      neighborIds: [],
    },
  ],
  spots: [
    { id: "left-spot", roomId: "left", label: "Left spot", position: { x: 1, y: 1 } },
    { id: "right-spot", roomId: "left", label: "Right spot", position: { x: 22, y: 2 } },
  ],
  links: [{ id: "left-spot__right-spot", fromSpotId: "left-spot", toSpotId: "right-spot" }],
  paths: [],
};

beforeEach(() => {
  tempDir = mkdtempSync(path.join(tmpdir(), "cogshambo-venue-store-"));
  graphPath = path.join(tempDir, "venue-graph.json");
  store = createJsonVenueEditorStore(graphPath);
});

afterEach(() => {
  store.close();
  rmSync(tempDir, { recursive: true, force: true });
});

describe("venue editor store", () => {
  it("preserves seeded spot room assignments and syncs room spot ids", () => {
    const loaded = store.load(() => seedState);

    expect(loaded.spots.find((spot) => spot.id === "left-spot")?.roomId).toBe("left");
    expect(loaded.spots.find((spot) => spot.id === "right-spot")?.roomId).toBe("left");
    expect(loaded.rooms.find((room) => room.id === "left")?.spotIds).toEqual(["left-spot", "right-spot"]);
    expect(loaded.rooms.find((room) => room.id === "right")?.spotIds).toEqual([]);
    expect(loaded.links).toEqual([]);
  });

  it("preserves persisted spot room assignments and syncs room spot ids", () => {
    store.save(seedState);

    const loaded = store.load(() => seedState);

    expect(loaded.spots.find((spot) => spot.id === "left-spot")?.roomId).toBe("left");
    expect(loaded.spots.find((spot) => spot.id === "right-spot")?.roomId).toBe("left");
    expect(loaded.rooms.find((room) => room.id === "left")?.spotIds).toEqual(["left-spot", "right-spot"]);
    expect(loaded.rooms.find((room) => room.id === "right")?.spotIds).toEqual([]);
    expect(loaded.links).toEqual([]);
  });

  it("persists saved venue state as a JSON graph file", () => {
    const saved = store.save({
      ...seedState,
      paths: [{ id: "left__right", fromRoomId: "left", toRoomId: "right", points: [{ x: 12, y: 3 }] }],
    });
    const parsed = JSON.parse(readFileSync(graphPath, "utf8")) as VenueEditorState;
    const reloadedStore = createJsonVenueEditorStore(graphPath);

    expect(existsSync(graphPath)).toBe(true);
    expect(parsed.updatedAt).toBe(saved.updatedAt);
    expect(parsed.rooms.map((room) => room.id)).toEqual(["left", "right"]);
    expect(parsed.spots.map((spot) => spot.id)).toEqual(["left-spot", "right-spot"]);
    expect(parsed.links).toEqual([]);
    expect(reloadedStore.load(() => seedState).paths).toEqual([
      { id: "left__right", fromRoomId: "left", toRoomId: "right", points: [{ x: 12, y: 3 }] },
    ]);
    reloadedStore.close();
  });
});
