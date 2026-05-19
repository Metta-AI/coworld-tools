import { describe, expect, it } from "vitest";
import type { CogAction, VenueLayout, WorldObject, WorldSnapshot } from "../../src/shared/types.js";
import { legacyHalfSecondTicksToSimulationTicks, secondsToSimulationTicks } from "../../src/shared/timing.js";
import { createSeedWorld } from "../../src/server/simulation/seed-world.js";
import { GridWorld } from "../../src/server/simulation/world.js";

describe("GridWorld", () => {
  it("creates observations with visible cells and entities", () => {
    const world = new GridWorld({ width: 20, height: 20 });
    const centerCog = world.addCog({
      name: "Center",
      spriteSheetKey: "cog-center",
      controllerId: "stub",
      attributes: { energy: 5 },
      position: { x: 10, y: 10 },
    });
    const nearCog = world.addCog({
      name: "Near",
      spriteSheetKey: "cog-near",
      controllerId: "stub",
      attributes: { energy: 5 },
      position: { x: 13, y: 14 },
    });
    world.addCog({
      name: "Far",
      spriteSheetKey: "cog-far",
      controllerId: "stub",
      attributes: { energy: 5 },
      position: { x: 16, y: 10 },
    });

    const observation = world.getObservation(centerCog.id);

    expect(observation.visibleEntities.some((entity) => entity.id === nearCog.id)).toBe(true);
    expect(observation.visibleEntities.some((entity) => entity.kind === "cog" && entity.name === "Far")).toBe(false);
    expect(observation.visibleCells).toContainEqual({ x: 10, y: 10 });
    expect(observation.visibleCells).toContainEqual({ x: 15, y: 10 });
    expect(observation.visibleCells).not.toContainEqual({ x: 16, y: 10 });
  });

  it("only includes events relevant to the observed cog", async () => {
    const world = new GridWorld({ width: 20, height: 20 });
    const ada = world.addCog({ name: "Ada", controllerId: "stub", position: { x: 5, y: 5 }, color: "red" });
    const babbage = world.addCog({ name: "Babbage", controllerId: "stub", position: { x: 6, y: 5 }, color: "blue" });
    const mira = world.addCog({ name: "Mira", controllerId: "stub", position: { x: 7, y: 5 }, color: "blue" });

    await world.step(
      new Map<string, CogAction>([
        [mira.id, { type: "move", direction: "east" }],
        [ada.id, { type: "debate", targetId: babbage.id }],
      ]),
    );

    const observation = world.getObservation(ada.id);

    expect(observation.recentEvents.map((event) => event.message)).toEqual(
      expect.arrayContaining([expect.stringContaining("Ada started debating Babbage")]),
    );
    expect(observation.recentEvents.map((event) => event.message)).not.toEqual(
      expect.arrayContaining([expect.stringContaining("Mira moved east")]),
    );
  });

  it("creates a cog in an empty cell", () => {
    const world = new GridWorld({ width: 8, height: 8 });

    const cog = world.addCog({
      name: "New Cog",
      spriteSheetKey: "cog-new",
      controllerId: "wander",
      attributes: { energy: 8 },
    });

    expect(cog.id).toMatch(/^cog_/);
    expect(cog.position.x).toBeGreaterThanOrEqual(0);
    expect(cog.position.y).toBeGreaterThanOrEqual(0);
    expect(world.snapshot().cogs).toHaveLength(1);
  });

  it("uses llm as the default controller for new cogs", () => {
    const world = new GridWorld({ width: 8, height: 8 });

    const cog = world.addCog({ name: "Default Controller" });

    expect(cog.controllerId).toBe("llm");
  });

  it("assigns unique names when duplicate cogs are added", () => {
    const world = new GridWorld({ width: 8, height: 8 });

    const first = world.addCog({ name: "Grace", controllerId: "stub" });
    const second = world.addCog({ name: "Grace", controllerId: "stub" });
    const third = world.addCog({ name: "Grace", controllerId: "stub" });

    expect([first.name, second.name, third.name]).toEqual(["Grace", "Grace 2", "Grace 3"]);
  });

  it("keeps names unique when profiles are renamed", () => {
    const world = new GridWorld({ width: 8, height: 8 });
    const ada = world.addCog({ name: "Ada", controllerId: "stub" });
    const babbage = world.addCog({ name: "Babbage", controllerId: "stub" });

    const updated = world.updateCogProfile(babbage.id, {
      name: "Ada",
      behaviorPrompt: "",
      attributes: {},
    });

    expect(ada.name).toBe("Ada");
    expect(updated.name).toBe("Ada 2");
    expect(world.snapshot().cogs.map((cog) => cog.name)).toEqual(["Ada", "Ada 2"]);
  });

  it("assigns neutral sprites to built-in cogs", () => {
    const world = new GridWorld({ width: 8, height: 8 });

    const cog = world.addCog({
      name: "Default",
      controllerId: "wander",
      attributes: { energy: 8 },
    });

    expect(cog.spriteSheetKey).toBe("cog-default");
    expect(cog.spriteUrl).toBe("/assets/cogshambo/sprite-sheets/cog-default/frames/cog-default-01.png");
    expect(cog.spriteUrls).toBeUndefined();
  });

  it("shuffles a one-color roster back across the active teams", () => {
    const world = new GridWorld({ width: 8, height: 8 });
    for (let index = 0; index < 6; index += 1) {
      world.addCog({ name: `Cog ${index}`, color: "blue", controllerId: "stub", position: { x: index, y: 1 } });
    }

    const snapshot = world.shuffleCogTeams();

    expect(snapshot.cogs.filter((cog) => cog.color === "red")).toHaveLength(3);
    expect(snapshot.cogs.filter((cog) => cog.color === "blue")).toHaveLength(3);
  });

  it("keeps kicked-home cogs out of active snapshots while preserving them in state", async () => {
    const world = new GridWorld({ width: 8, height: 8 });
    const ada = world.addCog({ name: "Ada", color: "red", controllerId: "stub", position: { x: 2, y: 2 } });
    const babbage = world.addCog({ name: "Babbage", color: "blue", controllerId: "stub", position: { x: 3, y: 2 } });

    await world.step(new Map<string, CogAction>([[ada.id, { type: "debate", targetId: babbage.id }]]));
    const homeCog = world.kickCogHome(ada.id);
    await world.step(new Map<string, CogAction>([[ada.id, { type: "move", direction: "east" }]]));

    expect(homeCog.status).toBe("home");
    expect(world.snapshot().cogs.map((cog) => cog.id)).toEqual([babbage.id]);
    expect(world.snapshot().cogs[0]?.debate).toBeUndefined();

    const exported = world.exportState();
    expect(exported.cogs.find((cog) => cog.id === ada.id)?.status).toBe("home");
    const restored = GridWorld.fromState(exported);
    expect(restored.snapshot().cogs.map((cog) => cog.id)).toEqual([babbage.id]);
    expect(restored.exportState().cogs.find((cog) => cog.id === ada.id)?.status).toBe("home");
  });

  it("does not remove active cogs when their local claim is abandoned", () => {
    const world = new GridWorld({ width: 8, height: 8 });
    const ada = world.addCog({ name: "Ada", color: "red", controllerId: "stub", position: { x: 2, y: 2 } });

    const abandoned = world.abandonCog(ada.id);

    expect(abandoned.status).toBeUndefined();
    expect(world.snapshot().cogs.map((cog) => cog.id)).toEqual([ada.id]);
    expect(world.exportState().cogs.find((cog) => cog.id === ada.id)?.status).toBeUndefined();
    expect(world.snapshot().recentEvents.some((event) => event.type === "abandon")).toBe(false);
  });

  it("does not expose removed portable-object world helpers", () => {
    const world = new GridWorld({ width: 8, height: 8 });
    const removedToken = ["cr", "own"].join("");

    expect(`add${removedToken[0].toUpperCase()}${removedToken.slice(1)}` in world).toBe(false);
    expect(world.snapshot()).not.toHaveProperty(`${removedToken}HolderId`);
  });

  it("keeps movement into occupied cog cells blocked", async () => {
    const world = new GridWorld({ width: 8, height: 8 });
    const cog = world.addCog({
      name: "Walker",
      spriteSheetKey: "cog-walker",
      controllerId: "stub",
      attributes: { energy: 5 },
      position: { x: 2, y: 2 },
    });
    world.addCog({ name: "Blocker", position: { x: 3, y: 2 }, controllerId: "stub" });

    await world.step(new Map<string, CogAction>([[cog.id, { type: "move", direction: "east" }]]));

    const snapshot = world.snapshot();
    expect(snapshot.cogs.find((candidate) => candidate.id === cog.id)?.position).toEqual({ x: 2, y: 2 });
    expect(snapshot.recentEvents.at(-1)?.type).toBe("moveBlocked");
  });

  it("keeps movement into tree and block map objects blocked", async () => {
    for (const object of [
      { id: "tree_test", type: "tree" as const },
      { id: "block_test", type: "block" as const },
    ]) {
      const world = new GridWorld({ width: 8, height: 8 });
      const cog = world.addCog({
        name: "Walker",
        spriteSheetKey: "cog-walker",
        controllerId: "stub",
        attributes: { energy: 5 },
        position: { x: 2, y: 2 },
      });
      world.addObject({
        ...object,
        position: { x: 3, y: 2 },
        spriteKey: "map-object-marker",
        attributes: {},
      });

      await world.step(new Map<string, CogAction>([[cog.id, { type: "move", direction: "east" }]]));

      const snapshot = world.snapshot();
      expect(snapshot.cogs.find((candidate) => candidate.id === cog.id)?.position).toEqual({ x: 2, y: 2 });
      expect(snapshot.recentEvents.at(-1)).toEqual(
        expect.objectContaining({
          type: "moveBlocked",
          targetId: object.id,
        }),
      );
    }
  });

  it("creates deterministic seeded worlds", () => {
    const world = createSeedWorld();
    const snapshot = world.snapshot();

    expect(snapshot.dimensions).toEqual({ width: 50, height: 28 });
    expect(snapshot.venue?.rooms).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ id: "stage", spotIds: ["stage_host", "stage_guest"] }),
        expect.objectContaining({ id: "seat_front", spotIds: expect.arrayContaining(["seat_front_left", "seat_front_right"]) }),
        expect.objectContaining({ id: "seat_back_right", spotIds: expect.arrayContaining(["seat_back_right_a", "seat_back_right_b"]) }),
        expect.objectContaining({ id: "lounge_sofas", spotIds: expect.arrayContaining(["sofa_left", "sofa_table", "sofa_right"]) }),
        expect.objectContaining({ id: "exhibit_center_a", spotIds: expect.arrayContaining(["center_a_left", "center_a_mid", "center_a_right"]) }),
        expect.objectContaining({ id: "new_room", spotIds: expect.arrayContaining(["new_room_spot_1"]) }),
        expect.objectContaining({ id: "new_room_2", spotIds: expect.arrayContaining(["new_room_2_spot_1"]) }),
      ]),
    );
    const roomIds = new Set(snapshot.venue?.rooms.map((room) => room.id) ?? []);
    const spotIds = new Set(snapshot.venue?.spots.map((spot) => spot.id) ?? []);
    expect(snapshot.venue?.spots.every((spot) => roomIds.has(spot.roomId))).toBe(true);
    expect(snapshot.venue?.rooms.every((room) => room.spotIds.every((spotId) => spotIds.has(spotId)))).toBe(true);
    expect(snapshot.venue?.spotLinks ?? []).toEqual([]);
    expect(snapshot.venue?.spots.every((spot) => !spot.role || spot.role === "speaker" || spot.role === "audience")).toBe(true);
    expect(snapshot.venue?.spots).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ id: "stage_host", roomId: "stage", position: { x: 46, y: 13 } }),
        expect.objectContaining({ id: "stage_guest", roomId: "stage", position: { x: 46, y: 17 } }),
        expect.objectContaining({ id: "bar_left_a", roomId: "concessions_left", position: { x: 11, y: 22 } }),
      ]),
    );
    expect(snapshot.cogs).toHaveLength(10);
    expect(snapshot.cogs.every((cog) => cog.controllerId === "llm")).toBe(true);
    expect(snapshot.cogs.filter((cog) => cog.color === "red")).toHaveLength(5);
    expect(snapshot.cogs.filter((cog) => cog.color === "blue")).toHaveLength(5);
    expect(snapshot.cogs).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          name: "Ada",
          location: { roomId: "stage", spotId: "stage_host" },
          spriteUrl: "/assets/cogshambo/sprite-sheets/cog-ada/frames/cog-ada-01.png",
          spriteUrls: undefined,
        }),
        expect.objectContaining({
          name: "Babbage",
          spriteUrl: "/assets/cogshambo/sprite-sheets/cog-babbage/frames/cog-babbage-01.png",
          spriteUrls: undefined,
        }),
        expect.objectContaining({
          name: "Mira",
          spriteUrl: "/assets/cogshambo/sprite-sheets/cog-mira/frames/cog-mira-01.png",
          spriteUrls: undefined,
        }),
      ]),
    );
    expect(snapshot.objects).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          type: "picknick",
          position: { x: 13, y: 8 },
        }),
        expect.objectContaining({
          type: "bench",
          position: { x: 23, y: 18 },
        }),
        expect.objectContaining({
          type: "stairs",
          position: { x: 7, y: 12 },
        }),
        expect.objectContaining({
          type: "block",
          position: { x: 15, y: 20 },
        }),
      ]),
    );
  });

  it("uses room links as venue move options", async () => {
    const venue: VenueLayout = {
      rooms: [
        { id: "room-a", label: "Room A", kind: "lounge", spotIds: ["a"], neighborIds: ["room-b"] },
        { id: "room-b", label: "Room B", kind: "lounge", spotIds: ["b"], neighborIds: ["room-a", "room-c"] },
        { id: "room-c", label: "Room C", kind: "lounge", spotIds: ["c"], neighborIds: ["room-b"] },
      ],
      spots: [
        { id: "a", roomId: "room-a", label: "A", position: { x: 1, y: 1 } },
        { id: "b", roomId: "room-b", label: "B", position: { x: 4, y: 1 } },
        { id: "c", roomId: "room-c", label: "C", position: { x: 7, y: 1 } },
      ],
      spotLinks: [],
    };
    const world = new GridWorld({ width: 10, height: 4 }, {}, venue);
    const ada = world.addCog({ name: "Ada", color: "red", controllerId: "stub", location: { roomId: "room-a", spotId: "a" } });

    await world.step(new Map<string, CogAction>([[ada.id, { type: "move", roomId: "room-c" }]]));

    expect(world.snapshot().cogs.find((cog) => cog.id === ada.id)?.location?.roomId).toBe("room-a");
    expect(world.snapshot().recentEvents.at(-1)).toEqual(
      expect.objectContaining({
        type: "moveBlocked",
        message: "Ada could not move from Room A to Room C",
      }),
    );

    await world.step(new Map<string, CogAction>([[ada.id, { type: "move", roomId: "room-b" }]]));

    const arrivedSnapshot = await stepUntilNotMoving(world, ada.id);
    expect(arrivedSnapshot.cogs.find((cog) => cog.id === ada.id)?.location).toEqual({ roomId: "room-b", spotId: "b" });
  });

  it("does not offer or perform same-room venue spot shuffles", async () => {
    const venue: VenueLayout = {
      rooms: [
        { id: "room-a", label: "Room A", kind: "lounge", spotIds: ["a1", "a2"], neighborIds: ["room-b"] },
        { id: "room-b", label: "Room B", kind: "lounge", spotIds: ["b1"], neighborIds: ["room-a"] },
      ],
      spots: [
        { id: "a1", roomId: "room-a", label: "A1", position: { x: 1, y: 1 } },
        { id: "a2", roomId: "room-a", label: "A2", position: { x: 2, y: 1 } },
        { id: "b1", roomId: "room-b", label: "B1", position: { x: 5, y: 1 } },
      ],
      spotLinks: [],
      roomPaths: [],
    };
    const world = new GridWorld({ width: 8, height: 4 }, {}, venue);
    const ada = world.addCog({ name: "Ada", color: "red", controllerId: "stub", location: { roomId: "room-a", spotId: "a1" } });

    expect(world.moveOptionsFor(ada.id).roomIds).toEqual(["room-b"]);

    await world.step(new Map<string, CogAction>([[ada.id, { type: "move", roomId: "room-a" }]]));

    const snapshot = world.snapshot();
    expect(snapshot.cogs.find((cog) => cog.id === ada.id)).toMatchObject({
      location: { roomId: "room-a", spotId: "a1" },
      position: { x: 1, y: 1 },
    });
    expect(snapshot.cogs.find((cog) => cog.id === ada.id)?.moving).toBeUndefined();
    expect(snapshot.recentEvents.at(-1)).toEqual(
      expect.objectContaining({
        type: "moveBlocked",
        message: "Ada is already in Room A",
      }),
    );
  });

  it("places room entrants in the empty spot nearest another cog", async () => {
    const venue: VenueLayout = {
      rooms: [
        { id: "room-a", label: "Room A", kind: "lounge", spotIds: ["a1"], neighborIds: ["room-b"] },
        { id: "room-b", label: "Room B", kind: "lounge", spotIds: ["far", "occupied", "near"], neighborIds: ["room-a"] },
      ],
      spots: [
        { id: "a1", roomId: "room-a", label: "A1", position: { x: 1, y: 1 } },
        { id: "far", roomId: "room-b", label: "Far", position: { x: 8, y: 1 } },
        { id: "occupied", roomId: "room-b", label: "Occupied", position: { x: 4, y: 1 } },
        { id: "near", roomId: "room-b", label: "Near", position: { x: 5, y: 1 } },
      ],
      spotLinks: [],
      roomPaths: [],
    };
    const world = new GridWorld({ width: 10, height: 4 }, {}, venue);
    const ada = world.addCog({ name: "Ada", color: "red", controllerId: "stub", location: { roomId: "room-a", spotId: "a1" } });
    world.addCog({ name: "Babbage", color: "blue", controllerId: "stub", location: { roomId: "room-b", spotId: "occupied" } });

    await world.step(new Map<string, CogAction>([[ada.id, { type: "move", roomId: "room-b" }]]));

    const snapshot = await stepUntilNotMoving(world, ada.id);
    expect(snapshot.cogs.find((cog) => cog.id === ada.id)?.location).toEqual({ roomId: "room-b", spotId: "near" });
  });

  it("uses same-room speaker spots as venue debate partners", () => {
    const venue: VenueLayout = {
      rooms: [
        { id: "room", label: "Room", kind: "lounge", spotIds: ["a", "b", "c"], neighborIds: [] },
      ],
      spots: [
        { id: "a", roomId: "room", label: "A", position: { x: 1, y: 1 } },
        { id: "b", roomId: "room", label: "B", position: { x: 2, y: 1 } },
        { id: "c", roomId: "room", label: "C", position: { x: 7, y: 1 }, role: "audience" },
      ],
      spotLinks: [],
      roomPaths: [],
    };
    const world = new GridWorld({ width: 10, height: 4 }, {}, venue);
    const ada = world.addCog({ name: "Ada", color: "red", controllerId: "stub", location: { roomId: "room", spotId: "a" } });
    const babbage = world.addCog({ name: "Babbage", color: "blue", controllerId: "stub", location: { roomId: "room", spotId: "b" } });
    const mira = world.addCog({ name: "Mira", color: "blue", controllerId: "stub", location: { roomId: "room", spotId: "c" } });

    expect(world.canStartDebate(ada.id, babbage.id)).toBe(true);
    expect(world.canStartDebate(ada.id, mira.id)).toBe(false);
  });

  it("rejects venue cogs whose explicit position does not match their spot", () => {
    const venue: VenueLayout = {
      rooms: [
        { id: "room", label: "Room", kind: "lounge", spotIds: ["a"], neighborIds: [] },
      ],
      spots: [
        { id: "a", roomId: "room", label: "A", position: { x: 1, y: 1 } },
      ],
      spotLinks: [],
    };
    const world = new GridWorld({ width: 10, height: 4 }, {}, venue);

    expect(() =>
      world.addCog({
        name: "Ada",
        color: "red",
        controllerId: "stub",
        location: { roomId: "room", spotId: "a" },
        position: { x: 5, y: 1 },
      }),
    ).toThrow("Cog position does not match venue spot");
  });

  it("snaps existing venue cogs when the venue layout changes", () => {
    const venue: VenueLayout = {
      rooms: [
        { id: "room", label: "Room", kind: "lounge", spotIds: ["a"], neighborIds: [] },
      ],
      spots: [
        { id: "a", roomId: "room", label: "A", position: { x: 1, y: 1 } },
      ],
      spotLinks: [],
    };
    const world = new GridWorld({ width: 10, height: 4 }, {}, venue);
    const ada = world.addCog({ name: "Ada", color: "red", controllerId: "stub", location: { roomId: "room", spotId: "a" } });

    world.updateVenueLayout({
      ...venue,
      spots: [
        { id: "a", roomId: "room", label: "A", position: { x: 4, y: 2 } },
      ],
    });

    expect(world.snapshot().cogs.find((cog) => cog.id === ada.id)?.position).toEqual({ x: 4, y: 2 });
  });

  it("repairs stale saved venue cog positions on restore", () => {
    const venue: VenueLayout = {
      rooms: [
        { id: "room", label: "Room", kind: "lounge", spotIds: ["a"], neighborIds: [] },
      ],
      spots: [
        { id: "a", roomId: "room", label: "A", position: { x: 1, y: 1 } },
      ],
      spotLinks: [],
    };
    const world = new GridWorld({ width: 10, height: 4 }, {}, venue);
    const ada = world.addCog({ name: "Ada", color: "red", controllerId: "stub", location: { roomId: "room", spotId: "a" } });
    const state = world.exportState();
    const savedCog = state.cogs.find((cog) => cog.id === ada.id);
    if (!savedCog) {
      throw new Error("Missing saved cog");
    }
    savedCog.position = { x: 8, y: 3 };

    const restored = GridWorld.fromState(state);

    expect(restored.snapshot().cogs.find((cog) => cog.id === ada.id)?.position).toEqual({ x: 1, y: 1 });
  });

  it("allows only one active debate per venue room", async () => {
    const venue: VenueLayout = {
      rooms: [
        { id: "room", label: "Room", kind: "lounge", spotIds: ["a", "b", "c", "d"], neighborIds: [] },
      ],
      spots: [
        { id: "a", roomId: "room", label: "A", position: { x: 1, y: 1 } },
        { id: "b", roomId: "room", label: "B", position: { x: 2, y: 1 } },
        { id: "c", roomId: "room", label: "C", position: { x: 3, y: 1 } },
        { id: "d", roomId: "room", label: "D", position: { x: 4, y: 1 } },
      ],
      spotLinks: [
        { id: "a__b", fromSpotId: "a", toSpotId: "b" },
        { id: "c__d", fromSpotId: "c", toSpotId: "d" },
      ],
    };
    const world = new GridWorld({ width: 8, height: 4 }, {}, venue);
    const ada = world.addCog({ name: "Ada", color: "red", controllerId: "stub", location: { roomId: "room", spotId: "a" } });
    const babbage = world.addCog({ name: "Babbage", color: "blue", controllerId: "stub", location: { roomId: "room", spotId: "b" } });
    const curie = world.addCog({ name: "Curie", color: "red", controllerId: "stub", location: { roomId: "room", spotId: "c" } });
    const darwin = world.addCog({ name: "Darwin", color: "blue", controllerId: "stub", location: { roomId: "room", spotId: "d" } });

    await world.step(
      new Map<string, CogAction>([
        [ada.id, { type: "debate", targetId: babbage.id }],
        [curie.id, { type: "debate", targetId: darwin.id }],
      ]),
    );

    const debatingCogIds = world.snapshot().cogs.filter((cog) => cog.debate).map((cog) => cog.id);
    expect(new Set(debatingCogIds)).toEqual(new Set([ada.id, babbage.id]));
  });

  it("allows only one active debate per venue section", async () => {
    const venue: VenueLayout = {
      rooms: [
        { id: "west-a", label: "West A", kind: "lounge", spotIds: ["wa1", "wa2"], neighborIds: [] },
        { id: "west-b", label: "West B", kind: "lounge", spotIds: ["wb1", "wb2"], neighborIds: [] },
        { id: "center", label: "Center", kind: "lounge", spotIds: ["c1", "c2"], neighborIds: [] },
      ],
      spots: [
        { id: "wa1", roomId: "west-a", label: "WA1", position: { x: 2, y: 1 } },
        { id: "wa2", roomId: "west-a", label: "WA2", position: { x: 3, y: 1 } },
        { id: "wb1", roomId: "west-b", label: "WB1", position: { x: 4, y: 2 } },
        { id: "wb2", roomId: "west-b", label: "WB2", position: { x: 5, y: 2 } },
        { id: "c1", roomId: "center", label: "C1", position: { x: 11, y: 1 } },
        { id: "c2", roomId: "center", label: "C2", position: { x: 12, y: 1 } },
      ],
      spotLinks: [
        { id: "wa1__wa2", fromSpotId: "wa1", toSpotId: "wa2" },
        { id: "wb1__wb2", fromSpotId: "wb1", toSpotId: "wb2" },
        { id: "c1__c2", fromSpotId: "c1", toSpotId: "c2" },
      ],
      roomPaths: [],
    };
    const world = new GridWorld({ width: 30, height: 6 }, {}, venue);
    const westRedA = world.addCog({ name: "West Red A", color: "red", controllerId: "stub", location: { roomId: "west-a", spotId: "wa1" } });
    const westBlueA = world.addCog({ name: "West Blue A", color: "blue", controllerId: "stub", location: { roomId: "west-a", spotId: "wa2" } });
    const westRedB = world.addCog({ name: "West Red B", color: "red", controllerId: "stub", location: { roomId: "west-b", spotId: "wb1" } });
    const westBlueB = world.addCog({ name: "West Blue B", color: "blue", controllerId: "stub", location: { roomId: "west-b", spotId: "wb2" } });
    const centerRed = world.addCog({ name: "Center Red", color: "red", controllerId: "stub", location: { roomId: "center", spotId: "c1" } });
    const centerBlue = world.addCog({ name: "Center Blue", color: "blue", controllerId: "stub", location: { roomId: "center", spotId: "c2" } });

    await world.step(
      new Map<string, CogAction>([
        [westRedA.id, { type: "debate", targetId: westBlueA.id }],
        [westRedB.id, { type: "debate", targetId: westBlueB.id }],
        [centerRed.id, { type: "debate", targetId: centerBlue.id }],
      ]),
    );

    const debatingCogIds = new Set(world.snapshot().cogs.filter((cog) => cog.debate).map((cog) => cog.id));
    expect(debatingCogIds).toEqual(new Set([westRedA.id, westBlueA.id, centerRed.id, centerBlue.id]));
  });

  it("applies venue debate witness certainty loss to everyone in the room", async () => {
    const venue: VenueLayout = {
      rooms: [
        { id: "room", label: "Room", kind: "lounge", spotIds: ["a", "b", "c"], neighborIds: [] },
      ],
      spots: [
        { id: "a", roomId: "room", label: "A", position: { x: 1, y: 1 } },
        { id: "b", roomId: "room", label: "B", position: { x: 2, y: 1 } },
        { id: "c", roomId: "room", label: "C", position: { x: 9, y: 1 } },
      ],
      spotLinks: [{ id: "a__b", fromSpotId: "a", toSpotId: "b" }],
    };
    const world = new GridWorld({ width: 12, height: 4 }, {
      debatePrepTicks: 0,
      debateChoiceRevealTicks: 0,
      debateResultTicks: 0,
      debateDoubt: 1,
      witnessDoubt: 5,
    }, venue);
    const ada = world.addCog({ name: "Ada", color: "red", controllerId: "stub", location: { roomId: "room", spotId: "a" } });
    const babbage = world.addCog({ name: "Babbage", color: "blue", controllerId: "stub", location: { roomId: "room", spotId: "b" } });
    const mira = world.addCog({ name: "Mira", color: "blue", controllerId: "stub", location: { roomId: "room", spotId: "c" } });

    await world.step(new Map<string, CogAction>([[ada.id, { type: "debate", targetId: babbage.id }]]));
    await world.step(
      new Map<string, CogAction>([
        [ada.id, { type: "chooseTactic", tactic: "reason" }],
        [babbage.id, { type: "chooseTactic", tactic: "spin" }],
      ]),
    );

    expect(world.snapshot().cogs.find((cog) => cog.id === mira.id)?.certainty).toBe(95);
  });

  it("moves venue cogs into an empty spot in the target room", async () => {
    const world = createSeedWorld();
    const ada = world.snapshot().cogs.find((cog) => cog.name === "Ada");
    expect(ada?.location).toEqual({ roomId: "stage", spotId: "stage_host" });

    await world.step(new Map<string, CogAction>([[ada!.id, { type: "move", roomId: "green_room" }]]));

    const snapshot = await stepUntilNotMoving(world, ada!.id);
    const movedAda = snapshot.cogs.find((cog) => cog.id === ada!.id);
    expect(movedAda?.location).toEqual({ roomId: "green_room", spotId: "green_room_sofa" });
    expect(movedAda?.position).toEqual({ x: 46, y: 4 });
    expect(snapshot.recentEvents).toContainEqual(
      expect.objectContaining({
        type: "move",
        message: "Ada arrived at Green Room - sofa",
      }),
    );
  });

  it("walks moving venue cogs along the room path until the distance-based arrival tick", async () => {
    const venue: VenueLayout = {
      rooms: [
        { id: "room-a", label: "Room A", kind: "lounge", spotIds: ["a"], neighborIds: ["room-b"] },
        { id: "room-b", label: "Room B", kind: "lounge", spotIds: ["b"], neighborIds: ["room-a"] },
      ],
      spots: [
        { id: "a", roomId: "room-a", label: "A", position: { x: 1, y: 1 } },
        { id: "b", roomId: "room-b", label: "B", position: { x: 9, y: 1 } },
      ],
      spotLinks: [],
      roomPaths: [{ id: "room-a__room-b", fromRoomId: "room-a", toRoomId: "room-b", points: [{ x: 1, y: 5 }, { x: 9, y: 5 }] }],
    };
    const world = new GridWorld({ width: 12, height: 4 }, {}, venue);
    const ada = world.addCog({ name: "Ada", color: "red", controllerId: "stub", location: { roomId: "room-a", spotId: "a" } });
    const blue = world.addCog({ name: "Blue", color: "blue", controllerId: "stub", position: { x: 1, y: 2 } });

    let snapshot = await world.step(new Map<string, CogAction>([[ada.id, { type: "move", roomId: "room-b" }]]));
    let movingAda = snapshot.cogs.find((cog) => cog.id === ada.id);
    expect(movingAda?.location).toBeUndefined();
    expect(movingAda?.position).toEqual({ x: 1, y: 1 });
    expect(movingAda?.moving?.path).toEqual([{ x: 1, y: 1 }, { x: 1, y: 5 }, { x: 9, y: 5 }, { x: 9, y: 1 }]);
    expect((movingAda as { moving?: { arriveTick: number } } | undefined)?.moving?.arriveTick).toBe(
      1 + Math.ceil((16 / 12) * secondsToSimulationTicks(10)),
    );
    expect(world.canCogMove(ada.id)).toBe(false);
    expect(world.canStartDebate(ada.id, blue.id)).toBe(false);

    for (let step = 0; step < secondsToSimulationTicks(0.5); step += 1) {
      snapshot = await world.step(new Map());
    }
    movingAda = snapshot.cogs.find((cog) => cog.id === ada.id);
    expect(movingAda?.location).toBeUndefined();
    expect(movingAda?.position?.x).toBeCloseTo(1);
    expect(movingAda?.position?.y).toBeCloseTo(1 + 16 / Math.ceil((16 / 12) * secondsToSimulationTicks(10)));
    expect((movingAda as { moving?: unknown } | undefined)?.moving).toBeDefined();

    snapshot = await stepUntilNotMoving(world, ada.id);
    const arrivedAda = snapshot.cogs.find((cog) => cog.id === ada.id);
    expect(arrivedAda?.moving).toBeUndefined();
    expect(arrivedAda?.location).toEqual({ roomId: "room-b", spotId: "b" });
    expect(arrivedAda?.position).toEqual({ x: 9, y: 1 });
    expect(snapshot.recentEvents.at(-1)).toEqual(
      expect.objectContaining({
        type: "move",
        message: "Ada arrived at Room B - B",
      }),
    );
  });

  it("takes ten seconds to move across the venue's longest side", async () => {
    const world = new GridWorld({ width: 20, height: 8 }, {}, twoRoomVenue("wide", { x: 0, y: 1 }, { x: 20, y: 1 }));
    const cog = world.addCog({ name: "Walker", color: "red", controllerId: "stub", location: { roomId: "room-a", spotId: "a" } });

    const snapshot = await world.step(new Map<string, CogAction>([[cog.id, { type: "move", roomId: "room-b" }]]));
    const move = snapshot.cogs.find((candidate) => candidate.id === cog.id)?.moving;

    expect(move).toBeDefined();
    expect(move!.arriveTick - move!.startedTick).toBe(secondsToSimulationTicks(10));
  });

  it("uses the same walking rate for short and long room moves", async () => {
    const shortWorld = new GridWorld({ width: 16, height: 4 }, {}, twoRoomVenue("short", { x: 1, y: 1 }, { x: 5, y: 1 }));
    const longWorld = new GridWorld({ width: 16, height: 4 }, {}, twoRoomVenue("long", { x: 1, y: 1 }, { x: 9, y: 1 }));
    const shortCog = shortWorld.addCog({ name: "Short", color: "red", controllerId: "stub", location: { roomId: "room-a", spotId: "a" } });
    const longCog = longWorld.addCog({ name: "Long", color: "red", controllerId: "stub", location: { roomId: "room-a", spotId: "a" } });

    const shortSnapshot = await shortWorld.step(new Map<string, CogAction>([[shortCog.id, { type: "move", roomId: "room-b" }]]));
    const longSnapshot = await longWorld.step(new Map<string, CogAction>([[longCog.id, { type: "move", roomId: "room-b" }]]));
    const shortMove = shortSnapshot.cogs.find((cog) => cog.id === shortCog.id)?.moving;
    const longMove = longSnapshot.cogs.find((cog) => cog.id === longCog.id)?.moving;

    expect(shortMove).toBeDefined();
    expect(longMove).toBeDefined();
    expect(shortMove!.arriveTick - shortMove!.startedTick).toBe(Math.ceil((4 / 16) * secondsToSimulationTicks(10)));
    expect(longMove!.arriveTick - longMove!.startedTick).toBe(Math.ceil((8 / 16) * secondsToSimulationTicks(10)));
  });

  it("keeps a leaving venue spot reserved until the moving cog arrives", async () => {
    const venue: VenueLayout = {
      rooms: [
        { id: "room-a", label: "Room A", kind: "lounge", spotIds: ["a1", "a2"], neighborIds: ["room-b"] },
        { id: "room-b", label: "Room B", kind: "lounge", spotIds: ["b1", "b2"], neighborIds: ["room-a"] },
      ],
      spots: [
        { id: "a1", roomId: "room-a", label: "A1", position: { x: 1, y: 1 } },
        { id: "a2", roomId: "room-a", label: "A2", position: { x: 2, y: 1 } },
        { id: "b1", roomId: "room-b", label: "B1", position: { x: 9, y: 1 } },
        { id: "b2", roomId: "room-b", label: "B2", position: { x: 10, y: 1 } },
      ],
      spotLinks: [],
    };
    const world = new GridWorld({ width: 12, height: 4 }, {}, venue);
    const ada = world.addCog({ name: "Ada", color: "red", controllerId: "stub", location: { roomId: "room-a", spotId: "a1" } });
    const blue = world.addCog({ name: "Blue", color: "blue", controllerId: "stub", location: { roomId: "room-b", spotId: "b2" } });

    await world.step(new Map<string, CogAction>([[ada.id, { type: "move", roomId: "room-b" }]]));
    const snapshot = await world.step(new Map<string, CogAction>([[blue.id, { type: "move", roomId: "room-a" }]]));

    expect(snapshot.cogs.find((cog) => cog.id === blue.id)?.moving?.to).toEqual({ roomId: "room-a", spotId: "a2" });
  });

  it("keeps venue cogs at their chosen spot when asked to move within the same room", async () => {
    const world = createSeedWorld();
    const mira = world.snapshot().cogs.find((cog) => cog.name === "Mira");
    expect(mira?.location).toEqual({ roomId: "lounge_sofas", spotId: "sofa_left" });

    await world.step(new Map<string, CogAction>([[mira!.id, { type: "move", roomId: "lounge_sofas" }]]));

    const snapshot = await stepUntilNotMoving(world, mira!.id);
    const movedMira = snapshot.cogs.find((cog) => cog.id === mira!.id);
    expect(movedMira?.location).toEqual({ roomId: "lounge_sofas", spotId: "sofa_left" });
    expect(movedMira?.position).toEqual({ x: 22, y: 17 });
    expect(snapshot.recentEvents).toContainEqual(
      expect.objectContaining({
        type: "moveBlocked",
        message: "Mira is already in Sofa Nook",
      }),
    );
  });

  it("blocks repeated venue moves while a cog shares a room", async () => {
    const world = createSeedWorld();
    world.updateGameConfig({ roomMoveCooldownTicks: legacyHalfSecondTicksToSimulationTicks(10) });
    const ada = world.snapshot().cogs.find((cog) => cog.name === "Ada");
    const babbage = world.snapshot().cogs.find((cog) => cog.name === "Babbage");

    await world.step(new Map<string, CogAction>([[ada!.id, { type: "move", roomId: "green_room" }]]));
    await stepUntilNotMoving(world, ada!.id);
    await world.step(new Map<string, CogAction>([[babbage!.id, { type: "move", roomId: "green_room" }]]));
    await stepUntilNotMoving(world, babbage!.id);
    await world.step(new Map<string, CogAction>([[ada!.id, { type: "move", roomId: "stage" }]]));

    const snapshot = world.snapshot();
    const blockedAda = snapshot.cogs.find((cog) => cog.id === ada!.id);
    expect(blockedAda?.location).toEqual({ roomId: "green_room", spotId: "green_room_sofa" });
    expect(snapshot.recentEvents.at(-1)).toEqual(
      expect.objectContaining({
        type: "moveBlocked",
      }),
    );
    expect(snapshot.recentEvents.at(-1)?.message).toContain("Ada must wait");
    expect(snapshot.recentEvents.at(-1)?.message).toContain("before moving from Green Room");
  });

  it("allows lone cogs to leave a room during cooldown", async () => {
    const world = createSeedWorld();
    world.updateGameConfig({ roomMoveCooldownTicks: legacyHalfSecondTicksToSimulationTicks(10) });
    const ada = world.snapshot().cogs.find((cog) => cog.name === "Ada");

    await world.step(new Map<string, CogAction>([[ada!.id, { type: "move", roomId: "green_room" }]]));
    await stepUntilNotMoving(world, ada!.id);
    await world.step(new Map<string, CogAction>([[ada!.id, { type: "move", roomId: "stage" }]]));

    const snapshot = await stepUntilNotMoving(world, ada!.id);
    const movedAda = snapshot.cogs.find((cog) => cog.id === ada!.id);
    expect(movedAda?.location?.roomId).toBe("stage");
    expect(snapshot.recentEvents).toContainEqual(
      expect.objectContaining({
        type: "move",
        message: "Ada arrived at Main Stage - host mic",
      }),
    );
  });

  it("allows a lone cog to bypass move cooldown when moving to a neighboring room", async () => {
    const world = createSeedWorld();
    world.updateGameConfig({ roomMoveCooldownTicks: legacyHalfSecondTicksToSimulationTicks(10) });
    const ada = world.snapshot().cogs.find((cog) => cog.name === "Ada");

    await world.step(new Map<string, CogAction>([[ada!.id, { type: "move", roomId: "green_room" }]]));
    await stepUntilNotMoving(world, ada!.id);
    await world.step(new Map<string, CogAction>([[ada!.id, { type: "move", roomId: "stage" }]]));

    const snapshot = await stepUntilNotMoving(world, ada!.id);
    const movedAda = snapshot.cogs.find((cog) => cog.id === ada!.id);
    expect(movedAda?.location).toEqual({ roomId: "stage", spotId: "stage_host" });
  });

  it("places room entrants into the next empty spot and blocks full rooms", async () => {
    const world = createSeedWorld();
    const ada = world.snapshot().cogs.find((cog) => cog.name === "Ada");
    const babbage = world.snapshot().cogs.find((cog) => cog.name === "Babbage");

    await world.step(new Map<string, CogAction>([[ada!.id, { type: "move", roomId: "green_room" }]]));
    await stepUntilNotMoving(world, ada!.id);
    await world.step(new Map<string, CogAction>([[babbage!.id, { type: "move", roomId: "green_room" }]]));
    await stepUntilNotMoving(world, babbage!.id);
    const third = world.addCog({
      name: "Third",
      controllerId: "stub",
      location: { roomId: "stage", spotId: "stage_host" },
    });
    await world.step(new Map<string, CogAction>([[third.id, { type: "move", roomId: "green_room" }]]));
    let snapshot = await stepUntilNotMoving(world, third.id);
    expect(snapshot.cogs.find((cog) => cog.id === third.id)?.location).toEqual({
      roomId: "green_room",
      spotId: "green_room_door",
    });

    const fourth = world.addCog({
      name: "Fourth",
      controllerId: "stub",
      location: { roomId: "stage", spotId: "stage_host" },
    });
    await world.step(new Map<string, CogAction>([[fourth.id, { type: "move", roomId: "green_room" }]]));

    snapshot = world.snapshot();
    expect(snapshot.cogs.find((cog) => cog.id === fourth.id)?.location?.roomId).not.toBe("green_room");
    expect(snapshot.recentEvents.at(-1)).toEqual(
      expect.objectContaining({
        type: "moveBlocked",
        message: "Fourth could not enter Green Room because it is full",
      }),
    );
  });

  it("isolates world state from caller-owned constructor and cog inputs", () => {
    const dimensions = { width: 8, height: 8 };
    const position = { x: 2, y: 2 };
    const attributes = { energy: 5 };
    const world = new GridWorld(dimensions);

    const cog = world.addCog({
      name: "Isolated",
      spriteSheetKey: "cog-isolated",
      controllerId: "stub",
      attributes,
      position,
    });

    dimensions.width = 1;
    position.x = 7;
    attributes.energy = 99;
    cog.position.y = 7;
    cog.attributes.energy = 42;

    const snapshot = world.snapshot();
    expect(snapshot.dimensions).toEqual({ width: 8, height: 8 });
    expect(snapshot.cogs.find((candidate) => candidate.id === cog.id)?.position).toEqual({ x: 2, y: 2 });
    expect(snapshot.cogs.find((candidate) => candidate.id === cog.id)?.attributes.energy).toBe(5);
  });

  it("isolates world state from caller-owned object data and returned objects", () => {
    const world = new GridWorld({ width: 8, height: 8 });
    const object: WorldObject = {
      id: "bench_mutable",
      type: "bench",
      position: { x: 3, y: 2 },
      spriteKey: "bench",
      attributes: { weight: 2 },
    };

    const addedObject = world.addObject(object);
    object.position.x = 7;
    object.attributes.weight = 99;
    addedObject.position.y = 7;
    addedObject.attributes.weight = 42;

    expect(world.snapshot().objects.find((candidate) => candidate.id === "bench_mutable")).toEqual({
      id: "bench_mutable",
      type: "bench",
      position: { x: 3, y: 2 },
      spriteKey: "bench",
      attributes: { weight: 2 },
    });
  });

  it("isolates world state from observation and snapshot mutation", () => {
    const world = new GridWorld({ width: 8, height: 8 });
    const cog = world.addCog({
      name: "Observer",
      spriteSheetKey: "cog-observer",
      controllerId: "stub",
      attributes: { energy: 5 },
      position: { x: 2, y: 2 },
    });

    const observation = world.getObservation(cog.id);
    observation.cog.position.x = 7;
    observation.cog.attributes.energy = 99;

    const snapshot = world.snapshot();
    snapshot.dimensions.width = 1;
    snapshot.cogs[0].position.y = 7;
    snapshot.cogs[0].attributes.energy = 42;

    const nextSnapshot = world.snapshot();
    expect(nextSnapshot.dimensions).toEqual({ width: 8, height: 8 });
    expect(nextSnapshot.cogs.find((candidate) => candidate.id === cog.id)?.position).toEqual({ x: 2, y: 2 });
    expect(nextSnapshot.cogs.find((candidate) => candidate.id === cog.id)?.attributes.energy).toBe(5);
  });

  it("rejects duplicate object IDs", () => {
    const world = new GridWorld({ width: 8, height: 8 });
    const object: WorldObject = {
      id: "bench_duplicate",
      type: "bench",
      position: { x: 1, y: 1 },
      spriteKey: "bench",
      attributes: {},
    };

    world.addObject(object);

    expect(() => world.addObject({ ...object, position: { x: 2, y: 2 } })).toThrow("Object ID already exists");
  });
});

async function stepUntilNotMoving(
  world: GridWorld,
  cogId: string,
  maxSteps = legacyHalfSecondTicksToSimulationTicks(80),
): Promise<WorldSnapshot> {
  let snapshot = world.snapshot();
  for (let step = 0; step <= maxSteps; step += 1) {
    const cog = snapshot.cogs.find((candidate) => candidate.id === cogId);
    if (!cog?.moving) {
      return snapshot;
    }
    snapshot = await world.step(new Map());
  }
  throw new Error(`Cog ${cogId} stayed moving after ${maxSteps} ticks`);
}

function twoRoomVenue(id: string, from: { x: number; y: number }, to: { x: number; y: number }): VenueLayout {
  return {
    rooms: [
      { id: "room-a", label: `Room A ${id}`, kind: "lounge", spotIds: ["a"], neighborIds: ["room-b"] },
      { id: "room-b", label: `Room B ${id}`, kind: "lounge", spotIds: ["b"], neighborIds: ["room-a"] },
    ],
    spots: [
      { id: "a", roomId: "room-a", label: "A", position: from },
      { id: "b", roomId: "room-b", label: "B", position: to },
    ],
    spotLinks: [],
    roomPaths: [{ id: "room-a__room-b", fromRoomId: "room-a", toRoomId: "room-b", points: [] }],
  };
}
