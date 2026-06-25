import { describe, expect, it } from "vitest";

import { GridWorld } from "../../src/server/simulation/world.js";
import type { AchievementAssignment, CogAction, VenueLayout } from "../../src/shared/types.js";

const FAST_DEBATE_CONFIG = {
  debatePrepTicks: 0,
  debateChoiceRevealTicks: 0,
  debateResultTicks: 0,
  debateCooldownTicks: 0,
  maxDebateRounds: 1,
};

describe("achievement integration", () => {
  it("awards an achievement for winning a debate in the assigned room kind", async () => {
    const world = new GridWorld({ width: 12, height: 12 }, FAST_DEBATE_CONFIG, achievementVenue());
    const red = world.addCog({ name: "Red", color: "red", controllerId: "stub", location: { roomId: "bar", spotId: "bar-red-a" } });
    const blue = world.addCog({ name: "Blue", color: "blue", controllerId: "stub", location: { roomId: "bar", spotId: "bar-blue-a" } });
    forceAchievements(world, red.id, [
      achievement("winInRoom", { roomKind: "bar" }),
      achievement("debateThreeCogs"),
      achievement("loseToTrait", { trait: "avenger" }),
    ]);

    await world.step(actionMap([[red.id, { type: "debate", targetId: blue.id }]]));
    const snapshot = await world.step(
      actionMap([
        [red.id, { type: "chooseTactic", tactic: "reason" }],
        [blue.id, { type: "chooseTactic", tactic: "spin" }],
      ]),
    );
    const observedRed = snapshot.cogs.find((cog) => cog.id === red.id);

    expect(observedRed?.completedAchievements).toEqual([
      expect.objectContaining({
        achievementId: "winInRoom",
        parameters: { roomKind: "bar" },
        completedTick: 2,
        points: 10,
      }),
    ]);
  });

  it("awards a witness achievement after three assigned-team debate wins in the same room", async () => {
    const world = new GridWorld({ width: 12, height: 12 }, FAST_DEBATE_CONFIG, achievementVenue());
    const witness = world.addCog({
      name: "Witness",
      color: "red",
      controllerId: "stub",
      location: { roomId: "bar", spotId: "bar-witness" },
    });
    const red = world.addCog({ name: "Red", color: "red", controllerId: "stub", location: { roomId: "bar", spotId: "bar-red-a" } });
    const blue = world.addCog({ name: "Blue", color: "blue", controllerId: "stub", location: { roomId: "bar", spotId: "bar-blue-a" } });
    forceAchievements(world, witness.id, [
      achievement("witnessTeamWins", { team: "red", rounds: 3 }),
      achievement("debateThreeCogs"),
      achievement("loseToTrait", { trait: "avenger" }),
    ]);

    let snapshot = world.snapshot();
    for (let index = 0; index < 3; index += 1) {
      await world.step(actionMap([[red.id, { type: "debate", targetId: blue.id }]]));
      snapshot = await world.step(
        actionMap([
          [red.id, { type: "chooseTactic", tactic: "reason" }],
          [blue.id, { type: "chooseTactic", tactic: "spin" }],
        ]),
      );
      if (index < 2) {
        expect(snapshot.cogs.find((cog) => cog.id === witness.id)?.completedAchievements).toHaveLength(0);
      }
    }
    const observedWitness = snapshot.cogs.find((cog) => cog.id === witness.id);

    expect(observedWitness?.completedAchievements).toEqual([
      expect.objectContaining({
        achievementId: "witnessTeamWins",
        parameters: { team: "red", rounds: 3 },
        completedTick: 6,
        points: 10,
      }),
    ]);
    const debateExchange = snapshot.recentEvents.findLast((event) => event.type === "debateExchange");
    expect(debateExchange?.debate?.witnessCogIds).toContain(witness.id);
  });

  it("awards a parameterized lose-to-trait achievement", async () => {
    const world = new GridWorld({ width: 12, height: 12 }, FAST_DEBATE_CONFIG, achievementVenue());
    const red = world.addCog({ name: "Red", color: "red", controllerId: "stub", location: { roomId: "bar", spotId: "bar-red-a" } });
    const blue = world.addCog({
      name: "Blue",
      color: "blue",
      controllerId: "stub",
      activeTrait: "charismatic",
      location: { roomId: "bar", spotId: "bar-blue-a" },
    });
    forceAchievements(world, red.id, [
      achievement("loseToTrait", { trait: "charismatic" }),
      achievement("debateThreeCogs"),
      achievement("witnessTeamWins", { team: "red", rounds: 3 }),
    ]);

    await world.step(actionMap([[red.id, { type: "debate", targetId: blue.id }]]));
    const snapshot = await world.step(
      actionMap([
        [red.id, { type: "chooseTactic", tactic: "spin" }],
        [blue.id, { type: "chooseTactic", tactic: "reason" }],
      ]),
    );
    const observedRed = snapshot.cogs.find((cog) => cog.id === red.id);

    expect(observedRed?.completedAchievements).toEqual([
      expect.objectContaining({
        achievementId: "loseToTrait",
        parameters: { trait: "charismatic" },
        completedTick: 2,
        points: 10,
      }),
    ]);
    expect(snapshot.recentEvents).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          message: expect.stringContaining("completed Lose Round to Cog with Charismatic for 10 points"),
          type: "score",
        }),
      ]),
    );
  });
});

function achievement(
  achievementId: AchievementAssignment["achievementId"],
  parameters?: AchievementAssignment["parameters"],
): AchievementAssignment {
  return {
    assignmentId: `${achievementId}-assignment`,
    achievementId,
    parameters,
    assignedTick: 0,
    timeoutTick: 100,
  };
}

function forceAchievements(world: GridWorld, cogId: string, achievements: AchievementAssignment[]): void {
  const cog = (world as unknown as { cogs: Map<string, { achievements: AchievementAssignment[] }> }).cogs.get(cogId);
  if (!cog) {
    throw new Error(`Missing cog ${cogId}`);
  }

  cog.achievements = achievements;
}

function actionMap(entries: Array<[string, CogAction]>): Map<string, CogAction> {
  return new Map(entries);
}

function achievementVenue(): VenueLayout {
  return {
    rooms: [
      {
        id: "bar",
        label: "Bar",
        kind: "bar",
        spotIds: ["bar-witness", "bar-red-a", "bar-blue-a", "bar-red-b", "bar-blue-b"],
        neighborIds: [],
      },
    ],
    spots: [
      { id: "bar-witness", roomId: "bar", label: "Witness", position: { x: 1, y: 1 } },
      { id: "bar-red-a", roomId: "bar", label: "Red A", position: { x: 2, y: 1 } },
      { id: "bar-blue-a", roomId: "bar", label: "Blue A", position: { x: 3, y: 1 } },
      { id: "bar-red-b", roomId: "bar", label: "Red B", position: { x: 4, y: 1 } },
      { id: "bar-blue-b", roomId: "bar", label: "Blue B", position: { x: 5, y: 1 } },
    ],
    spotLinks: [
      { id: "bar-red-a__bar-blue-a", fromSpotId: "bar-red-a", toSpotId: "bar-blue-a" },
      { id: "bar-red-b__bar-blue-b", fromSpotId: "bar-red-b", toSpotId: "bar-blue-b" },
    ],
    roomPaths: [],
  };
}
