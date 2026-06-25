import { describe, expect, it } from "vitest";

import { createCogRequestSchema } from "../../src/shared/protocol";
import { legacyHalfSecondTicksToSimulationTicks } from "../../src/shared/timing";
import type { CogAction, VenueLayout, WorldSnapshot } from "../../src/shared/types";
import { createSeedWorld } from "../../src/server/simulation/seed-world";
import { GridWorld } from "../../src/server/simulation/world";

function actionMap(entries: Array<[string, CogAction]>): Map<string, CogAction> {
  return new Map(entries);
}

function isEdge(position: { x: number; y: number }, width: number, height: number): boolean {
  return position.x === 0 || position.y === 0 || position.x === width - 1 || position.y === height - 1;
}

function mutableCog(world: GridWorld, cogId: string) {
  const cog = (world as unknown as { cogs: Map<string, { certainty: number }> }).cogs.get(cogId);
  if (!cog) {
    throw new Error(`Missing cog ${cogId}`);
  }
  return cog;
}

const FAST_DEBATE_CONFIG = {
  debatePrepTicks: 0,
  debateChoiceRevealTicks: 0,
  debateResultTicks: 0,
};

const TWO_ROOM_VENUE: VenueLayout = {
  rooms: [
    { id: "room-a", label: "Room A", kind: "lounge", spotIds: ["a1", "a2"], neighborIds: ["room-b"] },
    { id: "room-b", label: "Room B", kind: "lounge", spotIds: ["b1", "b2"], neighborIds: ["room-a"] },
  ],
  spots: [
    { id: "a1", roomId: "room-a", label: "A1", position: { x: 1, y: 1 } },
    { id: "a2", roomId: "room-a", label: "A2", position: { x: 2, y: 1 } },
    { id: "b1", roomId: "room-b", label: "B1", position: { x: 5, y: 1 } },
    { id: "b2", roomId: "room-b", label: "B2", position: { x: 6, y: 1 } },
  ],
  spotLinks: [],
  roomPaths: [{ id: "a-b", fromRoomId: "room-a", toRoomId: "room-b", points: [{ x: 4, y: 1 }] }],
};

describe("adapted game rules", () => {
  it("spawns new cogs on empty edge tiles and fails when no edge tile is open", () => {
    const world = new GridWorld({ width: 3, height: 3 });
    const edgeTiles = [
      { x: 0, y: 0 },
      { x: 1, y: 0 },
      { x: 2, y: 0 },
      { x: 0, y: 1 },
      { x: 2, y: 1 },
      { x: 0, y: 2 },
      { x: 1, y: 2 },
      { x: 2, y: 2 },
    ];

    for (const [index, position] of edgeTiles.entries()) {
      const cog = world.addCog({
        name: `edge-${index}`,
        position,
        color: index % 2 === 0 ? "red" : "blue",
      });
      expect(isEdge(cog.position, 3, 3)).toBe(true);
    }

    expect(() => world.addCog({ name: "center-only" })).toThrow(/edge/i);
  });

  it("preserves user-authored behavior prompts in create requests and observations", () => {
    const parsed = createCogRequestSchema.parse({
      name: "Pith",
      behaviorPrompt: "Prefer debates near sand and narrate briefly.",
    });
    expect(parsed.behaviorPrompt).toBe("Prefer debates near sand and narrate briefly.");

    const world = new GridWorld({ width: 6, height: 6 });
    const cog = world.addCog({
      name: "Pith",
      behaviorPrompt: parsed.behaviorPrompt,
      position: { x: 0, y: 0 },
    } as never);

    expect((cog as { behaviorPrompt?: string }).behaviorPrompt).toBe(parsed.behaviorPrompt);
    expect((world.getObservation(cog.id).cog as { behaviorPrompt?: string }).behaviorPrompt).toBe(
      parsed.behaviorPrompt,
    );
  });

  it("blocks walls and delays the next movement after entering sand", async () => {
    const world = new GridWorld({ width: 5, height: 5 });
    (world as unknown as { setTerrain: (position: { x: number; y: number }, terrain: string) => void }).setTerrain(
      { x: 2, y: 1 },
      "wall",
    );
    (world as unknown as { setTerrain: (position: { x: number; y: number }, terrain: string) => void }).setTerrain(
      { x: 1, y: 2 },
      "sand",
    );

    const cog = world.addCog({
      name: "Trex",
      position: { x: 1, y: 1 },
      color: "red",
      activeTrait: "rationalist",
    });

    let snapshot = await world.step(actionMap([[cog.id, { type: "move", direction: "east" }]]));
    expect(snapshot.cogs.find((candidate) => candidate.id === cog.id)?.position).toEqual({ x: 1, y: 1 });

    snapshot = await world.step(actionMap([[cog.id, { type: "move", direction: "south" }]]));
    expect(snapshot.cogs.find((candidate) => candidate.id === cog.id)?.position).toEqual({ x: 1, y: 2 });

    snapshot = await world.step(actionMap([[cog.id, { type: "move", direction: "south" }]]));
    expect(snapshot.cogs.find((candidate) => candidate.id === cog.id)?.position).toEqual({ x: 1, y: 2 });

    snapshot = await world.step(actionMap([[cog.id, { type: "move", direction: "south" }]]));
    expect(snapshot.cogs.find((candidate) => candidate.id === cog.id)?.position).toEqual({ x: 1, y: 3 });
  });

  it("keeps certainty stable over idle ticks for cogs without recovery traits", async () => {
    const world = new GridWorld({ width: 8, height: 8 }, FAST_DEBATE_CONFIG);
    const red = world.addCog({
      name: "Red",
      position: { x: 2, y: 2 },
      color: "red",
      activeTrait: "rationalist",
    });
    const blue = world.addCog({
      name: "Blue",
      position: { x: 3, y: 2 },
      color: "blue",
      defensiveTrait: "iconoclast",
    });

    await world.step(actionMap([[red.id, { type: "debate", targetId: blue.id }]]));
    await world.step(
      actionMap([
        [red.id, { type: "chooseTactic", tactic: "reason" }],
        [blue.id, { type: "chooseTactic", tactic: "spin" }],
      ]),
    );
    for (let round = 0; round < 4; round += 1) {
      await world.step(
        actionMap([
          [red.id, { type: "chooseTactic", tactic: "passion" }],
          [blue.id, { type: "chooseTactic", tactic: "passion" }],
        ]),
      );
    }

    const beforeIdle = world.snapshot().cogs.find((cog) => cog.id === blue.id)?.certainty ?? 0;
    await world.step(new Map());
    const afterIdle = world.snapshot().cogs.find((cog) => cog.id === blue.id)?.certainty ?? 0;

    expect(beforeIdle).toBeLessThan(100);
    expect(afterIdle).toBe(beforeIdle);
  });

  it("does not apply passive charisma witness certainty changes over idle ticks", async () => {
    expect(createCogRequestSchema.parse({ name: "Contra", activeTrait: "contrarian" }).activeTrait).toBe(
      "contrarian",
    );

    const world = new GridWorld({ width: 5, height: 5 });
    world.addCog({
      name: "Contra",
      position: { x: 2, y: 2 },
      color: "red",
      activeTrait: "contrarian",
    });
    const blue = world.addCog({
      name: "Blue",
      position: { x: 3, y: 2 },
      color: "blue",
    });
    mutableCog(world, blue.id).certainty = 95;

    const snapshot = await world.step(new Map());
    const observedBlue = snapshot.cogs.find((cog) => cog.id === blue.id);

    expect(observedBlue?.certainty).toBe(95);
  });

  it("does not apply passive certainty loss from charismatic cogs", async () => {
    const world = new GridWorld({ width: 5, height: 5 });
    world.addCog({
      name: "Red",
      position: { x: 2, y: 2 },
      color: "red",
      activeTrait: "charismatic",
    });
    const blue = world.addCog({
      name: "Blue",
      position: { x: 3, y: 2 },
      color: "blue",
      defensiveTrait: "stubborn",
    });

    const snapshot = await world.step(new Map());

    expect(snapshot.cogs.find((cog) => cog.id === blue.id)?.certainty).toBe(100);
  });

  it("insular cogs can convert when direct debate certainty reaches zero", async () => {
    const world = new GridWorld({ width: 5, height: 5 }, FAST_DEBATE_CONFIG);
    const red = world.addCog({
      name: "Red",
      position: { x: 2, y: 2 },
      color: "red",
      activeTrait: "avenger",
    });
    const insular = world.addCog({
      name: "Insular",
      position: { x: 3, y: 2 },
      color: "blue",
      defensiveTrait: "insular",
    });
    mutableCog(world, insular.id).certainty = 2;

    await world.step(new Map([[red.id, { type: "debate", targetId: insular.id }]]));
    const snapshot = await world.step(
      new Map([
        [red.id, { type: "chooseTactic", tactic: "reason" }],
        [insular.id, { type: "chooseTactic", tactic: "spin" }],
      ]),
    );
    const observedInsular = snapshot.cogs.find((cog) => cog.id === insular.id);

    expect(observedInsular?.color).toBe("red");
  });

  it("uses configured direct certainty-loss multipliers for stubborn and forceful traits", async () => {
    const world = new GridWorld(
      { width: 5, height: 5 },
      {
        ...FAST_DEBATE_CONFIG,
        traitConfig: {
          forceful: { winDoubtMultiplier: 2 },
          stubborn: { directDoubtMultiplier: 0.5 },
        },
      },
    );
    const red = world.addCog({
      name: "Force",
      position: { x: 2, y: 2 },
      color: "red",
      activeTrait: "forceful",
    });
    const blue = world.addCog({
      name: "Stubborn",
      position: { x: 3, y: 2 },
      color: "blue",
      defensiveTrait: "stubborn",
    });

    await world.step(new Map([[red.id, { type: "debate", targetId: blue.id }]]));
    const snapshot = await world.step(
      new Map([
        [red.id, { type: "chooseTactic", tactic: "reason" }],
        [blue.id, { type: "chooseTactic", tactic: "spin" }],
      ]),
    );

    expect(snapshot.cogs.find((cog) => cog.id === blue.id)?.certainty).toBe(90);
  });

  it("uses contrarian cooldown config for repeat debate pairs", async () => {
    const world = new GridWorld(
      { width: 5, height: 5 },
      {
        ...FAST_DEBATE_CONFIG,
        maxDebateRounds: 1,
        debateCooldownTicks: 10,
        traitConfig: {
          contrarian: { debateCooldownMultiplier: 0 },
        },
      },
    );
    const red = world.addCog({
      name: "Contra",
      position: { x: 2, y: 2 },
      color: "red",
      activeTrait: "contrarian",
    });
    const blue = world.addCog({
      name: "Blue",
      position: { x: 3, y: 2 },
      color: "blue",
    });

    await world.step(new Map([[red.id, { type: "debate", targetId: blue.id }]]));
    await world.step(
      new Map([
        [red.id, { type: "chooseTactic", tactic: "passion" }],
        [blue.id, { type: "chooseTactic", tactic: "passion" }],
      ]),
    );
    await world.step(new Map([[blue.id, { type: "debate", targetId: red.id }]]));

    const snapshot = world.snapshot();
    expect(snapshot.cogs.find((cog) => cog.id === red.id)?.debate?.opponentId).toBe(blue.id);
    expect(snapshot.cogs.find((cog) => cog.id === blue.id)?.debate?.opponentId).toBe(red.id);
  });

  it("uses the global conversion uncertainty when an argument converts a cog", async () => {
    const world = new GridWorld(
      { width: 5, height: 5 },
      {
        ...FAST_DEBATE_CONFIG,
        conversionDoubtPercent: 50,
      },
    );
    const red = world.addCog({
      name: "Red",
      position: { x: 2, y: 2 },
      color: "red",
      activeTrait: "forceful",
    });
    const blue = world.addCog({
      name: "Blue",
      position: { x: 3, y: 2 },
      color: "blue",
    });
    mutableCog(world, blue.id).certainty = 2;

    await world.step(new Map([[red.id, { type: "debate", targetId: blue.id }]]));
    const snapshot = await world.step(
      new Map([
        [red.id, { type: "chooseTactic", tactic: "reason" }],
        [blue.id, { type: "chooseTactic", tactic: "spin" }],
      ]),
    );

    const convertedBlue = snapshot.cogs.find((cog) => cog.id === blue.id);
    expect(convertedBlue?.color).toBe("red");
    expect(convertedBlue?.certainty).toBe(50);
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
