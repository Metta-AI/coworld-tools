import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { GridWorld } from "../../src/server/simulation/world.js";
import { createSqliteWorldStateStore } from "../../src/server/world-state-store.js";
import type { Cog, CogAction, WorldSnapshot } from "../../src/shared/types.js";

const FAST_DEBATE_CONFIG = {
  debatePrepTicks: 0,
  debateChoiceRevealTicks: 0,
  debateResultTicks: 0,
};

type DebateLogSnapshot = WorldSnapshot & {
  debateLog?: Array<{
    tick: number;
    round: number;
    outcome: string;
    winnerCogId?: string;
    actions: Array<{
      cogId: string;
      cogName: string;
      color: string;
      tactic: string;
    }>;
    changes: Array<{
      cogId: string;
      cogName: string;
      role: string;
      colorBefore: string;
      colorAfter: string;
      certaintyBefore: number;
      certaintyAfter: number;
      certaintyDelta: number;
    }>;
    conversions: Array<{
      cogId: string;
      cogName: string;
      fromColor: string;
      toColor: string;
    }>;
  }>;
};

describe("debate log", () => {
  it("records who debated, what got played, and the resulting certainty deltas", async () => {
    const world = new GridWorld(
      { width: 6, height: 6 },
      { ...FAST_DEBATE_CONFIG, debateDoubt: 10, debateWinCertaintyGain: 5, conversionThreshold: 1000 },
    );
    const red = addCog(world, { name: "Red", color: "red", position: { x: 2, y: 2 } });
    const blue = addCog(world, { name: "Blue", color: "blue", position: { x: 3, y: 2 } });

    await world.step(new Map<string, CogAction>([[red.id, debate(blue.id)]]));
    const state = world.exportState();
    const stateRed = state.cogs.find((cog) => cog.id === red.id);
    const stateBlue = state.cogs.find((cog) => cog.id === blue.id);
    if (!stateRed || !stateBlue) {
      throw new Error("Expected debate cogs");
    }
    stateRed.certainty = 480;
    stateBlue.certainty = 496;

    const restored = GridWorld.fromState(state);
    const snapshot = (await restored.step(
      new Map<string, CogAction>([
        [red.id, chooseTactic("reason")],
        [blue.id, chooseTactic("spin")],
      ]),
    )) as DebateLogSnapshot;

    expect(snapshot.debateLog).toHaveLength(1);
    expect(snapshot.debateLog?.[0]).toMatchObject({
      tick: 2,
      round: 1,
      outcome: "win",
      winnerCogId: red.id,
      actions: [
        { cogId: red.id, cogName: "Red", color: "red", tactic: "reason" },
        { cogId: blue.id, cogName: "Blue", color: "blue", tactic: "spin" },
      ],
      changes: [
        {
          cogId: red.id,
          cogName: "Red",
          role: "participant",
          colorBefore: "red",
          colorAfter: "red",
          certaintyBefore: 480,
          certaintyAfter: 485,
          certaintyDelta: 5,
        },
        {
          cogId: blue.id,
          cogName: "Blue",
          role: "participant",
          colorBefore: "blue",
          colorAfter: "blue",
          certaintyBefore: 496,
          certaintyAfter: 486,
          certaintyDelta: -10,
        },
      ],
      conversions: [],
    });
  });

  it("records color conversions caused by debate rounds", async () => {
    const world = new GridWorld(
      { width: 6, height: 6 },
      { ...FAST_DEBATE_CONFIG, debateDoubt: 2, conversionThreshold: 10 },
    );
    const red = addCog(world, { name: "Red", color: "red", position: { x: 2, y: 2 } });
    const blue = addCog(world, { name: "Blue", color: "blue", position: { x: 3, y: 2 } });

    await world.step(new Map<string, CogAction>([[red.id, debate(blue.id)]]));
    const state = world.exportState();
    const stateBlue = state.cogs.find((cog) => cog.id === blue.id);
    if (!stateBlue) {
      throw new Error("Expected blue cog");
    }
    stateBlue.certainty = 1;

    const restored = GridWorld.fromState(state);
    const snapshot = (await restored.step(
      new Map<string, CogAction>([
        [red.id, chooseTactic("reason")],
        [blue.id, chooseTactic("spin")],
      ]),
    )) as DebateLogSnapshot;

    expect(snapshot.debateLog?.[0]?.conversions).toEqual([
      expect.objectContaining({
        cogId: blue.id,
        cogName: "Blue",
        fromColor: "blue",
        toColor: "red",
      }),
    ]);
  });

  it("persists debate log entries in sqlite world state", async () => {
    const tempDir = mkdtempSync(path.join(tmpdir(), "cogshambo-debate-log-"));
    const dbPath = path.join(tempDir, "cogshambo.sqlite");
    try {
      const world = new GridWorld(
        { width: 6, height: 6 },
        { ...FAST_DEBATE_CONFIG, debateDoubt: 10, conversionThreshold: 1000 },
      );
      const red = addCog(world, { name: "Red", color: "red", position: { x: 2, y: 2 } });
      const blue = addCog(world, { name: "Blue", color: "blue", position: { x: 3, y: 2 } });

      await world.step(new Map<string, CogAction>([[red.id, debate(blue.id)]]));
      await world.step(
        new Map<string, CogAction>([
          [red.id, chooseTactic("reason")],
          [blue.id, chooseTactic("spin")],
        ]),
      );

      const store = createSqliteWorldStateStore(dbPath);
      store.save(world);
      store.close();

      const reloaded = createSqliteWorldStateStore(dbPath);
      const restored = reloaded.load();

      expect((restored?.snapshot() as DebateLogSnapshot | undefined)?.debateLog).toHaveLength(1);
      expect((restored?.snapshot() as DebateLogSnapshot | undefined)?.debateLog?.[0]?.actions[0]).toMatchObject({
        cogId: red.id,
        tactic: "reason",
      });

      reloaded.close();
    } finally {
      rmSync(tempDir, { recursive: true, force: true });
    }
  });
});

function addCog(
  world: GridWorld,
  input: {
    name: string;
    color: "red" | "blue";
    position: { x: number; y: number };
  },
): Cog {
  return world.addCog({
    name: input.name,
    spriteSheetKey: `cog-${input.name.toLowerCase()}`,
    controllerId: "stub",
    attributes: { energy: 5 },
    color: input.color,
    defensiveTrait: "avenger",
    activeTrait: "avenger",
    personalGoal: "majority",
    position: input.position,
  });
}

function debate(targetId: string): CogAction {
  return { type: "debate", targetId };
}

function chooseTactic(tactic: "reason" | "spin" | "passion"): CogAction {
  return { type: "chooseTactic", tactic };
}
