import { describe, expect, it } from "vitest";

import { colorForKey } from "../../src/client/render/atlas";
import { boardShader } from "../../src/client/render/shaders";
import { venueMovementPositionForRender } from "../../src/client/render/venue-movement";
import { createBoardInstancesForTest } from "../../src/client/render/webgpu-board-renderer";
import { SIMULATION_TICK_MS, secondsToSimulationTicks } from "../../src/shared/timing";
import type { Cog, WorldSnapshot } from "../../src/shared/types";

const baseCog: Omit<Cog, "color" | "debate" | "id" | "name" | "position"> = {
  activeTrait: "rationalist",
  activity: "idle",
  attributes: {},
  behaviorPrompt: "",
  controllerId: "stub",
  conversationLog: [],
  defensiveTrait: "stubborn",
  certainty: 100,
  goalScores: [],
  movementCooldown: 0,
  personalGoal: "majority",
  personalScore: 0,
  spriteSheetKey: "missing-test-sprite",
  stats: { argumentsLost: 0, argumentsWon: 0, teamFlips: 0 },
  ticksAlive: secondsToSimulationTicks(60),
};

describe("board renderer", () => {
  it("keeps WebGPU texture sampling outside per-instance render-mode branches", () => {
    const sampleIndex = boardShader.indexOf("let spriteColor = textureSample");
    const textureModeBranchIndex = boardShader.indexOf("if (input.textureMix > 0.5)");

    expect(sampleIndex).toBeGreaterThan(-1);
    expect(textureModeBranchIndex).toBeGreaterThan(sampleIndex);
  });

  it("does not draw legacy map object markers over venue art", () => {
    const redCog = cog({
      color: "red",
      id: "red-cog",
      name: "Red Cog",
      position: { x: 3, y: 3 },
    });
    const markerObject: WorldSnapshot["objects"][number] = {
      id: "conference_table",
      type: "picknick",
      position: { x: 13, y: 8 },
      spriteKey: "map-object-marker",
      attributes: {},
    };

    const withoutMarker = createBoardInstancesForTest(snapshot([redCog], { venue: testVenue }), {
      selectedCogId: undefined,
    });
    const withMarker = createBoardInstancesForTest(snapshot([redCog], { objects: [markerObject], venue: testVenue }), {
      selectedCogId: undefined,
    });

    expect(withMarker).toEqual(withoutMarker);
  });

  it("renders debating cogs with the same neutral halo color", () => {
    const red = cog({
      color: "red",
      debate: { opponentId: "blue", startedTick: 0, nextRoundTick: 20, roundsResolved: 0 },
      id: "red",
      name: "Red",
      position: { x: 3, y: 3 },
    });
    const blue = cog({
      color: "blue",
      debate: { opponentId: "red", startedTick: 0, nextRoundTick: 20, roundsResolved: 0 },
      id: "blue",
      name: "Blue",
      position: { x: 5, y: 3 },
    });
    const idle = cog({
      color: "red",
      id: "idle",
      name: "Idle",
      position: { x: 7, y: 3 },
    });

    const instances = createBoardInstancesForTest(snapshot([red, blue, idle]), {
      selectedCogId: undefined,
    });

    const debateHalos = instances.filter((instance) => instance.role === "debate-halo");
    expect(debateHalos).toHaveLength(2);
    expect(debateHalos.map((instance) => instance.cogId).sort()).toEqual(["blue", "red"]);
    expect(debateHalos.map((instance) => instance.color)).toEqual([colorForKey("debate"), colorForKey("debate")]);
    expect(debateHalos[0]?.color).not.toEqual(colorForKey("team-red"));
    expect(debateHalos[0]?.color).not.toEqual(colorForKey("team-blue"));
  });

  it("renders team-colored hats on every cog", () => {
    const redCog = cog({
      color: "red",
      id: "red-cog",
      name: "Red Cog",
      position: { x: 3, y: 3 },
    });
    const blueCog = cog({
      color: "blue",
      id: "blue-cog",
      name: "Blue Cog",
      position: { x: 5, y: 3 },
    });
    const otherRedCog = cog({
      color: "red",
      id: "other-red-cog",
      name: "Other Red Cog",
      position: { x: 7, y: 3 },
    });

    const instances = createBoardInstancesForTest(snapshot([redCog, blueCog, otherRedCog]), {
      selectedCogId: undefined,
    });

    const hats = instances.filter((instance) => instance.role === "team-hat");
    expect(hats).toHaveLength(6);
    expect(hats.filter((instance) => instance.cogId === "red-cog").map((instance) => instance.color)).toEqual([
      colorForKey("team-red"),
      colorForKey("team-red"),
    ]);
    expect(hats.filter((instance) => instance.cogId === "blue-cog").map((instance) => instance.color)).toEqual([
      colorForKey("team-blue"),
      colorForKey("team-blue"),
    ]);
    expect(hats.filter((instance) => instance.cogId === "other-red-cog").map((instance) => instance.color)).toEqual([
      colorForKey("team-red"),
      colorForKey("team-red"),
    ]);
  });

  it("switches to rainbow triangle party hats in disco mode", () => {
    const redCog = cog({
      color: "red",
      id: "red-cog",
      name: "Red Cog",
      position: { x: 3, y: 3 },
    });
    const blueCog = cog({
      color: "blue",
      id: "blue-cog",
      name: "Blue Cog",
      position: { x: 5, y: 3 },
    });

    const instances = createBoardInstancesForTest(snapshot([redCog, blueCog]), {
      discoMode: true,
      selectedCogId: undefined,
    });

    const partyHats = instances.filter((instance) => instance.role === "party-hat");
    expect(partyHats).toHaveLength(2);
    expect(partyHats.map((instance) => instance.cogId).sort()).toEqual(["blue-cog", "red-cog"]);
    expect(partyHats.map((instance) => instance.color)).toEqual([
      [1, 1, 1, 1],
      [1, 1, 1, 1],
    ]);
    expect(partyHats.find((instance) => instance.cogId === "red-cog")?.color).not.toEqual(colorForKey("team-red"));
    expect(partyHats.find((instance) => instance.cogId === "blue-cog")?.color).not.toEqual(colorForKey("team-blue"));
    expect(partyHats.every((instance) => instance.textureMix === -4)).toBe(true);
    expect(partyHats.every((instance) => instance.size[1] > instance.size[0])).toBe(true);
    expect(instances.some((instance) => instance.role === "team-hat")).toBe(false);
    expect(boardShader).toContain("partyHatRainbowColor");
  });

  it("renders moving disco ball light spots over the venue in disco mode", () => {
    const red = cog({
      color: "red",
      id: "red",
      name: "Red",
      position: { x: 3, y: 3 },
    });

    const firstFrame = createBoardInstancesForTest(snapshot([red], { venue: testVenue }), {
      discoLightTimeMs: 0,
      discoMode: true,
      selectedCogId: undefined,
    });
    const secondFrame = createBoardInstancesForTest(snapshot([red], { venue: testVenue }), {
      discoLightTimeMs: 1_250,
      discoMode: true,
      selectedCogId: undefined,
    });
    const disabled = createBoardInstancesForTest(snapshot([red], { venue: testVenue }), {
      discoLightTimeMs: 0,
      discoMode: false,
      selectedCogId: undefined,
    });

    const firstLights = firstFrame.filter((instance) => (instance.role as string | undefined) === "disco-light");
    const secondLights = secondFrame.filter((instance) => (instance.role as string | undefined) === "disco-light");

    expect(firstLights).toHaveLength(28);
    expect(disabled.some((instance) => (instance.role as string | undefined) === "disco-light")).toBe(false);
    expect(secondLights).toHaveLength(firstLights.length);
    expect(secondLights.map((instance) => instance.center)).not.toEqual(firstLights.map((instance) => instance.center));
    expect(new Set(firstLights.map((instance) => instance.color.join(","))).size).toBeGreaterThan(4);
  });

  it("walks newly spawned cogs from the left through the lobby entrance", () => {
    const freshCog = cog({
      color: "red",
      id: "fresh-cog",
      name: "Fresh Cog",
      position: { x: 6, y: 2 },
      ticksAlive: 0,
    });
    const settledCog = cog({
      ...freshCog,
      id: "settled-cog",
      ticksAlive: secondsToSimulationTicks(6),
    });

    const freshInstances = createBoardInstancesForTest(snapshot([freshCog], { venue: lobbyEntranceVenue }), {
      selectedCogId: undefined,
    });
    const settledInstances = createBoardInstancesForTest(snapshot([settledCog], { venue: lobbyEntranceVenue }), {
      selectedCogId: undefined,
    });

    const freshHalo = freshInstances.find((instance) => instance.role === "spawn-halo" && instance.cogId === "fresh-cog");
    const settledHat = settledInstances.find((instance) => instance.role === "team-hat" && instance.cogId === "settled-cog");
    const freshHat = freshInstances.find((instance) => instance.role === "team-hat" && instance.cogId === "fresh-cog");

    expect(freshHalo).toBeDefined();
    expect(freshHat?.center[0]).toBeLessThan(settledHat?.center[0] ?? -Infinity);
    expect(freshHalo?.center[1]).toBeLessThan(settledHat?.center[1] ?? -Infinity);
  });

  it("renders a spawn halo for the first thirty seconds", () => {
    const freshCog = cog({
      color: "red",
      id: "fresh-cog",
      name: "Fresh Cog",
      position: { x: 6, y: 2 },
      ticksAlive: 0,
    });
    const almostSettledCog = cog({
      ...freshCog,
      id: "almost-settled-cog",
      ticksAlive: secondsToSimulationTicks(30) - 1,
    });
    const settledCog = cog({
      ...freshCog,
      id: "settled-cog",
      ticksAlive: secondsToSimulationTicks(30),
    });

    const instances = createBoardInstancesForTest(snapshot([freshCog, almostSettledCog, settledCog], { venue: lobbyEntranceVenue }), {
      selectedCogId: undefined,
    });

    expect(instances.filter((instance) => instance.role === "spawn-halo").map((instance) => instance.cogId).sort()).toEqual([
      "almost-settled-cog",
      "fresh-cog",
    ]);
  });

  it("keeps new-cog lobby entry animation from rewinding when a delayed snapshot arrives", () => {
    const enteringCog = cog({
      color: "red",
      id: "entering-cog",
      name: "Entering Cog",
      position: { x: 6, y: 2 },
      ticksAlive: 0,
    });
    const firstSeenAtMs = 1_000;
    const delayedFrameMs = firstSeenAtMs + SIMULATION_TICK_MS * 8;

    const locallyAdvanced = createBoardInstancesForTest(
      snapshot([enteringCog], { tick: 20, venue: lobbyEntranceVenue }),
      { discoLightTimeMs: delayedFrameMs, selectedCogId: undefined },
      { snapshotSeenAtMs: firstSeenAtMs },
    );
    const afterFreshSnapshot = createBoardInstancesForTest(
      snapshot([{ ...enteringCog, ticksAlive: 1 }], { tick: 21, venue: lobbyEntranceVenue }),
      { discoLightTimeMs: delayedFrameMs, selectedCogId: undefined },
      {
        snapshotSeenAtMs: delayedFrameMs,
        spawnTimingForCog: () => ({
          spawnSeenAtMs: firstSeenAtMs,
          spawnSeenTicksAlive: 0,
        }),
      },
    );

    expect(teamHatX(afterFreshSnapshot, "entering-cog")).toBeGreaterThanOrEqual(
      teamHatX(locallyAdvanced, "entering-cog") - 0.001,
    );
  });

  it("interpolates venue movement along the stored route at a fixed walking rate", () => {
    const moving = cog({
      color: "red",
      id: "walker",
      name: "Walker",
      position: { x: 1, y: 3 },
      moving: {
        from: { roomId: "room-a", spotId: "a" },
        to: { roomId: "room-b", spotId: "b" },
        fromPosition: { x: 1, y: 1 },
        toPosition: { x: 9, y: 5 },
        path: [{ x: 1, y: 1 }, { x: 1, y: 5 }, { x: 9, y: 5 }],
        startedTick: 10,
        arriveTick: 10 + secondsToSimulationTicks(10),
      },
    });

    expectPositionCloseTo(venueMovementPositionForRender(moving, 11, 1_000, 1_000), { x: 1, y: 1.6 });
    expectPositionCloseTo(venueMovementPositionForRender(moving, 11, 1_000, 1_000 + SIMULATION_TICK_MS / 2), {
      x: 1,
      y: 1.9,
    });
    expectPositionCloseTo(venueMovementPositionForRender(moving, 11, 1_000, 1_000 + SIMULATION_TICK_MS * 2), {
      x: 1,
      y: 2.8,
    });
    expectPositionCloseTo(venueMovementPositionForRender(moving, 20, 1_000, 1_000), { x: 3, y: 5 });
  });

  it("keeps venue movement from rewinding when a newer snapshot arrives after local interpolation", () => {
    const moving = cog({
      color: "red",
      id: "walker",
      name: "Walker",
      position: { x: 1, y: 1 },
      moving: {
        from: { roomId: "room-a", spotId: "a" },
        to: { roomId: "room-b", spotId: "b" },
        fromPosition: { x: 1, y: 1 },
        toPosition: { x: 9, y: 1 },
        path: [{ x: 1, y: 1 }, { x: 9, y: 1 }],
        startedTick: 10,
        arriveTick: 20,
      },
    });
    const firstSeenAtMs = 1_000;
    const delayedFrameMs = firstSeenAtMs + SIMULATION_TICK_MS * 2;

    const interpolated = venueMovementPositionForRender(moving, 11, firstSeenAtMs, delayedFrameMs, firstSeenAtMs, 11);
    const afterFreshSnapshot = venueMovementPositionForRender(
      moving,
      12,
      delayedFrameMs,
      delayedFrameMs,
      firstSeenAtMs,
      11,
    );

    expect(afterFreshSnapshot.x).toBeGreaterThanOrEqual(interpolated.x);
    expect(afterFreshSnapshot.y).toBeCloseTo(interpolated.y, 3);
  });

  it("advances WebGPU venue movement at render frame time between game-clock snapshots", () => {
    const moving = cog({
      color: "red",
      id: "walker",
      name: "Walker",
      position: { x: 1, y: 1.6 },
      moving: {
        from: { roomId: "room-a", spotId: "a" },
        to: { roomId: "room-b", spotId: "b" },
        fromPosition: { x: 1, y: 1 },
        toPosition: { x: 9, y: 5 },
        path: [{ x: 1, y: 1 }, { x: 1, y: 5 }, { x: 9, y: 5 }],
        startedTick: 10,
        arriveTick: 10 + secondsToSimulationTicks(10),
      },
    });
    const movingSnapshot = snapshot([moving], { tick: 11, venue: testVenue });

    const firstFrame = createBoardInstancesForTest(
      movingSnapshot,
      { discoLightTimeMs: 1_000, selectedCogId: undefined },
      { snapshotSeenAtMs: 1_000 },
    );
    const secondFrame = createBoardInstancesForTest(
      movingSnapshot,
      { discoLightTimeMs: 1_000 + SIMULATION_TICK_MS * 2, selectedCogId: undefined },
      { snapshotSeenAtMs: 1_000 },
    );

    const firstHatCenter = firstFrame.find((instance) => instance.role === "team-hat" && instance.cogId === "walker")?.center;
    const secondHatCenter = secondFrame.find((instance) => instance.role === "team-hat" && instance.cogId === "walker")?.center;

    expect(firstHatCenter).toBeDefined();
    expect(secondHatCenter).toBeDefined();
    expect(secondHatCenter).not.toEqual(firstHatCenter);
  });
});

function expectPositionCloseTo(actual: { x: number; y: number }, expected: { x: number; y: number }): void {
  expect(actual.x).toBeCloseTo(expected.x, 3);
  expect(actual.y).toBeCloseTo(expected.y, 3);
}

function teamHatX(instances: ReturnType<typeof createBoardInstancesForTest>, cogId: string): number {
  const hat = instances.find((instance) => instance.role === "team-hat" && instance.cogId === cogId);
  expect(hat).toBeDefined();
  return hat!.center[0];
}

function cog(overrides: Pick<Cog, "color" | "id" | "name" | "position"> & Partial<Cog>): Cog {
  return {
    ...baseCog,
    ...overrides,
  };
}

function snapshot(cogs: Cog[], overrides: Partial<WorldSnapshot> = {}): WorldSnapshot {
  return {
    cogs,
    dimensions: { width: 10, height: 8 },
    objects: [],
    recentEvents: [],
    terrain: [],
    tick: 1,
    ...overrides,
  };
}

const testVenue: WorldSnapshot["venue"] = {
  rooms: [
    { id: "floor", label: "Dance Floor", kind: "stage", neighborIds: [], spotIds: ["center"] },
  ],
  spots: [
    { id: "center", roomId: "floor", label: "Center", position: { x: 5, y: 4 } },
  ],
  spotLinks: [],
  roomPaths: [],
};

const lobbyEntranceVenue: WorldSnapshot["venue"] = {
  rooms: [
    { id: "lobby_entry", label: "Lobby Entry", kind: "walkway", neighborIds: ["floor"], spotIds: ["lobby_entry_door"] },
    { id: "floor", label: "Floor", kind: "stage", neighborIds: ["lobby_entry"], spotIds: ["target"] },
  ],
  spots: [
    { id: "lobby_entry_door", roomId: "lobby_entry", label: "front doors", position: { x: 1, y: 5 } },
    { id: "target", roomId: "floor", label: "Target", position: { x: 6, y: 2 } },
  ],
  spotLinks: [],
  roomPaths: [],
};
