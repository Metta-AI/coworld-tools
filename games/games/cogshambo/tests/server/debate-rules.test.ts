import { describe, expect, it } from "vitest";
import type { Cog, CogAction, VenueLayout } from "../../src/shared/types.js";
import { GridWorld } from "../../src/server/simulation/world.js";
import { createCogRequestSchema } from "../../src/shared/protocol.js";
import { legacyHalfSecondTicksToSimulationTicks, secondsToSimulationTicks } from "../../src/shared/timing.js";

function addCog(
  world: GridWorld,
  input: {
    name: string;
    color: "red" | "blue";
    position: { x: number; y: number };
    defensiveTrait?: string;
    activeTrait?: string;
  },
): Cog {
  return world.addCog({
    name: input.name,
    spriteSheetKey: `cog-${input.name.toLowerCase()}`,
    controllerId: "stub",
    attributes: { energy: 5 },
    color: input.color,
    defensiveTrait: input.defensiveTrait ?? "avenger",
    activeTrait: input.activeTrait ?? "forceful",
    personalGoal: "majority",
    position: input.position,
  });
}

function addVenueCog(
  world: GridWorld,
  input: {
    name: string;
    color: "red" | "blue";
    roomId: string;
    spotId: string;
    defensiveTrait?: string;
    activeTrait?: string;
  },
): Cog {
  return world.addCog({
    name: input.name,
    spriteSheetKey: `cog-${input.name.toLowerCase()}`,
    controllerId: "stub",
    attributes: { energy: 5 },
    color: input.color,
    defensiveTrait: input.defensiveTrait ?? "stubborn",
    activeTrait: input.activeTrait ?? "forceful",
    personalGoal: "majority",
    location: { roomId: input.roomId, spotId: input.spotId },
  });
}

function witnessVenue(): VenueLayout {
  return {
    rooms: [
      { id: "room", label: "Room", kind: "lounge", spotIds: ["a", "b", "c"], neighborIds: ["other"] },
      { id: "other", label: "Other", kind: "table", spotIds: ["d"], neighborIds: ["room"] },
    ],
    spots: [
      { id: "a", roomId: "room", label: "A", position: { x: 2, y: 2 } },
      { id: "b", roomId: "room", label: "B", position: { x: 3, y: 2 } },
      { id: "c", roomId: "room", label: "C", position: { x: 7, y: 2 } },
      { id: "d", roomId: "other", label: "D", position: { x: 7, y: 7 } },
    ],
    spotLinks: [
      { id: "a__b", fromSpotId: "a", toSpotId: "b" },
      { id: "c__d", fromSpotId: "c", toSpotId: "d" },
    ],
  };
}

function debate(targetId: string): CogAction {
  return { type: "debate", targetId } as CogAction;
}

function chooseTactic(tactic: "reason" | "spin" | "passion"): CogAction {
  return { type: "chooseTactic", tactic } as CogAction;
}

const FAST_DEBATE_CONFIG = {
  debatePrepTicks: 0,
  debateChoiceRevealTicks: 0,
  debateResultTicks: 0,
};

describe("GridWorld debate rules", () => {
  it("blocks movement into occupied cog cells without changing certainty", async () => {
    const world = new GridWorld({ width: 6, height: 6 });
    const red = addCog(world, { name: "Red", color: "red", position: { x: 2, y: 2 } });
    const blue = addCog(world, { name: "Blue", color: "red", position: { x: 3, y: 2 } });

    const snapshot = await world.step(new Map<string, CogAction>([[red.id, { type: "move", direction: "east" }]]));
    const movedRed = snapshot.cogs.find((cog) => cog.id === red.id);
    const targetBlue = snapshot.cogs.find((cog) => cog.id === blue.id);

    expect(movedRed?.position).toEqual({ x: 2, y: 2 });
    expect(targetBlue?.certainty).toBe(100);
    expect(snapshot.recentEvents.at(-1)?.type).toBe("moveBlocked");
  });

  it("starts debate only with adjacent available cogs", async () => {
    const world = new GridWorld({ width: 6, height: 6 });
    const red = addCog(world, { name: "Red", color: "red", position: { x: 2, y: 2 } });
    const blue = addCog(world, { name: "Blue", color: "blue", position: { x: 3, y: 2 } });

    const snapshot = await world.step(new Map<string, CogAction>([[red.id, debate(blue.id)]]));
    const debatingRed = snapshot.cogs.find((cog) => cog.id === red.id);
    const debatingBlue = snapshot.cogs.find((cog) => cog.id === blue.id);

    expect(debatingRed?.debate?.opponentId).toBe(blue.id);
    expect(debatingBlue?.debate?.opponentId).toBe(red.id);
    expect(snapshot.recentEvents).toEqual(expect.arrayContaining([expect.objectContaining({ type: "debateStart" })]));
  });

  it("does not start debate with same-team cogs", async () => {
    const world = new GridWorld({ width: 6, height: 6 });
    const red = addCog(world, { name: "Red", color: "red", position: { x: 2, y: 2 } });
    const teammate = addCog(world, { name: "Teammate", color: "red", position: { x: 3, y: 2 } });

    const snapshot = await world.step(new Map<string, CogAction>([[red.id, debate(teammate.id)]]));
    const debatingRed = snapshot.cogs.find((cog) => cog.id === red.id);
    const debatingTeammate = snapshot.cogs.find((cog) => cog.id === teammate.id);

    expect(debatingRed?.debate).toBeUndefined();
    expect(debatingTeammate?.debate).toBeUndefined();
    expect(snapshot.recentEvents.some((event) => event.type === "debateStart")).toBe(false);
  });

  it("drops restored debates when opponents now share a team", async () => {
    const world = new GridWorld({ width: 6, height: 6 });
    const red = addCog(world, { name: "Red", color: "red", position: { x: 2, y: 2 } });
    const blue = addCog(world, { name: "Blue", color: "blue", position: { x: 3, y: 2 } });

    await world.step(new Map<string, CogAction>([[red.id, debate(blue.id)]]));
    const state = world.exportState();
    const restoredBlue = state.cogs.find((cog) => cog.id === blue.id);
    if (!restoredBlue) {
      throw new Error("Expected restored blue cog");
    }
    restoredBlue.color = "red";

    const restored = GridWorld.fromState(state);
    const restoredSnapshot = restored.snapshot();
    expect(restoredSnapshot.cogs.find((cog) => cog.id === red.id)?.debate).toBeUndefined();
    expect(restoredSnapshot.cogs.find((cog) => cog.id === blue.id)?.debate).toBeUndefined();

    const nextSnapshot = await restored.step(new Map());
    expect(nextSnapshot.recentEvents.some((event) => event.type === "debateExchange")).toBe(false);
    expect(nextSnapshot.cogs.some((cog) => cog.debate)).toBe(false);
  });

  it("resolves debate tactic choices simultaneously", async () => {
    const world = new GridWorld({ width: 6, height: 6 }, FAST_DEBATE_CONFIG);
    const red = addCog(world, { name: "Red", color: "red", position: { x: 2, y: 2 } });
    const blue = addCog(world, { name: "Blue", color: "blue", position: { x: 3, y: 2 } });

    await world.step(new Map<string, CogAction>([[red.id, debate(blue.id)]]));
    const snapshot = await world.step(
      new Map<string, CogAction>([
        [red.id, chooseTactic("reason")],
        [blue.id, chooseTactic("spin")],
      ]),
    );
    const debatingRed = snapshot.cogs.find((cog) => cog.id === red.id);
    const debatingBlue = snapshot.cogs.find((cog) => cog.id === blue.id);

    expect(debatingBlue?.certainty).toBeLessThan(100);
    expect(debatingRed?.certainty).toBeGreaterThan(debatingBlue?.certainty ?? 0);
    expect(debatingRed?.stats.argumentsWon).toBe(1);
    expect(debatingRed?.stats.argumentsLost).toBe(0);
    expect(debatingBlue?.stats.argumentsWon).toBe(0);
    expect(debatingBlue?.stats.argumentsLost).toBe(1);
    expect(debatingRed?.debate?.opponentId).toBe(blue.id);
    const debateExchange = snapshot.recentEvents.findLast((event) => event.type === "debateExchange");
    expect(debateExchange?.debate).toEqual({
      actions: [
        { cogId: red.id, action: "reason" },
        { cogId: blue.id, action: "spin" },
      ],
      choicesRevealedAtTick: 2,
      resultRevealedAtTick: 2,
      expiresAtTick: 2,
      outcome: "win",
      round: 1,
      winnerCogId: red.id,
      winnerColor: "red",
    });
  });

  it("raises the winner's certainty and lowers the loser's certainty after an argument", async () => {
    const world = new GridWorld(
      { width: 6, height: 6 },
      { ...FAST_DEBATE_CONFIG, debateDoubt: 10, debateWinCertaintyGain: 5, conversionThreshold: 1000 },
    );
    const red = addCog(world, {
      name: "Red",
      color: "red",
      activeTrait: "avenger",
      defensiveTrait: "insular",
      position: { x: 2, y: 2 },
    });
    const blue = addCog(world, {
      name: "Blue",
      color: "blue",
      activeTrait: "avenger",
      defensiveTrait: "insular",
      position: { x: 3, y: 2 },
    });

    await world.step(new Map<string, CogAction>([[red.id, debate(blue.id)]]));
    const state = world.exportState();
    const stateRed = state.cogs.find((cog) => cog.id === red.id);
    const stateBlue = state.cogs.find((cog) => cog.id === blue.id);
    if (!stateRed || !stateBlue) {
      throw new Error("Expected debate cogs in exported state");
    }
    stateRed.certainty = 480;
    stateBlue.certainty = 496;
    const restored = GridWorld.fromState(state);

    const snapshot = await restored.step(
      new Map<string, CogAction>([
        [red.id, chooseTactic("reason")],
        [blue.id, chooseTactic("spin")],
      ]),
    );

    expect(snapshot.cogs.find((cog) => cog.id === red.id)?.certainty).toBe(485);
    expect(snapshot.cogs.find((cog) => cog.id === blue.id)?.certainty).toBe(486);
  });

  it("waits the configured reveal and result duration before resolving another exchange", async () => {
    const world = new GridWorld(
      { width: 6, height: 6 },
      { debatePrepTicks: 0, debateChoiceRevealTicks: 1, debateResultTicks: 1 },
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

    let snapshot = await world.step(
      new Map<string, CogAction>([
        [red.id, chooseTactic("reason")],
        [blue.id, chooseTactic("spin")],
      ]),
    );
    expect(snapshot.recentEvents.filter((event) => event.type === "debateExchange")).toHaveLength(1);
    expect(snapshot.cogs.find((cog) => cog.id === red.id)?.debate?.nextRoundTick).toBe(4);

    snapshot = await world.step(
      new Map<string, CogAction>([
        [red.id, chooseTactic("reason")],
        [blue.id, chooseTactic("spin")],
      ]),
    );

    expect(snapshot.recentEvents.filter((event) => event.type === "debateExchange")).toHaveLength(2);
    expect(snapshot.recentEvents.findLast((event) => event.type === "debateExchange")?.debate?.round).toBe(2);
  });

  it("keeps drawn exchanges brief before the next round can start", async () => {
    const world = new GridWorld(
      { width: 6, height: 6 },
      { debatePrepTicks: 0, debateChoiceRevealTicks: 0, debateResultTicks: legacyHalfSecondTicksToSimulationTicks(6) },
    );
    const red = addCog(world, { name: "Red", color: "red", position: { x: 2, y: 2 } });
    const blue = addCog(world, { name: "Blue", color: "blue", position: { x: 3, y: 2 } });

    await world.step(new Map<string, CogAction>([[red.id, debate(blue.id)]]));
    let snapshot = await world.step(
      new Map<string, CogAction>([
        [red.id, chooseTactic("passion")],
        [blue.id, chooseTactic("passion")],
      ]),
    );

    const draw = snapshot.recentEvents.find((event) => event.type === "debateExchange")?.debate;
    expect(draw).toMatchObject({ outcome: "draw" });
    expect((draw?.expiresAtTick ?? 0) - (draw?.resultRevealedAtTick ?? 0)).toBe(
      legacyHalfSecondTicksToSimulationTicks(2),
    );
    expect(snapshot.cogs.find((cog) => cog.id === red.id)?.debate?.nextRoundTick).toBe(draw?.expiresAtTick);

    for (let index = 0; index < legacyHalfSecondTicksToSimulationTicks(2); index += 1) {
      snapshot = await world.step(
        new Map<string, CogAction>([
          [red.id, chooseTactic("reason")],
          [blue.id, chooseTactic("spin")],
        ]),
      );
    }

    expect(snapshot.recentEvents.filter((event) => event.type === "debateExchange")).toHaveLength(2);
    expect(snapshot.recentEvents.findLast((event) => event.type === "debateExchange")?.debate?.round).toBe(2);
  });

  it("paces debate rounds through prep choices and result phases", async () => {
    const world = new GridWorld({ width: 6, height: 6 });
    const red = addCog(world, { name: "Red", color: "red", position: { x: 2, y: 2 } });
    const blue = addCog(world, { name: "Blue", color: "blue", position: { x: 3, y: 2 } });

    await world.step(new Map<string, CogAction>([[red.id, debate(blue.id)]]));
    expect(world.snapshot().cogs.find((cog) => cog.id === red.id)?.debate?.nextRoundTick).toBe(
      1 + secondsToSimulationTicks(1),
    );

    let snapshot = world.snapshot();
    for (let index = 0; index < secondsToSimulationTicks(1) - 1; index += 1) {
      snapshot = await world.step(
        new Map<string, CogAction>([
          [red.id, chooseTactic("reason")],
          [blue.id, chooseTactic("spin")],
        ]),
      );
    }
    expect(snapshot.recentEvents.filter((event) => event.type === "debateExchange")).toHaveLength(0);

    snapshot = await world.step(
      new Map<string, CogAction>([
        [red.id, chooseTactic("reason")],
        [blue.id, chooseTactic("spin")],
      ]),
    );
    const exchange = snapshot.recentEvents.find((event) => event.type === "debateExchange");
    expect(exchange?.tick).toBe(1 + secondsToSimulationTicks(1));
    expect(exchange?.debate).toMatchObject({
      choicesRevealedAtTick: 1 + secondsToSimulationTicks(1),
      resultRevealedAtTick: 1 + secondsToSimulationTicks(2),
      expiresAtTick: 1 + secondsToSimulationTicks(5),
      round: 1,
    });
    expect(snapshot.cogs.find((cog) => cog.id === red.id)?.debate?.nextRoundTick).toBe(1 + secondsToSimulationTicks(6));

    for (let index = 0; index < secondsToSimulationTicks(5) - 1; index += 1) {
      snapshot = await world.step(
        new Map<string, CogAction>([
          [red.id, chooseTactic("reason")],
          [blue.id, chooseTactic("spin")],
        ]),
      );
    }
    expect(snapshot.recentEvents.filter((event) => event.type === "debateExchange")).toHaveLength(1);

    snapshot = await world.step(
      new Map<string, CogAction>([
        [red.id, chooseTactic("reason")],
        [blue.id, chooseTactic("spin")],
      ]),
    );
    expect(snapshot.recentEvents.filter((event) => event.type === "debateExchange")).toHaveLength(2);
    expect(snapshot.recentEvents.at(-1)?.debate?.round).toBe(2);
  });

  it("keeps same-tactic debates active without certainty changes", async () => {
    const world = new GridWorld({ width: 6, height: 6 }, FAST_DEBATE_CONFIG);
    const red = addCog(world, { name: "Red", color: "red", activeTrait: "contrarian", position: { x: 2, y: 2 } });
    const blue = addCog(world, { name: "Blue", color: "blue", activeTrait: "contrarian", position: { x: 3, y: 2 } });

    await world.step(new Map<string, CogAction>([[red.id, debate(blue.id)]]));
    const snapshot = await world.step(
      new Map<string, CogAction>([
        [red.id, chooseTactic("passion")],
        [blue.id, chooseTactic("passion")],
      ]),
    );
    const debatingRed = snapshot.cogs.find((cog) => cog.id === red.id);
    const debatingBlue = snapshot.cogs.find((cog) => cog.id === blue.id);

    expect(debatingRed?.certainty).toBe(100);
    expect(debatingBlue?.certainty).toBe(100);
    expect(debatingRed?.stats.argumentsWon).toBe(0);
    expect(debatingRed?.stats.argumentsLost).toBe(0);
    expect(debatingBlue?.stats.argumentsWon).toBe(0);
    expect(debatingBlue?.stats.argumentsLost).toBe(0);
    expect(debatingRed?.debate?.opponentId).toBe(blue.id);
  });

  it("invalid debate actions do not let cogs exit early", async () => {
    const world = new GridWorld({ width: 6, height: 6 }, FAST_DEBATE_CONFIG);
    const red = addCog(world, { name: "Red", color: "red", position: { x: 2, y: 2 } });
    const blue = addCog(world, { name: "Blue", color: "blue", position: { x: 3, y: 2 } });

    await world.step(new Map<string, CogAction>([[red.id, debate(blue.id)]]));
    const snapshot = await world.step(
      new Map<string, CogAction>([
        [red.id, { type: "wait" }],
        [blue.id, chooseTactic("passion")],
      ]),
    );
    const debatingRed = snapshot.cogs.find((cog) => cog.id === red.id);
    const debatingBlue = snapshot.cogs.find((cog) => cog.id === blue.id);
    const exchange = snapshot.recentEvents.find((event) => event.type === "debateExchange");

    expect(debatingRed?.debate?.opponentId).toBe(blue.id);
    expect(debatingBlue?.debate?.opponentId).toBe(red.id);
    expect(exchange?.debate?.outcome).toBe("lose");
  });

  it("converts color when certainty reaches zero, restores configured certainty, and ends the debate", async () => {
    const world = new GridWorld({ width: 6, height: 6 }, { ...FAST_DEBATE_CONFIG, debateDoubt: 20 });
    const red = addCog(world, { name: "Red", color: "red", activeTrait: "avenger", position: { x: 2, y: 2 } });
    const blue = addCog(world, { name: "Blue", color: "blue", defensiveTrait: "avenger", position: { x: 3, y: 2 } });

    await world.step(new Map<string, CogAction>([[red.id, debate(blue.id)]]));
    for (let i = 0; i < 5; i += 1) {
      await world.step(
        new Map<string, CogAction>([
          [red.id, chooseTactic("reason")],
          [blue.id, chooseTactic("spin")],
        ]),
      );
    }
    const conversionSnapshot = world.snapshot();
    const convertedRed = conversionSnapshot.cogs.find((cog) => cog.id === red.id);
    const convertedBlue = conversionSnapshot.cogs.find((cog) => cog.id === blue.id);

    expect(convertedBlue?.color).toBe("red");
    expect(convertedBlue?.stats.teamFlips).toBe(1);
    expect(convertedBlue?.stats.argumentsLost).toBeGreaterThan(0);
    expect(convertedBlue?.certainty).toBe(50);
    expect(convertedRed?.debate).toBeUndefined();
    expect(convertedBlue?.debate).toBeUndefined();

    const nextSnapshot = await world.step(
      new Map<string, CogAction>([
        [red.id, chooseTactic("reason")],
        [blue.id, chooseTactic("spin")],
      ]),
    );
    const exchangeEvents = nextSnapshot.recentEvents.filter((event) => event.type === "debateExchange");
    expect(exchangeEvents).toHaveLength(conversionSnapshot.recentEvents.filter((event) => event.type === "debateExchange").length);
  });

  it("ends the debate as soon as a participant flips", async () => {
    const world = new GridWorld(
      { width: 6, height: 6 },
      { ...FAST_DEBATE_CONFIG, debateDoubt: 100, conversionThreshold: 100, maxDebateRounds: 5 },
    );
    const red = addCog(world, { name: "Red", color: "red", position: { x: 2, y: 2 } });
    const blue = addCog(world, { name: "Blue", color: "blue", defensiveTrait: "avenger", position: { x: 3, y: 2 } });

    await world.step(new Map<string, CogAction>([[red.id, debate(blue.id)]]));
    const snapshot = await world.step(
      new Map<string, CogAction>([
        [red.id, chooseTactic("reason")],
        [blue.id, chooseTactic("spin")],
      ]),
    );

    const convertedBlue = snapshot.cogs.find((cog) => cog.id === blue.id);
    expect(convertedBlue?.color).toBe("red");
    expect(snapshot.cogs.find((cog) => cog.id === red.id)?.debate).toBeUndefined();
    expect(convertedBlue?.debate).toBeUndefined();
    expect(snapshot.recentEvents.filter((event) => event.type === "debateExchange")).toHaveLength(1);
    expect(snapshot.recentEvents).toContainEqual(
      expect.objectContaining({
        type: "colorChange",
        actorId: blue.id,
      }),
    );
    expect(snapshot.recentEvents).toContainEqual(
      expect.objectContaining({
        type: "gameFlow",
        message: "Red reaches majority",
      }),
    );
  });

  it("ends decisive debates after five rounds even when nobody flips", async () => {
    const world = new GridWorld(
      { width: 6, height: 6 },
      { ...FAST_DEBATE_CONFIG, debateDoubt: 10, conversionThreshold: 1000, maxDebateRounds: 5 },
    );
    const red = addCog(world, { name: "Red", color: "red", position: { x: 2, y: 2 } });
    const blue = addCog(world, { name: "Blue", color: "blue", position: { x: 3, y: 2 } });

    await world.step(new Map<string, CogAction>([[red.id, debate(blue.id)]]));
    for (let i = 0; i < 5; i += 1) {
      await world.step(
        new Map<string, CogAction>([
          [red.id, chooseTactic("reason")],
          [blue.id, chooseTactic("spin")],
        ]),
      );
    }

    const snapshot = world.snapshot();
    const blueAfterFiveRounds = snapshot.cogs.find((cog) => cog.id === blue.id);
    expect(snapshot.cogs.find((cog) => cog.id === red.id)?.debate).toBeUndefined();
    expect(blueAfterFiveRounds?.debate).toBeUndefined();
    expect(blueAfterFiveRounds?.color).toBe("blue");
    expect(snapshot.recentEvents.findLast((event) => event.type === "debateExchange")?.debate?.round).toBe(5);
  });

  it("ends unresolved debates after five rounds", async () => {
    const world = new GridWorld({ width: 6, height: 6 }, FAST_DEBATE_CONFIG);
    const red = addCog(world, { name: "Red", color: "red", activeTrait: "avenger", position: { x: 2, y: 2 } });
    const blue = addCog(world, { name: "Blue", color: "blue", activeTrait: "avenger", position: { x: 3, y: 2 } });

    await world.step(new Map<string, CogAction>([[red.id, debate(blue.id)]]));
    for (let i = 0; i < 5; i += 1) {
      await world.step(
        new Map<string, CogAction>([
          [red.id, chooseTactic("passion")],
          [blue.id, chooseTactic("passion")],
        ]),
      );
    }

    const snapshot = world.snapshot();
    expect(snapshot.cogs.find((cog) => cog.id === red.id)?.debate).toBeUndefined();
    expect(snapshot.cogs.find((cog) => cog.id === blue.id)?.debate).toBeUndefined();
    const finalExchange = snapshot.recentEvents.findLast((event) => event.type === "debateExchange");
    expect(finalExchange?.debate?.outcome).toBe("draw");
    expect(finalExchange?.debate?.round).toBe(5);
  });

  it("blocks repeat debates between the same pair during cooldown", async () => {
    const world = new GridWorld({ width: 6, height: 6 }, FAST_DEBATE_CONFIG);
    const red = addCog(world, { name: "Red", color: "red", activeTrait: "avenger", position: { x: 2, y: 2 } });
    const blue = addCog(world, { name: "Blue", color: "blue", activeTrait: "avenger", position: { x: 3, y: 2 } });

    await world.step(new Map<string, CogAction>([[red.id, debate(blue.id)]]));
    for (let i = 0; i < 5; i += 1) {
      await world.step(
        new Map<string, CogAction>([
          [red.id, chooseTactic("passion")],
          [blue.id, chooseTactic("passion")],
        ]),
      );
    }
    const afterCooldownAttempt = await world.step(new Map<string, CogAction>([[blue.id, debate(red.id)]]));

    expect(afterCooldownAttempt.cogs.find((cog) => cog.id === red.id)?.debate).toBeUndefined();
    expect(afterCooldownAttempt.cogs.find((cog) => cog.id === blue.id)?.debate).toBeUndefined();
  });

  it("adjusts same-room witness certainty after decisive rounds", async () => {
    const world = new GridWorld({ width: 8, height: 8 }, FAST_DEBATE_CONFIG, witnessVenue());
    const red = addVenueCog(world, { name: "Red", color: "red", activeTrait: "avenger", roomId: "room", spotId: "a" });
    const blue = addVenueCog(world, { name: "Blue", color: "blue", activeTrait: "avenger", roomId: "room", spotId: "b" });
    const witness = addVenueCog(world, { name: "Witness", color: "blue", activeTrait: "avenger", roomId: "room", spotId: "c" });

    await world.step(new Map<string, CogAction>([[red.id, debate(blue.id)]]));
    const snapshot = await world.step(
      new Map<string, CogAction>([
        [red.id, chooseTactic("reason")],
        [blue.id, chooseTactic("spin")],
      ]),
    );

    expect(snapshot.cogs.find((cog) => cog.id === witness.id)?.certainty).toBeLessThan(100);
  });

  it("uses charismatic trait config for witness certainty loss", async () => {
    const world = new GridWorld(
      { width: 8, height: 8 },
      { ...FAST_DEBATE_CONFIG, traitConfig: { charismatic: { witnessDoubt: 9 } }, witnessDoubt: 4 },
      witnessVenue(),
    );
    const red = addVenueCog(world, {
      name: "Red",
      color: "red",
      activeTrait: "charismatic",
      roomId: "room",
      spotId: "a",
    });
    const blue = addVenueCog(world, { name: "Blue", color: "blue", activeTrait: "avenger", roomId: "room", spotId: "b" });
    const witness = addVenueCog(world, {
      name: "Witness",
      color: "blue",
      activeTrait: "avenger",
      roomId: "room",
      spotId: "c",
    });

    await world.step(new Map<string, CogAction>([[red.id, debate(blue.id)]]));
    const snapshot = await world.step(
      new Map<string, CogAction>([
        [red.id, chooseTactic("reason")],
        [blue.id, chooseTactic("spin")],
      ]),
    );

    expect(snapshot.cogs.find((cog) => cog.id === witness.id)?.certainty).toBe(91);
  });

  it("does not adjust witnesses outside the debate room", async () => {
    const world = new GridWorld({ width: 10, height: 10 }, { ...FAST_DEBATE_CONFIG, witnessDoubt: 4 }, witnessVenue());
    const red = addVenueCog(world, { name: "Red", color: "red", activeTrait: "avenger", roomId: "room", spotId: "a" });
    const blue = addVenueCog(world, { name: "Blue", color: "blue", activeTrait: "avenger", roomId: "room", spotId: "b" });
    const otherRoomWitness = addVenueCog(world, {
      name: "OtherRoom",
      color: "blue",
      activeTrait: "avenger",
      roomId: "other",
      spotId: "d",
    });

    await world.step(new Map<string, CogAction>([[red.id, debate(blue.id)]]));
    const snapshot = await world.step(
      new Map<string, CogAction>([
        [red.id, chooseTactic("reason")],
        [blue.id, chooseTactic("spin")],
      ]),
    );

    expect(snapshot.cogs.find((cog) => cog.id === otherRoomWitness.id)?.certainty).toBe(100);
  });

  it("tactic affinity traits apply more certainty loss and increase matching susceptibility", async () => {
    const baselineWorld = new GridWorld({ width: 6, height: 6 }, FAST_DEBATE_CONFIG);
    const baselineRed = addCog(baselineWorld, {
      name: "BaselineRed",
      color: "red",
      activeTrait: "avenger",
      defensiveTrait: "avenger",
      position: { x: 2, y: 2 },
    });
    const baselineBlue = addCog(baselineWorld, {
      name: "BaselineBlue",
      color: "blue",
      activeTrait: "avenger",
      defensiveTrait: "avenger",
      position: { x: 3, y: 2 },
    });
    await baselineWorld.step(new Map<string, CogAction>([[baselineRed.id, debate(baselineBlue.id)]]));
    const baselineSnapshot = await baselineWorld.step(
      new Map<string, CogAction>([
        [baselineRed.id, chooseTactic("reason")],
        [baselineBlue.id, chooseTactic("spin")],
      ]),
    );
    const baselineCertainty =
      baselineSnapshot.cogs.find((cog) => cog.id === baselineBlue.id)?.certainty ?? Number.NaN;

    const affinityWorld = new GridWorld({ width: 6, height: 6 }, FAST_DEBATE_CONFIG);
    const rationalistRed = addCog(affinityWorld, {
      name: "RationalistRed",
      color: "red",
      activeTrait: "rationalist",
      defensiveTrait: "avenger",
      position: { x: 2, y: 2 },
    });
    const rationalistBlue = addCog(affinityWorld, {
      name: "RationalistBlue",
      color: "blue",
      activeTrait: "rationalist",
      defensiveTrait: "avenger",
      position: { x: 3, y: 2 },
    });
    await affinityWorld.step(new Map<string, CogAction>([[rationalistRed.id, debate(rationalistBlue.id)]]));
    const affinitySnapshot = await affinityWorld.step(
      new Map<string, CogAction>([
        [rationalistRed.id, chooseTactic("reason")],
        [rationalistBlue.id, chooseTactic("spin")],
      ]),
    );
    const affinityCertainty = affinitySnapshot.cogs.find((cog) => cog.id === rationalistBlue.id)?.certainty ?? Number.NaN;

    expect(affinityCertainty).toBeLessThan(baselineCertainty);
  });

  it("iconoclast and conformist resist certainty loss from unique largest and smallest colors", async () => {
    const iconoclastWorld = new GridWorld({ width: 8, height: 8 }, FAST_DEBATE_CONFIG);
    const red = addCog(iconoclastWorld, {
      name: "Red",
      color: "red",
      activeTrait: "avenger",
      defensiveTrait: "avenger",
      position: { x: 2, y: 2 },
    });
    iconoclastWorld.addCog({
      name: "OtherRed",
      spriteSheetKey: "cog-otherred",
      controllerId: "stub",
      attributes: { energy: 5 },
      color: "red",
      defensiveTrait: "avenger",
      activeTrait: "avenger",
      personalGoal: "majority",
      position: { x: 7, y: 7 },
    });
    const iconoclastBlue = addCog(iconoclastWorld, {
      name: "IconoclastBlue",
      color: "blue",
      activeTrait: "avenger",
      defensiveTrait: "iconoclast",
      position: { x: 3, y: 2 },
    });
    await iconoclastWorld.step(new Map<string, CogAction>([[red.id, debate(iconoclastBlue.id)]]));
    const iconoclastSnapshot = await iconoclastWorld.step(
      new Map<string, CogAction>([
        [red.id, chooseTactic("reason")],
        [iconoclastBlue.id, chooseTactic("spin")],
      ]),
    );
    const iconoclastCertainty =
      iconoclastSnapshot.cogs.find((cog) => cog.id === iconoclastBlue.id)?.certainty ?? Number.NaN;

    const conformistWorld = new GridWorld({ width: 8, height: 8 }, FAST_DEBATE_CONFIG);
    const loneRed = addCog(conformistWorld, {
      name: "LoneRed",
      color: "red",
      activeTrait: "avenger",
      defensiveTrait: "avenger",
      position: { x: 2, y: 2 },
    });
    conformistWorld.addCog({
      name: "OtherBlue",
      spriteSheetKey: "cog-otherblue",
      controllerId: "stub",
      attributes: { energy: 5 },
      color: "blue",
      defensiveTrait: "avenger",
      activeTrait: "avenger",
      personalGoal: "majority",
      position: { x: 7, y: 7 },
    });
    const conformistBlue = addCog(conformistWorld, {
      name: "ConformistBlue",
      color: "blue",
      activeTrait: "avenger",
      defensiveTrait: "conformist",
      position: { x: 3, y: 2 },
    });
    await conformistWorld.step(new Map<string, CogAction>([[loneRed.id, debate(conformistBlue.id)]]));
    const conformistSnapshot = await conformistWorld.step(
      new Map<string, CogAction>([
        [loneRed.id, chooseTactic("reason")],
        [conformistBlue.id, chooseTactic("spin")],
      ]),
    );
    const conformistCertainty =
      conformistSnapshot.cogs.find((cog) => cog.id === conformistBlue.id)?.certainty ?? Number.NaN;

    expect(iconoclastCertainty).toBeGreaterThan(64);
    expect(conformistCertainty).toBeGreaterThan(64);
  });

  it("forceful debate wins apply extra direct certainty loss", async () => {
    expect(createCogRequestSchema.parse({ name: "Force", activeTrait: "forceful" }).activeTrait).toBe("forceful");

    async function certaintyAfterWin(activeTrait: string): Promise<number> {
      const world = new GridWorld({ width: 10, height: 10 }, FAST_DEBATE_CONFIG);
      const red = addCog(world, {
        name: "Red",
        color: "red",
        activeTrait,
        defensiveTrait: "avenger",
        position: { x: 2, y: 2 },
      });
      const blue = addCog(world, {
        name: "Blue",
        color: "blue",
        activeTrait: "avenger",
        defensiveTrait: "avenger",
        position: { x: 3, y: 2 },
      });

      await world.step(new Map<string, CogAction>([[red.id, debate(blue.id)]]));
      const snapshot = await world.step(
        new Map<string, CogAction>([
          [red.id, chooseTactic("reason")],
          [blue.id, chooseTactic("spin")],
        ]),
      );

      return snapshot.cogs.find((cog) => cog.id === blue.id)?.certainty ?? Number.NaN;
    }

    const forcefulCertainty = await certaintyAfterWin("forceful");
    const avengerCertainty = await certaintyAfterWin("avenger");

    expect(forcefulCertainty).toBeLessThan(avengerCertainty);
  });

});
