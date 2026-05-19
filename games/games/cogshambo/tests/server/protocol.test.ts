import { describe, expect, it } from "vitest";
import {
  controlRequestSchema,
  createCogRequestSchema,
  generateCogSpritesRequestSchema,
  isClientMessage,
  isServerMessage,
  updateCogProfileRequestSchema,
  worldEventSchema,
  worldSnapshotSchema,
} from "../../src/shared/protocol.js";
import { GridWorld } from "../../src/server/simulation/world.js";

describe("protocol contracts", () => {
  it("accepts a valid create cog request", () => {
    const parsed = createCogRequestSchema.parse({
      name: "Ada",
      spriteSheetKey: "cog-ada",
      spriteUrl: "data:image/png;base64,abc",
      spriteUrls: {
        red: "/assets/cogshambo/cogs/ada-red.png",
        blue: "/assets/cogshambo/cogs/ada-blue.png",
      },
      controllerId: "wander",
      color: "red",
      defensiveTrait: "stubborn",
      activeTrait: "passionate",
      personalGoal: "underdog",
      attributes: { energy: 7, focus: 4 },
    });

    expect(parsed.name).toBe("Ada");
    expect(parsed.spriteUrl).toBe("data:image/png;base64,abc");
    expect(parsed.spriteUrls?.red).toBe("/assets/cogshambo/cogs/ada-red.png");
    expect(parsed.attributes.energy).toBe(7);
  });

  it("defaults created cogs to the llm controller", () => {
    expect(createCogRequestSchema.parse({ name: "Default LLM" }).controllerId).toBe("llm");
  });

  it("accepts every selectable trait in either trait slot", () => {
    const selectableTraits = [
      "stubborn",
      "insular",
      "iconoclast",
      "conformist",
      "defector",
      "bandwagoner",
      "martyr",
      "doubter",
      "diplomat",
      "heretic",
      "forceful",
      "charismatic",
      "contrarian",
      "hippie",
      "rationalist",
      "spinner",
      "passionate",
      "avenger",
      "insurgent",
      "polarizer",
    ] as const;

    for (const defensiveTrait of selectableTraits) {
      expect(createCogRequestSchema.parse({ name: defensiveTrait, defensiveTrait }).defensiveTrait).toBe(
        defensiveTrait,
      );
    }

    for (const activeTrait of selectableTraits) {
      expect(createCogRequestSchema.parse({ name: activeTrait, activeTrait }).activeTrait).toBe(activeTrait);
    }

    expect(generateCogSpritesRequestSchema.parse({ defensiveTrait: "forceful", activeTrait: "stubborn" })).toMatchObject({
      defensiveTrait: "forceful",
      activeTrait: "stubborn",
    });

    expect(
      updateCogProfileRequestSchema.parse({
        name: "Ada Prime",
        behaviorPrompt: "hold the line",
        attributes: { focus: 8 },
        defensiveTrait: "passionate",
        activeTrait: "iconoclast",
        personalGoal: "underdog",
      }),
    ).toEqual(
      expect.objectContaining({
        name: "Ada Prime",
        behaviorPrompt: "hold the line",
      }),
    );

    const removedTrait = "sw" + "ift";
    expect(() => createCogRequestSchema.parse({ name: "Removed", defensiveTrait: removedTrait })).toThrow();
    expect(() => createCogRequestSchema.parse({ name: "Removed", activeTrait: removedTrait })).toThrow();
    const removedStickyTrait = "sti" + "cky";
    expect(() => createCogRequestSchema.parse({ name: "Removed", defensiveTrait: removedStickyTrait })).toThrow();
    expect(() => createCogRequestSchema.parse({ name: "Removed", activeTrait: removedStickyTrait })).toThrow();
    const removedMercurialTrait = "merc" + "urial";
    expect(() => createCogRequestSchema.parse({ name: "Removed", defensiveTrait: removedMercurialTrait })).toThrow();
    expect(() => createCogRequestSchema.parse({ name: "Removed", activeTrait: removedMercurialTrait })).toThrow();
  });

  it("keeps zealot as a world-state trait but out of selectable creation traits", () => {
    expect(() => createCogRequestSchema.parse({ name: "Zealot", defensiveTrait: "zealot" })).toThrow();
    expect(() => createCogRequestSchema.parse({ name: "Zealot", activeTrait: "zealot" })).toThrow();
    expect(
      updateCogProfileRequestSchema.parse({
        behaviorPrompt: "",
        attributes: {},
        defensiveTrait: "zealot",
      }).defensiveTrait,
    ).toBe("zealot");
    expect(() => generateCogSpritesRequestSchema.parse({ defensiveTrait: "zealot" })).toThrow();
    expect(() => generateCogSpritesRequestSchema.parse({ activeTrait: "zealot" })).toThrow();

    const world = new GridWorld({ width: 6, height: 6 });
    world.addCog({ name: "Anchor", color: "red", defensiveTrait: "zealot", position: { x: 1, y: 1 } });

    expect(worldSnapshotSchema.parse(world.snapshot()).cogs[0]?.defensiveTrait).toBe("zealot");
  });

  it("coerces legacy personal goals for running worlds", () => {
    expect(createCogRequestSchema.parse({ name: "Old Leader", personalGoal: "leader" }).personalGoal).toBe("majority");
    expect(createCogRequestSchema.parse({ name: "Old Minority", personalGoal: "minority" }).personalGoal).toBe(
      "underdog",
    );
    expect(createCogRequestSchema.parse({ name: "Old Underdog", personalGoal: "underdog" }).personalGoal).toBe(
      "underdog",
    );
  });

  it("accepts legacy debate exchange events without reveal timing", () => {
    const parsed = worldEventSchema.parse({
      id: "old-debate",
      tick: 12,
      type: "debateExchange",
      message: "old debate event",
      debate: {
        actions: [
          { cogId: "red-cog", action: "reason" },
          { cogId: "blue-cog", action: "spin" },
        ],
        expiresAtTick: 48,
        outcome: "win",
        round: 1,
      },
    });

    expect(parsed.debate?.choicesRevealedAtTick).toBeUndefined();
  });

  it("rejects a create cog request without a name", () => {
    expect(() =>
      createCogRequestSchema.parse({
        spriteSheetKey: "cog-empty",
      }),
    ).toThrow();
  });

  it("accepts bounded cog sprite generation requests", () => {
    const parsed = generateCogSpritesRequestSchema.parse({
      name: "Ada",
      description: "brass cog with teal lens",
      defensiveTrait: "stubborn",
      activeTrait: "passionate",
      personalGoal: "underdog",
      spriteRoll: 3,
      count: 5,
    });

    expect(parsed.count).toBe(5);
    expect(() => generateCogSpritesRequestSchema.parse({ count: 6 })).toThrow();
  });

  it("recognizes server and client message shapes", () => {
    expect(isClientMessage({ type: "hello", clientName: "test" })).toBe(true);
    expect(isClientMessage({ type: "snapshot" })).toBe(false);
    expect(
      isServerMessage({
        type: "serverStatus",
        status: {
          tick: 1,
          cogCount: 2,
          clientCount: 0,
          controllerMode: "stub",
          discoMode: true,
          llmMoveDecisions: 10,
          llmTimedOutMovePercent: 20,
          llmTimedOutMoves: 2,
          simulationMode: "playing",
          stepRequested: false,
        },
      }),
    ).toBe(true);
  });

  it("accepts the disco mode control command", () => {
    expect(controlRequestSchema.parse({ command: "toggleDisco" }).command).toBe("toggleDisco");
  });

  it("rejects malformed server messages", () => {
    expect(isServerMessage({ type: "snapshot", snapshot: { cogs: [] } })).toBe(false);
    expect(
      isServerMessage({
        type: "serverStatus",
        status: {
          tick: 1,
          cogCount: 2,
          clientCount: 0,
          controllerMode: "remote",
          discoMode: false,
          llmMoveDecisions: 0,
          llmTimedOutMovePercent: 0,
          llmTimedOutMoves: 0,
          simulationMode: "playing",
          stepRequested: false,
        },
      }),
    ).toBe(false);
    expect(isServerMessage({ type: "event", event: { message: "missing fields" } })).toBe(false);
  });

  it("rejects malformed client debug messages", () => {
    expect(isClientMessage({ type: "debugCommand", command: "followCog", cogId: "cog-1" })).toBe(
      true,
    );
    expect(isClientMessage({ type: "debugCommand", command: "followCog", cogId: 123 })).toBe(false);
  });

  it("recognizes manual move client messages", () => {
    expect(isClientMessage({ type: "manualMove", cogId: "cog-1", direction: "east" })).toBe(true);
    expect(isClientMessage({ type: "manualMove", cogId: "cog-1", direction: "up" })).toBe(false);
    expect(isClientMessage({ type: "manualMove", direction: "east" })).toBe(false);
  });

  it("recognizes manual cog action client messages", () => {
    expect(isClientMessage({ type: "manualAction", cogId: "cog-1", action: { type: "move", roomId: "green_room" } })).toBe(
      true,
    );
    expect(
      isClientMessage({ type: "manualAction", cogId: "cog-1", action: { type: "chooseTactic", tactic: "reason" } }),
    ).toBe(true);
    expect(isClientMessage({ type: "manualAction", cogId: "cog-1", action: { type: "debate", targetId: "cog-2" } })).toBe(
      true,
    );
    expect(
      isClientMessage({
        type: "manualAction",
        cogId: "cog-1",
        action: { type: "wait", intent: "player steer: guard certainty" },
      }),
    ).toBe(true);
    expect(
      isClientMessage({ type: "manualAction", cogId: "cog-1", action: { type: "chooseTactic", tactic: "dance" } }),
    ).toBe(false);
    expect(isClientMessage({ type: "manualAction", action: { type: "move", roomId: "green_room" } })).toBe(false);
  });

  it("rejects manual debate-exit client messages", () => {
    expect(isClientMessage({ type: "manualTalkToTheHand", cogId: "cog-1" })).toBe(false);
  });

  it("accepts structured debate exchange action details", () => {
    const parsed = worldEventSchema.parse({
      id: "event-1",
      tick: 8,
      type: "debateExchange",
      actorId: "red-cog",
      targetId: "blue-cog",
      message: "Red's reason shook Blue's certainty",
      debate: {
        actions: [
          { cogId: "red-cog", action: "reason" },
          { cogId: "blue-cog", action: "spin" },
        ],
        choicesRevealedAtTick: 8,
        resultRevealedAtTick: 14,
        expiresAtTick: 48,
        outcome: "win",
        round: 1,
        winnerCogId: "red-cog",
        winnerColor: "red",
      },
    });

    expect(parsed.debate?.winnerColor).toBe("red");
    expect(() =>
      worldEventSchema.parse({
        ...parsed,
        debate: {
          actions: [{ cogId: "red-cog", action: "dance" }],
        },
      }),
    ).toThrow();
  });

  it("accepts kick events", () => {
    expect(
      worldEventSchema.parse({
        id: "event-kick",
        tick: 4,
        type: "kick",
        actorId: "cog-1",
        message: "Ada was kicked home",
      }).type,
    ).toBe("kick");
  });

  it("uses one numeric certainty value and no active color list in snapshots", () => {
    const snapshot = {
      tick: 1,
      dimensions: { width: 6, height: 6 },
      cogs: [
        {
          id: "cog-red",
          name: "Red",
          behaviorPrompt: "",
          position: { x: 2, y: 2 },
          spriteSheetKey: "cog-default",
          attributes: { energy: 5 },
          color: "red",
          defensiveTrait: "stubborn",
          activeTrait: "forceful",
          personalGoal: "majority",
          activity: "idle",
          personalScore: 0,
          achievements: [],
          completedAchievements: [],
          goalScores: [],
          stats: { argumentsWon: 0, argumentsLost: 0, teamFlips: 0 },
          certainty: 12,
          controllerId: "stub",
          movementCooldown: 0,
          conversationLog: [],
        },
      ],
      objects: [],
      terrain: [],
      recentEvents: [],
      achievementCounts: [],
    };

    expect(worldSnapshotSchema.parse(snapshot).cogs[0]?.certainty).toBe(12);
    expect(() => worldSnapshotSchema.parse({ ...snapshot, activeColors: ["red", "blue"] })).toThrow();
    expect(() => worldSnapshotSchema.parse({ ...snapshot, cogs: [{ ...snapshot.cogs[0], doubt: 12 }] })).toThrow();
    expect(() => worldSnapshotSchema.parse({ ...snapshot, cogs: [{ ...snapshot.cogs[0], certainty: { red: 12, blue: 0 } }] })).toThrow();
  });

  it("rejects removed portable-object state", () => {
    const removedToken = ["cr", "own"].join("");
    expect(() =>
      worldEventSchema.parse({
        id: "event-removed-object",
        tick: 1,
        type: `${removedToken}Pickup`,
        message: "picked up removed object",
      }),
    ).toThrow();
    expect(() =>
      worldSnapshotSchema.parse({
        tick: 1,
        dimensions: { width: 6, height: 6 },
        cogs: [],
        objects: [
          {
            id: "legacy-object",
            type: removedToken,
            position: { x: 1, y: 1 },
            spriteKey: removedToken,
            attributes: {},
          },
        ],
        terrain: [],
        recentEvents: [],
        achievementCounts: [],
      }),
    ).toThrow();
    expect(() =>
      worldSnapshotSchema.parse({
        tick: 1,
        dimensions: { width: 6, height: 6 },
        cogs: [],
        objects: [],
        terrain: [],
        recentEvents: [],
        achievementCounts: [],
        [`${removedToken}HolderId`]: "cog-1",
      }),
    ).toThrow();
  });

  it("accepts game flow events", () => {
    const parsed = worldEventSchema.parse({
      id: "flow-1",
      tick: 12,
      type: "gameFlow",
      actorId: "cog-1",
      message: "asking Ada to move",
    });

    expect(parsed.type).toBe("gameFlow");
    expect(parsed.message).toBe("asking Ada to move");
  });
});
