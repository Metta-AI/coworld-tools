import { readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
  ACHIEVEMENT_DEFINITIONS,
  ACHIEVEMENT_RULES,
  achievementDefinitionById,
  achievementKey,
  achievementRuleByAssignment,
} from "../../src/shared/achievements/index.js";
import { formatAchievementText } from "../../src/shared/achievements/helpers.js";
import type { AchievementAssignment, Cog, DebateTactic, VenueRoomKind, WorldEvent, WorldSnapshot } from "../../src/shared/types.js";

describe("achievement registry", () => {
  it("loads one rule per achievement template", () => {
    const achievementDir = fileURLToPath(new URL("../../src/shared/achievements/", import.meta.url));
    const implementationFiles = readdirSync(achievementDir).filter(
      (file) => file.endsWith(".ts") && !["helpers.ts", "ids.ts", "index.ts", "types.ts"].includes(file),
    );

    expect(ACHIEVEMENT_DEFINITIONS).toHaveLength(implementationFiles.length);
    expect(ACHIEVEMENT_RULES).toHaveLength(ACHIEVEMENT_DEFINITIONS.length);
    expect(new Set(ACHIEVEMENT_DEFINITIONS.map((achievement) => achievement.id)).size).toBe(ACHIEVEMENT_DEFINITIONS.length);
    expect(ACHIEVEMENT_DEFINITIONS.every((achievement) => achievement.name.length > 0)).toBe(true);
    expect(ACHIEVEMENT_DEFINITIONS.every((achievement) => achievement.description.length > 0)).toBe(true);
    expect(ACHIEVEMENT_DEFINITIONS.every((achievement) => typeof achievement.isAchieved === "function")).toBe(true);
  });

  it("represents template achievements as one rule with random parameters", () => {
    const loseToTraitFiles = readdirSync(fileURLToPath(new URL("../../src/shared/achievements/", import.meta.url))).filter(
      (file) => /^loseTo(?!Trait\.ts)/.test(file),
    );
    const ids = ACHIEVEMENT_DEFINITIONS.map((achievement) => achievement.id);
    const loseToTraitRules = ACHIEVEMENT_RULES.filter((rule) => rule.id === "loseToTrait");
    const assignedRule = achievementRuleByAssignment({
      achievementId: "loseToTrait",
      parameters: { trait: "charismatic" },
    });

    expect(loseToTraitFiles).toEqual([]);
    expect(ids).toEqual(expect.arrayContaining(["witnessTeamWins"]));
    expect(ids).not.toEqual(expect.arrayContaining(["redRecruit", "blueRecruit", "witnessRedWinsFive", "witnessTeamWinsFive"]));
    expect(achievementDefinitionById("loseToTrait").name).toContain("$TRAIT");
    expect(loseToTraitRules).toHaveLength(1);
    expect(loseToTraitRules[0].parameters).toBeUndefined();
    expect(loseToTraitRules[0].label).toBe("Lose Round to Cog with [TRAIT]");
    expect(assignedRule?.label).toBe("Lose Round to Cog with Charismatic");
    expect(assignedRule?.condition).toBe("Lose one round to a cog with the Charismatic trait.");
  });

  it("represents room achievements as one rule with random room parameters", () => {
    const roomRules = ACHIEVEMENT_RULES.filter((rule) => rule.id === "winInRoom");
    const assignedRule = achievementRuleByAssignment({
      achievementId: "winInRoom",
      parameters: { roomKind: "stage" },
    });

    expect(achievementDefinitionById("winInRoom").name).toBe("Win Round in $ROOM");
    expect(roomRules).toHaveLength(1);
    expect(roomRules[0].parameters).toBeUndefined();
    expect(roomRules[0].label).toBe("Win Round in [ROOM]");
    expect(assignedRule?.label).toBe("Win Round in Stage");
    expect(assignedRule?.condition).toBe("Win one round while both debaters are in a Stage room.");
  });

  it("formats achievement template variables", () => {
    expect(
      formatAchievementText("$TEAM recruits $COG through $TRAIT", {
        trait: "insular",
        team: "red",
        cogId: "ada-id",
        cogName: "Ada",
      }),
    ).toBe("Red recruits Ada through Insular");
    expect(formatAchievementText("Win Round in $ROOM", { roomKind: "lounge" })).toBe("Win Round in Lounge");
    expect(formatAchievementText("Lose Round to Cog with $TRAIT")).toBe("Lose Round to Cog with [TRAIT]");
    expect(formatAchievementText("Witness $ROUNDS rounds won by $TEAM", { team: "blue", rounds: 4 })).toBe(
      "Witness 4 rounds won by Blue",
    );
    expect(formatAchievementText("Win with $TACTIC", { tactic: "spin" })).toBe("Win with Spin");
  });

  it("keys template achievements by their assigned parameters", () => {
    expect(achievementKey({ achievementId: "winInRoom", parameters: { roomKind: "bar" } })).toBe(
      achievementKey({ achievementId: "winInRoom", parameters: { roomKind: "bar" } }),
    );
    expect(achievementKey({ achievementId: "winInRoom", parameters: { roomKind: "bar" } })).not.toBe(
      achievementKey({ achievementId: "winInRoom", parameters: { roomKind: "stage" } }),
    );
    expect(achievementKey({ achievementId: "sameTacticSweep", parameters: { tactic: "reason" } })).not.toBe(
      achievementKey({ achievementId: "sameTacticSweep", parameters: { tactic: "spin" } }),
    );
  });

  it("uses precise debate session and round nomenclature in achievement language", () => {
    expect(achievementRuleByAssignment({ achievementId: "debateThreeCogs" })).toMatchObject({
      label: "Debate Three Opponents",
      description: "Starts debate sessions with different opponents.",
      condition: "Complete at least one round in debate sessions against three distinct opponents.",
    });
    expect(achievementRuleByAssignment({ achievementId: "witnessTeamWins", parameters: { team: "blue", rounds: 4 } })).toMatchObject({
      label: "Witness Blue Win 4 Rounds",
      description: "Watches Blue win 4 debate rounds.",
      condition: "Witness 4 rounds won by Blue.",
    });
    expect(achievementRuleByAssignment({ achievementId: "debateMarathon" })).toMatchObject({
      label: "Five-Round Debate",
      description: "Stays in a debate session until the final round.",
      condition: "Participate in a debate session that reaches round five.",
    });
    expect(achievementRuleByAssignment({ achievementId: "comebackRound" })).toMatchObject({
      label: "Comeback Round",
      description: "Wins a round after taking losses.",
      condition: "Win a round after at least one recorded round loss.",
    });
    expect(achievementRuleByAssignment({ achievementId: "perfectDebate" })).toMatchObject({
      label: "Perfect Rounds",
      description: "Builds a clean round win streak.",
      condition: "Record at least three round wins and zero round losses.",
    });
  });

  it("does not register removed portable-object achievements", () => {
    const removedToken = ["cr", "own"].join("");
    const achievementDir = fileURLToPath(new URL("../../src/shared/achievements/", import.meta.url));
    const implementationFiles = readdirSync(achievementDir).filter((file) => file.toLowerCase().includes(removedToken));
    const removedRules = ACHIEVEMENT_RULES.filter((rule) =>
      [rule.id, rule.label, rule.description, rule.condition].some((text) => text.toLowerCase().includes(removedToken)),
    );

    expect(implementationFiles).toEqual([]);
    expect(removedRules).toEqual([]);
  });

  it("does not register passive score or state achievements", () => {
    const meaninglessIds = [
      "achievementCollector",
      "firstTenPoints",
      "highDoubt",
      "teamRecruit",
      "twentyFivePoints",
    ];

    expect(ACHIEVEMENT_DEFINITIONS.map((achievement) => achievement.id)).not.toEqual(
      expect.arrayContaining(meaninglessIds),
    );
    expect(ACHIEVEMENT_RULES.map((rule) => rule.id)).not.toEqual(expect.arrayContaining(meaninglessIds));
  });

  it("does not register tactic-vs-tactic matchup achievements", () => {
    const matchupIds = [
      "beatPassionWithSpin",
      "beatReasonWithPassion",
      "beatSpinWithReason",
    ];

    expect(ACHIEVEMENT_DEFINITIONS.map((achievement) => achievement.id)).not.toEqual(
      expect.arrayContaining(matchupIds),
    );
    expect(ACHIEVEMENT_RULES.map((rule) => rule.id)).not.toEqual(expect.arrayContaining(matchupIds));
  });

  it("does not register trivial checklist achievements", () => {
    const trivialIds = [
      "barRegular",
      "centerStage",
      "debateStarter",
      "drawSpecialist",
      "loseWithPassion",
      "loseWithReason",
      "loseWithSpin",
      "majorityScorer",
      "moveFiveTimes",
      "passionWinner",
      "reasonWinner",
      "roomScout",
      "roundWinner",
      "socialButterfly",
      "spinWinner",
      "teamShifter",
      "underdogScorer",
      "witnessTeamWinsTwice",
    ];

    expect(ACHIEVEMENT_DEFINITIONS.map((achievement) => achievement.id)).not.toEqual(
      expect.arrayContaining(trivialIds),
    );
    expect(ACHIEVEMENT_RULES.map((rule) => rule.id)).not.toEqual(expect.arrayContaining(trivialIds));
  });

  it("evaluates every achievement checker against an empty context without throwing", () => {
    for (const achievement of ACHIEVEMENT_DEFINITIONS) {
      const result = achievement.isAchieved(context({ achievementId: achievement.id }));

      expect(typeof result).toBe("boolean");
    }
  });
});

describe("achievement checkers", () => {
  it("requires debate sessions against three distinct opponents", () => {
    const achievement = achievementDefinitionById("debateThreeCogs");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "debateThreeCogs",
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent-1", winnerCogId: "hero", winnerColor: "red" }),
            debateExchange({ firstId: "opponent-2", secondId: "hero", winnerCogId: "opponent-2", winnerColor: "blue" }),
            debateExchange({ firstId: "hero", secondId: "opponent-1", winnerCogId: "hero", winnerColor: "red" }),
            debateExchange({ firstId: "opponent-3", secondId: "hero", winnerCogId: "hero", winnerColor: "red" }),
          ],
        }),
      ),
    ).toBe(true);

    expect(
      achievement.isAchieved(
        context({
          achievementId: "debateThreeCogs",
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent-1", winnerCogId: "hero", winnerColor: "red" }),
            debateExchange({ firstId: "opponent-2", secondId: "hero", winnerCogId: "opponent-2", winnerColor: "blue" }),
          ],
        }),
      ),
    ).toBe(false);
  });

  it("requires winning a round in the assigned room kind", () => {
    const achievement = achievementDefinitionById("winInRoom");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "winInRoom",
          parameters: { roomKind: "stage" },
          cog: { ...baseCog(), location: { roomId: "stage", spotId: "stage-left" } },
          snapshot: snapshot({
            cogs: [
              { ...baseCog(), location: { roomId: "stage", spotId: "stage-left" } },
              { ...baseCog("opponent", "blue"), location: { roomId: "stage", spotId: "stage-right" } },
            ],
          }),
          events: [debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red" })],
        }),
      ),
    ).toBe(true);

    expect(
      achievement.isAchieved(
        context({
          achievementId: "winInRoom",
          parameters: { roomKind: "stage" },
          cog: { ...baseCog(), location: { roomId: "bar", spotId: "bar-left" } },
          snapshot: snapshot({
            cogs: [
              { ...baseCog(), location: { roomId: "bar", spotId: "bar-left" } },
              { ...baseCog("opponent", "blue"), location: { roomId: "bar", spotId: "bar-right" } },
            ],
          }),
          events: [debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red" })],
        }),
      ),
    ).toBe(false);
  });

  it("counts witnessing the assigned number of rounds where the assigned team wins", () => {
    const achievement = achievementDefinitionById("witnessTeamWins");
    const redWin = (index: number): WorldEvent =>
      debateExchange({
        firstId: `red-${index}`,
        secondId: `blue-${index}`,
        winnerCogId: `red-${index}`,
        winnerColor: "red",
        witnessCogIds: ["hero"],
        tick: index + 1,
      });

    expect(
      achievement.isAchieved(
        context({
          achievementId: "witnessTeamWins",
          parameters: { team: "red", rounds: 3 },
          events: [redWin(1), redWin(2), redWin(3)],
        }),
      ),
    ).toBe(true);

    expect(
      achievement.isAchieved(
        context({
          achievementId: "witnessTeamWins",
          parameters: { team: "red", rounds: 4 },
          events: [redWin(1), redWin(2), redWin(3)],
        }),
      ),
    ).toBe(false);
  });

  it("detects participating in a debate session that reaches round five", () => {
    const achievement = achievementDefinitionById("debateMarathon");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "debateMarathon",
          events: [debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "opponent", winnerColor: "blue", tick: 5 })],
        }),
      ),
    ).toBe(true);

    expect(
      achievement.isAchieved(
        context({
          achievementId: "debateMarathon",
          events: [debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red", tick: 4 })],
        }),
      ),
    ).toBe(false);
  });

  it("detects a comeback round after a prior round loss", () => {
    const achievement = achievementDefinitionById("comebackRound");
    const cogWithLoss = { ...baseCog(), stats: { argumentsWon: 0, argumentsLost: 1, teamFlips: 0 } };

    expect(
      achievement.isAchieved(
        context({
          achievementId: "comebackRound",
          cog: cogWithLoss,
          events: [debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red" })],
        }),
      ),
    ).toBe(true);

    expect(
      achievement.isAchieved(
        context({
          achievementId: "comebackRound",
          events: [debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red" })],
        }),
      ),
    ).toBe(false);
  });

  it("detects Perfect Rounds from three round wins and no round losses", () => {
    const achievement = achievementDefinitionById("perfectDebate");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "perfectDebate",
          cog: { ...baseCog(), stats: { argumentsWon: 3, argumentsLost: 0, teamFlips: 0 } },
        }),
      ),
    ).toBe(true);

    expect(
      achievement.isAchieved(
        context({
          achievementId: "perfectDebate",
          cog: { ...baseCog(), stats: { argumentsWon: 3, argumentsLost: 1, teamFlips: 0 } },
        }),
      ),
    ).toBe(false);
  });

  it("detects FlipFlop after two team flips", () => {
    const achievement = achievementDefinitionById("flipFlop");

    expect(achievement.name).toBe("FlipFlop");
    expect(ACHIEVEMENT_DEFINITIONS.map((candidate) => candidate.id)).not.toContain("tripleTeamFlip");
    expect(achievement.condition).toBe("Flip teams twice before the timer expires.");
    expect(
      achievement.isAchieved(
        context({
          achievementId: "flipFlop",
          events: [
            colorChange("hero", 1),
            colorChange("hero", 2),
          ],
        }),
      ),
    ).toBe(true);
  });

  it("detects losing a round to a parameterized trait", () => {
    const achievement = achievementDefinitionById("loseToTrait");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "loseToTrait",
          parameters: { trait: "charismatic" },
          snapshot: snapshot({
            cogs: [baseCog(), { ...baseCog("opponent", "blue"), activeTrait: "charismatic" }],
          }),
          events: [debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "opponent", winnerColor: "blue" })],
        }),
      ),
    ).toBe(true);

    expect(
      achievement.isAchieved(
        context({
          achievementId: "loseToTrait",
          parameters: { trait: "avenger" },
          snapshot: snapshot({
            cogs: [baseCog(), { ...baseCog("opponent", "blue"), activeTrait: "charismatic" }],
          }),
          events: [debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "opponent", winnerColor: "blue" })],
        }),
      ),
    ).toBe(false);
  });

  it("detects parameterized team witness achievements", () => {
    expect(
      achievementDefinitionById("witnessTeamWins").isAchieved(
        context({
          achievementId: "witnessTeamWins",
          parameters: { team: "blue", rounds: 2 },
          events: [1, 2].map((tick) =>
            debateExchange({
              firstId: `blue-${tick}`,
              secondId: `red-${tick}`,
              winnerCogId: `blue-${tick}`,
              winnerColor: "blue",
              witnessCogIds: ["hero"],
              tick,
            }),
          ),
        }),
      ),
    ).toBe(true);
  });

  it("detects winning the final round", () => {
    const achievement = achievementDefinitionById("winFinalRound");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "winFinalRound",
          events: [debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red", round: 5 })],
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "winFinalRound",
          events: [debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red", round: 4 })],
        }),
      ),
    ).toBe(false);
  });

  it("detects winning after two recorded round losses", () => {
    const achievement = achievementDefinitionById("winAfterTwoLosses");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "winAfterTwoLosses",
          cog: { ...baseCog(), stats: { argumentsWon: 0, argumentsLost: 2, teamFlips: 0 } },
          events: [debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red" })],
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "winAfterTwoLosses",
          cog: { ...baseCog(), stats: { argumentsWon: 0, argumentsLost: 1, teamFlips: 0 } },
          events: [debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red" })],
        }),
      ),
    ).toBe(false);
  });

  it("detects beating a cog with the assigned trait", () => {
    const achievement = achievementDefinitionById("beatTrait");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "beatTrait",
          parameters: { trait: "avenger" },
          snapshot: snapshot({
            cogs: [baseCog(), { ...baseCog("opponent", "blue"), activeTrait: "avenger" }],
          }),
          events: [debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red" })],
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "beatTrait",
          parameters: { trait: "charismatic" },
          snapshot: snapshot({
            cogs: [baseCog(), { ...baseCog("opponent", "blue"), activeTrait: "avenger" }],
          }),
          events: [debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red" })],
        }),
      ),
    ).toBe(false);
  });

  it("detects defeating an assigned opponent twice", () => {
    const achievement = achievementDefinitionById("defeatOpponentTwice");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "defeatOpponentTwice",
          parameters: { cogId: "opponent", cogName: "Opal" },
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red", tick: 1 }),
            debateExchange({ firstId: "opponent", secondId: "hero", winnerCogId: "hero", winnerColor: "red", tick: 2 }),
          ],
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "defeatOpponentTwice",
          parameters: { cogId: "opponent", cogName: "Opal" },
          events: [debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red", tick: 1 })],
        }),
      ),
    ).toBe(false);
  });

  it("detects witnessing a team comeback round", () => {
    const achievement = achievementDefinitionById("witnessComeback");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "witnessComeback",
          parameters: { team: "red" },
          events: [
            debateExchange({ firstId: "red-1", secondId: "blue-1", winnerCogId: "blue-1", winnerColor: "blue", round: 1, tick: 1 }),
            debateExchange({
              firstId: "red-1",
              secondId: "blue-1",
              winnerCogId: "red-1",
              winnerColor: "red",
              witnessCogIds: ["hero"],
              round: 2,
              tick: 2,
            }),
          ],
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "witnessComeback",
          parameters: { team: "red" },
          events: [
            debateExchange({ firstId: "red-1", secondId: "blue-1", winnerCogId: "red-1", winnerColor: "red", round: 1, tick: 1 }),
            debateExchange({
              firstId: "red-1",
              secondId: "blue-1",
              winnerCogId: "red-1",
              winnerColor: "red",
              witnessCogIds: ["hero"],
              round: 2,
              tick: 2,
            }),
          ],
        }),
      ),
    ).toBe(false);
  });

  it("detects sweeping a debate session", () => {
    const achievement = achievementDefinitionById("sweepDebate");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "sweepDebate",
          events: [1, 2, 3].map((round) =>
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red", round, tick: round }),
          ),
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "sweepDebate",
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red", round: 1, tick: 1 }),
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "opponent", winnerColor: "blue", round: 2, tick: 2 }),
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red", round: 3, tick: 3 }),
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red", round: 4, tick: 4 }),
          ],
        }),
      ),
    ).toBe(false);
  });

  it("detects winning with all three debate tactics", () => {
    const achievement = achievementDefinitionById("winWithAllTactics");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "winWithAllTactics",
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent-1", firstAction: "reason", secondAction: "spin", winnerCogId: "hero", winnerColor: "red" }),
            debateExchange({ firstId: "hero", secondId: "opponent-2", firstAction: "spin", secondAction: "passion", winnerCogId: "hero", winnerColor: "red" }),
            debateExchange({ firstId: "hero", secondId: "opponent-3", firstAction: "passion", secondAction: "reason", winnerCogId: "hero", winnerColor: "red" }),
          ],
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "winWithAllTactics",
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent-1", firstAction: "reason", secondAction: "spin", winnerCogId: "hero", winnerColor: "red" }),
            debateExchange({ firstId: "hero", secondId: "opponent-2", firstAction: "spin", secondAction: "passion", winnerCogId: "hero", winnerColor: "red" }),
          ],
        }),
      ),
    ).toBe(false);
  });

  it("detects room specialist wins", () => {
    const achievement = achievementDefinitionById("roomSpecialist");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "roomSpecialist",
          parameters: { roomKind: "stage", rounds: 2 },
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent-1", winnerCogId: "hero", winnerColor: "red", roomKind: "stage", tick: 1 }),
            debateExchange({ firstId: "hero", secondId: "opponent-2", winnerCogId: "hero", winnerColor: "red", roomKind: "stage", tick: 2 }),
          ],
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "roomSpecialist",
          parameters: { roomKind: "stage", rounds: 2 },
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent-1", winnerCogId: "hero", winnerColor: "red", roomKind: "stage", tick: 1 }),
            debateExchange({ firstId: "hero", secondId: "opponent-2", winnerCogId: "hero", winnerColor: "red", roomKind: "bar", tick: 2 }),
          ],
        }),
      ),
    ).toBe(false);
  });

  it("detects traveling debater wins across three room kinds", () => {
    const achievement = achievementDefinitionById("travelingDebater");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "travelingDebater",
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent-1", winnerCogId: "hero", winnerColor: "red", roomKind: "bar", tick: 1 }),
            debateExchange({ firstId: "hero", secondId: "opponent-2", winnerCogId: "hero", winnerColor: "red", roomKind: "stage", tick: 2 }),
            debateExchange({ firstId: "hero", secondId: "opponent-3", winnerCogId: "hero", winnerColor: "red", roomKind: "lounge", tick: 3 }),
          ],
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "travelingDebater",
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent-1", winnerCogId: "hero", winnerColor: "red", roomKind: "bar", tick: 1 }),
            debateExchange({ firstId: "hero", secondId: "opponent-2", winnerCogId: "hero", winnerColor: "red", roomKind: "stage", tick: 2 }),
          ],
        }),
      ),
    ).toBe(false);
  });

  it("detects witnessing a conversion from a witnessed debate", () => {
    const achievement = achievementDefinitionById("witnessConversion");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "witnessConversion",
          events: [
            debateExchange({ firstId: "red-1", secondId: "blue-1", winnerCogId: "red-1", winnerColor: "red", witnessCogIds: ["hero"], tick: 1 }),
            colorChange("blue-1", 1),
          ],
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "witnessConversion",
          events: [
            debateExchange({ firstId: "red-1", secondId: "blue-1", winnerCogId: "red-1", winnerColor: "red", tick: 1 }),
            colorChange("blue-1", 1),
          ],
        }),
      ),
    ).toBe(false);
  });

  it("detects losing assigned rounds to cogs with a trait", () => {
    const achievement = achievementDefinitionById("traitNemesis");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "traitNemesis",
          parameters: { trait: "charismatic", rounds: 2 },
          snapshot: snapshot({
            cogs: [baseCog(), { ...baseCog("opponent-1", "blue"), activeTrait: "charismatic" }, { ...baseCog("opponent-2", "blue"), activeTrait: "charismatic" }],
          }),
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent-1", winnerCogId: "opponent-1", winnerColor: "blue", tick: 1 }),
            debateExchange({ firstId: "hero", secondId: "opponent-2", winnerCogId: "opponent-2", winnerColor: "blue", tick: 2 }),
          ],
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "traitNemesis",
          parameters: { trait: "charismatic", rounds: 2 },
          snapshot: snapshot({
            cogs: [baseCog(), { ...baseCog("opponent-1", "blue"), activeTrait: "charismatic" }, { ...baseCog("opponent-2", "blue"), activeTrait: "avenger" }],
          }),
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent-1", winnerCogId: "opponent-1", winnerColor: "blue", tick: 1 }),
            debateExchange({ firstId: "hero", secondId: "opponent-2", winnerCogId: "opponent-2", winnerColor: "blue", tick: 2 }),
          ],
        }),
      ),
    ).toBe(false);
  });

  it("detects revenge against an assigned opponent", () => {
    const achievement = achievementDefinitionById("revengeRound");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "revengeRound",
          parameters: { cogId: "opponent", cogName: "Opal" },
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "opponent", winnerColor: "blue", tick: 1 }),
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red", tick: 2 }),
          ],
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "revengeRound",
          parameters: { cogId: "opponent", cogName: "Opal" },
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red", tick: 1 }),
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "opponent", winnerColor: "blue", tick: 2 }),
          ],
        }),
      ),
    ).toBe(false);
  });

  it("detects low certainty wins", () => {
    const achievement = achievementDefinitionById("lowCertaintyWin");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "lowCertaintyWin",
          cog: { ...baseCog(), certainty: 20 },
          events: [debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red" })],
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "lowCertaintyWin",
          cog: { ...baseCog(), certainty: 40 },
          events: [debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red" })],
        }),
      ),
    ).toBe(false);
  });

  it("detects a social circuit across opponents and rooms", () => {
    const achievement = achievementDefinitionById("socialCircuit");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "socialCircuit",
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent-1", winnerCogId: "hero", winnerColor: "red", roomKind: "bar", tick: 1 }),
            debateExchange({ firstId: "hero", secondId: "opponent-2", winnerCogId: "opponent-2", winnerColor: "blue", roomKind: "stage", tick: 2 }),
            debateExchange({ firstId: "opponent-3", secondId: "hero", winnerCogId: "hero", winnerColor: "red", roomKind: "lounge", tick: 3 }),
          ],
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "socialCircuit",
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent-1", winnerCogId: "hero", winnerColor: "red", roomKind: "bar", tick: 1 }),
            debateExchange({ firstId: "hero", secondId: "opponent-2", winnerCogId: "opponent-2", winnerColor: "blue", roomKind: "stage", tick: 2 }),
            debateExchange({ firstId: "opponent-1", secondId: "hero", winnerCogId: "hero", winnerColor: "red", roomKind: "lounge", tick: 3 }),
          ],
        }),
      ),
    ).toBe(false);
  });

  it("detects witnessing underdog team wins", () => {
    const achievement = achievementDefinitionById("underdogWitness");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "underdogWitness",
          snapshot: snapshot({
            cogs: [
              baseCog(),
              baseCog("red-1", "red"),
              baseCog("blue-1", "blue"),
              baseCog("blue-2", "blue"),
              baseCog("blue-3", "blue"),
            ],
          }),
          events: [1, 2, 3].map((tick) =>
            debateExchange({
              firstId: `red-${tick}`,
              secondId: `blue-${tick}`,
              winnerCogId: `red-${tick}`,
              winnerColor: "red",
              witnessCogIds: ["hero"],
              tick,
            }),
          ),
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "underdogWitness",
          snapshot: snapshot({
            cogs: [baseCog(), baseCog("red-1", "red"), baseCog("blue-1", "blue")],
          }),
          events: [1, 2, 3].map((tick) =>
            debateExchange({
              firstId: `red-${tick}`,
              secondId: `blue-${tick}`,
              winnerCogId: `red-${tick}`,
              winnerColor: "red",
              witnessCogIds: ["hero"],
              tick,
            }),
          ),
        }),
      ),
    ).toBe(false);
  });

  it("detects breaking a draw in the next same-session round", () => {
    const achievement = achievementDefinitionById("drawBreaker");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "drawBreaker",
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent", outcome: "draw", round: 1, tick: 1 }),
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red", round: 2, tick: 2 }),
          ],
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "drawBreaker",
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent", outcome: "draw", round: 1, tick: 1 }),
            debateExchange({ firstId: "opponent", secondId: "hero", winnerCogId: "opponent", winnerColor: "blue", round: 2, tick: 2 }),
          ],
        }),
      ),
    ).toBe(false);
  });

  it("detects denying a sweep after two opening losses", () => {
    const achievement = achievementDefinitionById("denySweep");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "denySweep",
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "opponent", winnerColor: "blue", round: 1, tick: 1 }),
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "opponent", winnerColor: "blue", round: 2, tick: 2 }),
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red", round: 3, tick: 3 }),
          ],
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "denySweep",
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "opponent", winnerColor: "blue", round: 1, tick: 1 }),
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red", round: 2, tick: 2 }),
          ],
        }),
      ),
    ).toBe(false);
  });

  it("detects converting an opponent after a debate round", () => {
    const achievement = achievementDefinitionById("convertOpponent");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "convertOpponent",
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red", tick: 1 }),
            colorChange("opponent", 1),
          ],
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "convertOpponent",
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red", tick: 1 }),
            colorChange("hero", 1),
          ],
        }),
      ),
    ).toBe(false);
  });

  it("detects witnessing a final debate round", () => {
    const achievement = achievementDefinitionById("finalRoundWitness");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "finalRoundWitness",
          events: [debateExchange({ firstId: "red-1", secondId: "blue-1", winnerCogId: "red-1", winnerColor: "red", witnessCogIds: ["hero"], round: 5 })],
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "finalRoundWitness",
          events: [debateExchange({ firstId: "red-1", secondId: "blue-1", winnerCogId: "red-1", winnerColor: "red", witnessCogIds: ["hero"], round: 4 })],
        }),
      ),
    ).toBe(false);
  });

  it("detects winning a debate after falling behind", () => {
    const achievement = achievementDefinitionById("winFromBehind");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "winFromBehind",
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "opponent", winnerColor: "blue", round: 1, tick: 1 }),
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "opponent", winnerColor: "blue", round: 2, tick: 2 }),
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red", round: 3, tick: 3 }),
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red", round: 4, tick: 4 }),
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red", round: 5, tick: 5 }),
          ],
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "winFromBehind",
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "opponent", winnerColor: "blue", round: 1, tick: 1 }),
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red", round: 2, tick: 2 }),
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red", round: 3, tick: 3 }),
          ],
        }),
      ),
    ).toBe(false);
  });

  it("detects sweeping with one assigned tactic", () => {
    const achievement = achievementDefinitionById("sameTacticSweep");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "sameTacticSweep",
          parameters: { tactic: "reason" },
          events: [1, 2, 3].map((tick) =>
            debateExchange({ firstId: "hero", secondId: `opponent-${tick}`, firstAction: "reason", secondAction: "spin", winnerCogId: "hero", winnerColor: "red", tick }),
          ),
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "sameTacticSweep",
          parameters: { tactic: "reason" },
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent-1", firstAction: "reason", secondAction: "spin", winnerCogId: "hero", winnerColor: "red", tick: 1 }),
            debateExchange({ firstId: "hero", secondId: "opponent-2", firstAction: "spin", secondAction: "passion", winnerCogId: "hero", winnerColor: "red", tick: 2 }),
            debateExchange({ firstId: "hero", secondId: "opponent-3", firstAction: "reason", secondAction: "spin", winnerCogId: "hero", winnerColor: "red", tick: 3 }),
          ],
        }),
      ),
    ).toBe(false);
  });

  it("detects countering back after a loss", () => {
    const achievement = achievementDefinitionById("counterComeback");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "counterComeback",
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent", firstAction: "spin", secondAction: "reason", winnerCogId: "opponent", winnerColor: "blue", round: 1, tick: 1 }),
            debateExchange({ firstId: "hero", secondId: "opponent", firstAction: "passion", secondAction: "reason", winnerCogId: "hero", winnerColor: "red", round: 2, tick: 2 }),
          ],
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "counterComeback",
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent", firstAction: "spin", secondAction: "reason", winnerCogId: "opponent", winnerColor: "blue", round: 1, tick: 1 }),
            debateExchange({ firstId: "hero", secondId: "opponent", firstAction: "reason", secondAction: "passion", winnerCogId: "hero", winnerColor: "red", round: 2, tick: 2 }),
          ],
        }),
      ),
    ).toBe(false);
  });

  it("detects a comeback in an assigned room", () => {
    const achievement = achievementDefinitionById("roomComeback");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "roomComeback",
          parameters: { roomKind: "stage" },
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "opponent", winnerColor: "blue", roomKind: "stage", tick: 1 }),
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red", roomKind: "stage", tick: 2 }),
          ],
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "roomComeback",
          parameters: { roomKind: "stage" },
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "opponent", winnerColor: "blue", roomKind: "stage", tick: 1 }),
            debateExchange({ firstId: "hero", secondId: "opponent", winnerCogId: "hero", winnerColor: "red", roomKind: "bar", tick: 2 }),
          ],
        }),
      ),
    ).toBe(false);
  });

  it("detects trait hunter wins", () => {
    const achievement = achievementDefinitionById("traitHunter");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "traitHunter",
          parameters: { trait: "swift", rounds: 2 },
          snapshot: snapshot({
            cogs: [baseCog(), { ...baseCog("opponent-1", "blue"), activeTrait: "swift" }, { ...baseCog("opponent-2", "blue"), activeTrait: "swift" }],
          }),
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent-1", winnerCogId: "hero", winnerColor: "red", tick: 1 }),
            debateExchange({ firstId: "hero", secondId: "opponent-2", winnerCogId: "hero", winnerColor: "red", tick: 2 }),
          ],
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "traitHunter",
          parameters: { trait: "swift", rounds: 2 },
          snapshot: snapshot({
            cogs: [baseCog(), { ...baseCog("opponent-1", "blue"), activeTrait: "swift" }, { ...baseCog("opponent-2", "blue"), activeTrait: "charismatic" }],
          }),
          events: [
            debateExchange({ firstId: "hero", secondId: "opponent-1", winnerCogId: "hero", winnerColor: "red", tick: 1 }),
            debateExchange({ firstId: "hero", secondId: "opponent-2", winnerCogId: "hero", winnerColor: "red", tick: 2 }),
          ],
        }),
      ),
    ).toBe(false);
  });

  it("detects witnessing two different conversions", () => {
    const achievement = achievementDefinitionById("conversionWitnessStreak");

    expect(
      achievement.isAchieved(
        context({
          achievementId: "conversionWitnessStreak",
          events: [
            debateExchange({ firstId: "red-1", secondId: "blue-1", winnerCogId: "red-1", winnerColor: "red", witnessCogIds: ["hero"], tick: 1 }),
            colorChange("blue-1", 1),
            debateExchange({ firstId: "red-2", secondId: "blue-2", winnerCogId: "red-2", winnerColor: "red", witnessCogIds: ["hero"], tick: 2 }),
            colorChange("blue-2", 2),
          ],
        }),
      ),
    ).toBe(true);
    expect(
      achievement.isAchieved(
        context({
          achievementId: "conversionWitnessStreak",
          events: [
            debateExchange({ firstId: "red-1", secondId: "blue-1", winnerCogId: "red-1", winnerColor: "red", witnessCogIds: ["hero"], tick: 1 }),
            colorChange("blue-1", 1),
            debateExchange({ firstId: "red-2", secondId: "blue-2", winnerCogId: "red-2", winnerColor: "red", tick: 2 }),
            colorChange("blue-2", 2),
          ],
        }),
      ),
    ).toBe(false);
  });
});

function context(input: {
  achievementId: AchievementAssignment["achievementId"];
  parameters?: AchievementAssignment["parameters"];
  cog?: Cog;
  events?: WorldEvent[];
  snapshot?: WorldSnapshot;
}) {
  const assignment: AchievementAssignment = {
    assignmentId: "assignment",
    achievementId: input.achievementId,
    parameters: input.parameters,
    assignedTick: 0,
    timeoutTick: 100,
  };
  const cog = input.cog ?? baseCog();
  const worldSnapshot = input.snapshot ?? snapshot({ cogs: [cog] });

  return {
    assignment,
    cog,
    events: input.events ?? [],
    snapshot: worldSnapshot,
    tick: worldSnapshot.tick,
  };
}

function baseCog(id = "hero", color: "red" | "blue" = "red"): Cog {
  return {
    id,
    name: id,
    behaviorPrompt: "",
    position: { x: 1, y: 1 },
    location: { roomId: "bar", spotId: `${id}-spot` },
    spriteSheetKey: "cog-default",
    attributes: {},
    color,
    defensiveTrait: "stubborn",
    activeTrait: "forceful",
    personalGoal: "majority",
    activity: "idle",
    personalScore: 0,
    achievements: [],
    completedAchievements: [],
    goalScores: [],
    stats: { argumentsWon: 0, argumentsLost: 0, teamFlips: 0 },
    certainty: 100,
    controllerId: "stub",
    movementCooldown: 0,
    conversationLog: [],
  };
}

function snapshot(input: { cogs?: Cog[] } = {}): WorldSnapshot {
  return {
    tick: 10,
    dimensions: { width: 20, height: 20 },
    venue: {
      rooms: [
        { id: "bar", label: "Bar", kind: "bar", spotIds: ["bar-left", "bar-right"], neighborIds: ["stage"] },
        { id: "stage", label: "Stage", kind: "stage", spotIds: ["stage-left", "stage-right"], neighborIds: ["bar"] },
      ],
      spots: [
        { id: "bar-left", roomId: "bar", label: "Bar Left", position: { x: 1, y: 1 } },
        { id: "bar-right", roomId: "bar", label: "Bar Right", position: { x: 2, y: 1 } },
        { id: "stage-left", roomId: "stage", label: "Stage Left", position: { x: 5, y: 1 } },
        { id: "stage-right", roomId: "stage", label: "Stage Right", position: { x: 6, y: 1 } },
      ],
      spotLinks: [
        { id: "bar-left__bar-right", fromSpotId: "bar-left", toSpotId: "bar-right" },
        { id: "stage-left__stage-right", fromSpotId: "stage-left", toSpotId: "stage-right" },
      ],
      roomPaths: [],
    },
    cogs: input.cogs ?? [baseCog()],
    objects: [],
    terrain: [],
    recentEvents: [],
  };
}

function debateExchange(input: {
  firstId: string;
  secondId: string;
  winnerCogId?: string;
  winnerColor?: "red" | "blue";
  outcome?: "win" | "lose" | "draw";
  firstAction?: DebateTactic;
  secondAction?: DebateTactic;
  witnessCogIds?: string[];
  roomKind?: VenueRoomKind;
  round?: number;
  tick?: number;
}): WorldEvent {
  const round = input.round ?? input.tick ?? 1;
  return {
    id: `event-${input.firstId}-${input.secondId}-${input.tick ?? 1}`,
    tick: input.tick ?? 1,
    type: "debateExchange",
    actorId: input.winnerCogId,
    targetId: input.winnerCogId ? (input.winnerCogId === input.firstId ? input.secondId : input.firstId) : input.secondId,
    message: "debate",
    debate: {
      actions: [
        { cogId: input.firstId, action: input.firstAction ?? "reason" },
        { cogId: input.secondId, action: input.secondAction ?? "spin" },
      ],
      choicesRevealedAtTick: input.tick ?? 1,
      resultRevealedAtTick: input.tick ?? 1,
      expiresAtTick: input.tick ?? 1,
      outcome: input.outcome ?? (input.winnerCogId === input.firstId ? "win" : "lose"),
      round,
      winnerCogId: input.winnerCogId,
      winnerColor: input.winnerColor,
      witnessCogIds: input.witnessCogIds,
      roomKind: input.roomKind,
    },
  };
}

function colorChange(actorId: string, tick: number): WorldEvent {
  return {
    id: `color-change-${tick}`,
    tick,
    type: "colorChange",
    actorId,
    message: "changed color",
  };
}
