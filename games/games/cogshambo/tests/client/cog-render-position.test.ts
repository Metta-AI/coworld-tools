import { describe, expect, it } from "vitest";

import { cogPositionForRender } from "../../src/client/render/cog-render-position";
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

describe("cog render position", () => {
  it("advances moving cog positions for overlay labels between server snapshots", () => {
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

    const position = cogPositionForRender(
      moving,
      snapshot([moving], { tick: 11 }),
      1_000 + SIMULATION_TICK_MS * 2,
      { snapshotSeenAtMs: 1_000 },
    );

    expect(position.y).toBeGreaterThan(moving.position.y);
    expect(position).toEqual(expect.objectContaining({ x: 1 }));
  });
});

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
