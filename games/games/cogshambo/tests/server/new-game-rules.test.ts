import { describe, expect, it } from "vitest";

import { createCogRequestSchema } from "../../src/shared/protocol.js";
import { ACHIEVEMENT_RULES, achievementKey } from "../../src/shared/rules.js";
import { GOAL_SCORE_INTERVAL_TICKS } from "../../src/shared/timing.js";
import type { AchievementAssignment, CogAction, CompletedAchievement } from "../../src/shared/types.js";
import { GridWorld } from "../../src/server/simulation/world.js";

function actionMap(entries: Array<[string, CogAction]>): Map<string, CogAction> {
  return new Map(entries);
}

describe("new game rules contract", () => {
  it("rejects old vibe-based cog creation fields", () => {
    expect(() =>
      createCogRequestSchema.parse({
        name: "Old Mood",
        vibe: "curious",
      }),
    ).toThrow();
  });

  it("ignores legacy speak actions", async () => {
    const world = new GridWorld({ width: 6, height: 6 });
    const cog = world.addCog({ name: "Bee", position: { x: 1, y: 1 }, color: "red" });

    const snapshot = await world.step(
      actionMap([[cog.id, { type: "speak", text: "hello from red" } as unknown as CogAction]]),
    );

    expect(snapshot.recentEvents.some((event) => (event.type as string) === "speech")).toBe(false);
    expect(snapshot.cogs.find((candidate) => candidate.id === cog.id)).not.toHaveProperty("speech");
  });

  it("does not award recurring majority or underdog goal score", async () => {
    const world = new GridWorld({ width: 6, height: 6 });
    const red = world.addCog({ name: "Red", position: { x: 1, y: 1 }, color: "red", personalGoal: "majority" });
    world.addCog({ name: "OtherRed", position: { x: 1, y: 2 }, color: "red", personalGoal: "underdog" });
    const blue = world.addCog({ name: "Blue", position: { x: 4, y: 4 }, color: "blue", personalGoal: "underdog" });

    for (let index = 0; index < GOAL_SCORE_INTERVAL_TICKS; index += 1) {
      await world.step(new Map());
    }

    const snapshot = world.snapshot();
    const scoredRed = snapshot.cogs.find((cog) => cog.id === red.id);
    const scoredBlue = snapshot.cogs.find((cog) => cog.id === blue.id);

    expect(scoredRed?.personalScore).toBe(0);
    expect(scoredBlue?.personalScore).toBe(0);
    expect(scoredRed?.goalScores).toEqual([]);
    expect(scoredBlue?.goalScores).toEqual([]);
    expect(snapshot.recentEvents.some((event) => event.type === "score")).toBe(false);
  });

  it("assigns three active achievements to every new cog", () => {
    const world = new GridWorld({ width: 6, height: 6 });
    const cog = world.addCog({ name: "Ada", position: { x: 1, y: 1 }, color: "red" });
    const snapshot = world.snapshot();

    expect(cog.achievements).toHaveLength(3);
    expect(new Set(cog.achievements.map((achievement) => achievement.achievementId)).size).toBe(3);
    expect(cog.achievements.every((achievement) => achievement.assignedTick === 0)).toBe(true);
    expect(cog.achievements.every((achievement) => achievement.timeoutTick > achievement.assignedTick)).toBe(true);
    expect(cog.completedAchievements).toEqual([]);
    expect(snapshot.achievementCounts.reduce((sum, count) => sum + count.assigned, 0)).toBe(3);
    expect(snapshot.achievementCounts.reduce((sum, count) => sum + count.current, 0)).toBe(3);
  });

  it("records new cog arrivals as spawn events", () => {
    const world = new GridWorld({ width: 6, height: 6 });
    const cog = world.addCog({ name: "Ada", position: { x: 1, y: 1 }, color: "red" });

    expect(world.snapshot().recentEvents).toContainEqual(
      expect.objectContaining({
        actorId: cog.id,
        message: "Ada arrived!",
        position: { x: 1, y: 1 },
        type: "spawn",
      }),
    );
  });

  it("awards 10 score and replaces a completed achievement", async () => {
    const world = new GridWorld({ width: 6, height: 6 });
    const cog = world.addCog({ name: "Ada", position: { x: 1, y: 1 }, color: "red", personalGoal: "majority" });
    forceCogStats(world, cog.id, { argumentsWon: 3, argumentsLost: 0, teamFlips: 0 });
    forceAchievements(world, cog.id, [
      { assignmentId: "perfect-assignment", achievementId: "perfectDebate", assignedTick: 0, timeoutTick: 20 },
      { assignmentId: "bar-assignment", achievementId: "winInRoom", assignedTick: 0, timeoutTick: 20 },
      { assignmentId: "debate-three-assignment", achievementId: "debateThreeCogs", assignedTick: 0, timeoutTick: 20 },
    ]);

    const snapshot = await world.step(new Map());
    const scoredCog = snapshot.cogs.find((candidate) => candidate.id === cog.id);

    expect(scoredCog?.personalScore).toBe(10);
    expect(scoredCog?.completedAchievements).toEqual([
      expect.objectContaining({
        achievementId: "perfectDebate",
        assignmentId: "perfect-assignment",
        completedTick: 1,
        points: 10,
      }),
    ]);
    expect(scoredCog?.achievements).toHaveLength(3);
    expect(scoredCog?.achievements.some((achievement) => achievement.assignmentId === "perfect-assignment")).toBe(false);
    expect(scoredCog?.goalScores.every((track) => track.points === 0)).toBe(true);
    expect(snapshot.recentEvents).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          actorId: cog.id,
          message: expect.stringContaining("completed Perfect Rounds for 10 points"),
          type: "score",
        }),
      ]),
    );
  });

  it("normalizes achievement score by each cog's lifetime", async () => {
    const world = new GridWorld({ width: 6, height: 6 });
    const cog = world.addCog({ name: "Ada", position: { x: 1, y: 1 }, color: "red", personalGoal: "majority" });
    world.addCog({ name: "Grace", position: { x: 4, y: 4 }, color: "blue", personalGoal: "majority" });

    for (let index = 0; index < GOAL_SCORE_INTERVAL_TICKS; index += 1) {
      await world.step(new Map());
    }

    forceCogStats(world, cog.id, { argumentsWon: 3, argumentsLost: 0, teamFlips: 0 });
    forceAchievements(world, cog.id, [
      {
        assignmentId: "perfect-assignment",
        achievementId: "perfectDebate",
        assignedTick: GOAL_SCORE_INTERVAL_TICKS,
        timeoutTick: GOAL_SCORE_INTERVAL_TICKS + 20,
      },
    ]);

    const snapshot = await world.step(new Map());
    const scoredCog = snapshot.cogs.find((candidate) => candidate.id === cog.id);

    expect(scoredCog?.ticksAlive).toBe(GOAL_SCORE_INTERVAL_TICKS + 1);
    expect(scoredCog?.personalScore).toBeCloseTo(10 / (GOAL_SCORE_INTERVAL_TICKS + 1));
    expect(scoredCog?.goalScores.every((track) => track.points === 0)).toBe(true);
  });

  it("replaces timed-out achievements without awarding score", async () => {
    const world = new GridWorld({ width: 6, height: 6 });
    const cog = world.addCog({ name: "Ada", position: { x: 1, y: 1 }, color: "red" });
    forceAchievements(world, cog.id, [
      { assignmentId: "expired-assignment", achievementId: "debateThreeCogs", assignedTick: 0, timeoutTick: 1 },
      { assignmentId: "bar-assignment", achievementId: "winInRoom", assignedTick: 0, timeoutTick: 20 },
      { assignmentId: "trait-assignment", achievementId: "loseToTrait", parameters: { trait: "avenger" }, assignedTick: 0, timeoutTick: 20 },
    ]);

    const snapshot = await world.step(new Map());
    const observedCog = snapshot.cogs.find((candidate) => candidate.id === cog.id);

    expect(observedCog?.personalScore).toBe(0);
    expect(observedCog?.completedAchievements).toEqual([]);
    expect(observedCog?.failedAchievements).toEqual([
      expect.objectContaining({
        achievementId: "debateThreeCogs",
        assignmentId: "expired-assignment",
        failedTick: 1,
      }),
    ]);
    expect(observedCog?.achievements).toHaveLength(3);
    expect(observedCog?.achievements.some((achievement) => achievement.assignmentId === "expired-assignment")).toBe(false);
  });

  it("does not assign non-template achievements a cog has already completed", async () => {
    const world = new GridWorld({ width: 6, height: 6 });
    const cog = world.addCog({ name: "Ada", position: { x: 1, y: 1 }, color: "red" });
    const completedAchievementIds = new Set(ACHIEVEMENT_RULES.filter((rule) => rule.templateVariables.length === 0).map((rule) => rule.id));
    forceAchievements(world, cog.id, []);
    forceCompletedAchievements(
      world,
      cog.id,
      ACHIEVEMENT_RULES.filter((rule) => completedAchievementIds.has(rule.id)).map((rule, index) => ({
        assignmentId: `completed-${index}`,
        achievementId: rule.id,
        parameters: rule.parameters,
        assignedTick: 0,
        timeoutTick: 1,
        completedTick: 1,
        points: rule.points,
      })),
    );

    const snapshot = await world.step(new Map());
    const observedCog = snapshot.cogs.find((candidate) => candidate.id === cog.id);

    expect(observedCog?.achievements.some((achievement) => completedAchievementIds.has(achievement.achievementId))).toBe(false);
  });

  it("treats completed template achievements with different parameters as different achievements", async () => {
    const world = new GridWorld({ width: 6, height: 6 }, {}, {
      rooms: [
        { id: "bar", label: "Bar", kind: "bar", spotIds: [], neighborIds: ["stage"] },
        { id: "stage", label: "Stage", kind: "stage", spotIds: [], neighborIds: ["bar"] },
      ],
      spots: [],
      spotLinks: [],
      roomPaths: [],
    });
    const cog = world.addCog({ name: "Ada", position: { x: 1, y: 1 }, color: "red" });
    forceAchievements(world, cog.id, []);
    forceCompletedAchievements(world, cog.id, [
      {
        assignmentId: "completed-bar",
        achievementId: "winInRoom",
        parameters: { roomKind: "bar" },
        assignedTick: 0,
        timeoutTick: 1,
        completedTick: 1,
        points: 10,
      },
    ]);
    forceRandomChoice(world, (values) => preferredAchievementChoice(values, "winInRoom", { roomKind: "stage" }));

    const snapshot = await world.step(new Map());
    const observedCog = snapshot.cogs.find((candidate) => candidate.id === cog.id);

    expect(observedCog?.achievements).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          achievementId: "winInRoom",
          parameters: { roomKind: "stage" },
        }),
      ]),
    );
    expect(observedCog?.achievements).not.toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          achievementId: "winInRoom",
          parameters: { roomKind: "bar" },
        }),
      ]),
    );
  });

  it("does not forget completed achievement keys when completion history grows", async () => {
    const world = new GridWorld({ width: 6, height: 6 }, {}, {
      rooms: [{ id: "bar", label: "Bar", kind: "bar", spotIds: [], neighborIds: [] }],
      spots: [],
      spotLinks: [],
      roomPaths: [],
    });
    const cog = world.addCog({ name: "Ada", position: { x: 1, y: 1 }, color: "red" });
    forceAchievements(world, cog.id, []);
    forceCompletedAchievements(world, cog.id, [
      {
        assignmentId: "completed-bar",
        achievementId: "winInRoom",
        parameters: { roomKind: "bar" },
        assignedTick: 0,
        timeoutTick: 1,
        completedTick: 1,
        points: 10,
      },
      ...Array.from({ length: 80 }, (_, index): CompletedAchievement => ({
        assignmentId: `completed-extra-${index}`,
        achievementId: "debateThreeCogs",
        assignedTick: 0,
        timeoutTick: 1,
        completedTick: 1,
        points: 10,
      })),
    ]);
    forceRandomChoice(world, (values) => preferredAchievementChoice(values, "winInRoom", { roomKind: "bar" }));

    const snapshot = await world.step(new Map());
    const observedCog = snapshot.cogs.find((candidate) => candidate.id === cog.id);

    expect(observedCog?.achievements).not.toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          achievementId: "winInRoom",
          parameters: { roomKind: "bar" },
        }),
      ]),
    );
  });

  it("instantiates one random parameter set for a template achievement", async () => {
    const world = new GridWorld({ width: 6, height: 6 });
    const cog = world.addCog({ name: "Ada", position: { x: 1, y: 1 }, color: "red" });
    forceAchievements(world, cog.id, []);
    forceCompletedAchievements(
      world,
      cog.id,
      ACHIEVEMENT_RULES.filter((rule) => rule.id !== "loseToTrait").map((rule, index) => ({
        assignmentId: `completed-${index}`,
        achievementId: rule.id,
        parameters: rule.parameters,
        assignedTick: 0,
        timeoutTick: 1,
        completedTick: 1,
        points: rule.points,
      })),
    );
    forceRandomChoice(world, (values) => preferredAchievementChoice(values, "loseToTrait"));

    const snapshot = await world.step(new Map());
    const observedCog = snapshot.cogs.find((candidate) => candidate.id === cog.id);
    const assignedLoseToTrait = observedCog?.achievements.filter((achievement) => achievement.achievementId === "loseToTrait") ?? [];
    const loseToTraitCounts = snapshot.achievementCounts.filter((count) => count.achievementId === "loseToTrait");

    expect(assignedLoseToTrait).toHaveLength(1);
    expect(assignedLoseToTrait[0].parameters?.trait).toEqual(expect.any(String));
    expect(loseToTraitCounts).toHaveLength(1);
    expect(loseToTraitCounts[0]).toMatchObject({ assigned: 1, current: 1 });
  });

  it("instantiates one random room parameter set for a room template achievement", async () => {
    const world = new GridWorld({ width: 6, height: 6 }, {}, {
      rooms: [{ id: "stage", label: "Stage", kind: "stage", spotIds: [], neighborIds: [] }],
      spots: [],
      spotLinks: [],
      roomPaths: [],
    });
    const cog = world.addCog({ name: "Ada", position: { x: 1, y: 1 }, color: "red" });
    forceAchievements(world, cog.id, []);
    forceAchievementCounts(world, []);
    forceCompletedAchievements(
      world,
      cog.id,
      ACHIEVEMENT_RULES.filter((rule) => rule.id !== "winInRoom").map((rule, index) => ({
        assignmentId: `completed-${index}`,
        achievementId: rule.id,
        parameters: rule.parameters,
        assignedTick: 0,
        timeoutTick: 1,
        completedTick: 1,
        points: rule.points,
      })),
    );
    forceRandomChoice(world, (values) => preferredAchievementChoice(values, "winInRoom"));

    const snapshot = await world.step(new Map());
    const observedCog = snapshot.cogs.find((candidate) => candidate.id === cog.id);
    const assignedRoomAchievements = observedCog?.achievements.filter((achievement) => achievement.achievementId === "winInRoom") ?? [];
    const roomCounts = snapshot.achievementCounts.filter((count) => count.achievementId === "winInRoom");

    expect(assignedRoomAchievements).toHaveLength(1);
    expect(assignedRoomAchievements[0].parameters?.roomKind).toBe("stage");
    expect(roomCounts).toHaveLength(1);
    expect(roomCounts[0]).toMatchObject({ assigned: 1, current: 1 });
  });

  it("instantiates team and round parameters for witness achievements", async () => {
    const world = new GridWorld({ width: 6, height: 6 });
    const cog = world.addCog({ name: "Ada", position: { x: 1, y: 1 }, color: "red" });
    forceAchievements(world, cog.id, []);
    forceAchievementCounts(world, []);
    forceCompletedAchievements(
      world,
      cog.id,
      ACHIEVEMENT_RULES.filter((rule) => rule.id !== "witnessTeamWins").map((rule, index) => ({
        assignmentId: `completed-${index}`,
        achievementId: rule.id,
        parameters: rule.parameters,
        assignedTick: 0,
        timeoutTick: 1,
        completedTick: 1,
        points: rule.points,
      })),
    );
    forceRandomChoice(world, (values) => preferredAchievementChoice(values, "witnessTeamWins"));

    const snapshot = await world.step(new Map());
    const observedCog = snapshot.cogs.find((candidate) => candidate.id === cog.id);
    const assignedWitnessAchievements = observedCog?.achievements.filter((achievement) => achievement.achievementId === "witnessTeamWins") ?? [];
    const witnessCounts = snapshot.achievementCounts.filter((count) => count.achievementId === "witnessTeamWins");

    expect(assignedWitnessAchievements).toHaveLength(1);
    expect(assignedWitnessAchievements[0].parameters?.team).toEqual(expect.stringMatching(/^(red|blue)$/));
    expect(assignedWitnessAchievements[0].parameters?.rounds).toBe(3);
    expect(witnessCounts).toHaveLength(1);
    expect(witnessCounts[0]).toMatchObject({ assigned: 1, current: 1 });
  });

  it("tracks achievement assigned, completed, current, and expired counts", async () => {
    const world = new GridWorld({ width: 6, height: 6 });
    const cog = world.addCog({ name: "Ada", position: { x: 1, y: 1 }, color: "red" });
    forceCogStats(world, cog.id, { argumentsWon: 3, argumentsLost: 0, teamFlips: 0 });
    forceAchievements(world, cog.id, [
      { assignmentId: "perfect-assignment", achievementId: "perfectDebate", assignedTick: 0, timeoutTick: 20 },
      { assignmentId: "expired-assignment", achievementId: "debateThreeCogs", assignedTick: 0, timeoutTick: 1 },
      { assignmentId: "current-assignment", achievementId: "winInRoom", assignedTick: 0, timeoutTick: 20 },
    ]);
    forceAchievementCounts(world, [
      { achievementId: "perfectDebate", assigned: 1, completed: 0, expired: 0 },
      { achievementId: "debateThreeCogs", assigned: 1, completed: 0, expired: 0 },
      { achievementId: "winInRoom", assigned: 1, completed: 0, expired: 0 },
    ]);

    const snapshot = await world.step(new Map());

    expect(achievementCount(snapshot, "perfectDebate")).toMatchObject({
      assigned: 1,
      completed: 1,
      current: 0,
      expired: 0,
    });
    expect(achievementCount(snapshot, "debateThreeCogs")).toMatchObject({
      assigned: 1,
      completed: 0,
      current: 0,
      expired: 1,
    });
    expect(achievementCount(snapshot, "winInRoom")).toMatchObject({
      assigned: 1,
      completed: 0,
      current: 1,
      expired: 0,
    });
  });
});

function forceAchievements(world: GridWorld, cogId: string, achievements: AchievementAssignment[]): void {
  const cog = (world as unknown as { cogs: Map<string, { achievements: AchievementAssignment[] }> }).cogs.get(cogId);
  if (!cog) {
    throw new Error(`Missing cog ${cogId}`);
  }

  cog.achievements = achievements;
}

function forceCogStats(world: GridWorld, cogId: string, stats: { argumentsWon: number; argumentsLost: number; teamFlips: number }): void {
  const cog = (world as unknown as { cogs: Map<string, { stats: typeof stats }> }).cogs.get(cogId);
  if (!cog) {
    throw new Error(`Missing cog ${cogId}`);
  }

  cog.stats = stats;
}

function forceCompletedAchievements(world: GridWorld, cogId: string, achievements: CompletedAchievement[]): void {
  const cog = (world as unknown as { cogs: Map<string, { completedAchievements: CompletedAchievement[] }> }).cogs.get(cogId);
  if (!cog) {
    throw new Error(`Missing cog ${cogId}`);
  }

  cog.completedAchievements = achievements;
}

function forceAchievementCounts(
  world: GridWorld,
  counts: Array<{ achievementId: AchievementAssignment["achievementId"]; parameters?: AchievementAssignment["parameters"]; assigned: number; completed: number; expired: number }>,
): void {
  (world as unknown as {
    achievementCounts: Map<string, { achievementId: AchievementAssignment["achievementId"]; parameters?: AchievementAssignment["parameters"]; assigned: number; completed: number; expired: number }>;
  }).achievementCounts = new Map(
    counts.map((count) => [achievementKey(count), count]),
  );
}

function forceRandomChoice(world: GridWorld, choose: (values: readonly unknown[]) => unknown): void {
  (world as unknown as {
    random: {
      choice<T>(values: readonly T[]): T;
      int(maxExclusive: number): number;
      next(): number;
      setState(state: number): void;
      stateValue(): number;
    };
  }).random = {
    choice<T>(values: readonly T[]): T {
      return choose(values) as T;
    },
    int() {
      return 0;
    },
    next() {
      return 0;
    },
    setState() {
      // Test stub.
    },
    stateValue() {
      return 0;
    },
  };
}

function preferredAchievementChoice(
  values: readonly unknown[],
  achievementId: AchievementAssignment["achievementId"],
  parameters?: AchievementAssignment["parameters"],
): unknown {
  return (
    values.find((value) => achievementChoiceId(value) === achievementId && achievementChoiceParametersMatch(achievementChoiceParameters(value), parameters)) ??
    values.find((value) => achievementChoiceId(value) === achievementId) ??
    values[0]
  );
}

function achievementChoiceParametersMatch(
  candidate: AchievementAssignment["parameters"],
  expected: AchievementAssignment["parameters"],
): boolean {
  if (!expected) {
    return true;
  }
  return (
    (expected.trait === undefined || candidate?.trait === expected.trait) &&
    (expected.team === undefined || candidate?.team === expected.team) &&
    (expected.roomKind === undefined || candidate?.roomKind === expected.roomKind) &&
    (expected.tactic === undefined || candidate?.tactic === expected.tactic) &&
    (expected.rounds === undefined || candidate?.rounds === expected.rounds) &&
    (expected.cogId === undefined || candidate?.cogId === expected.cogId)
  );
}

function achievementChoiceId(value: unknown): AchievementAssignment["achievementId"] | undefined {
  if (!value || typeof value !== "object") {
    return undefined;
  }
  if ("rule" in value && value.rule && typeof value.rule === "object" && "id" in value.rule) {
    return value.rule.id as AchievementAssignment["achievementId"];
  }
  if ("id" in value) {
    return value.id as AchievementAssignment["achievementId"];
  }
  return undefined;
}

function achievementChoiceParameters(value: unknown): AchievementAssignment["parameters"] {
  if (!value || typeof value !== "object" || !("parameters" in value)) {
    return undefined;
  }
  return value.parameters as AchievementAssignment["parameters"];
}

function achievementCount(
  snapshot: Awaited<ReturnType<GridWorld["step"]>>,
  achievementId: AchievementAssignment["achievementId"],
  parameters?: AchievementAssignment["parameters"],
) {
  const key = achievementKey({ achievementId, parameters });
  return snapshot.achievementCounts.find((count) => {
    const countKey = achievementKey(count);
    return countKey === key;
  });
}
