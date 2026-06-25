import { describe, expect, it } from "vitest";

import { renderConfigPage, type ConfigPayload } from "../../src/client/ui/hud";
import { ACHIEVEMENT_RULES, DEFAULT_GAME_CONFIG, RULE_PARAMETERS, TRAIT_RULES } from "../../src/shared/rules";
import type { WorldSnapshot } from "../../src/shared/types";

function configPayload(): ConfigPayload {
  return {
    config: DEFAULT_GAME_CONFIG,
    parameters: RULE_PARAMETERS,
    traits: TRAIT_RULES,
    goals: [],
    achievements: ACHIEVEMENT_RULES,
  };
}

describe("settings timing", () => {
  it("shows timing constants as seconds in their own settings tab", () => {
    const markup = renderConfigPage(configPayload(), "timing");

    expect(markup).toContain('data-config-tab="timing"');
    expect(markup).toContain("Debate prep");
    expect(markup).toContain('data-config-seconds-key="debatePrepTicks"');
    expect(markup).toContain('value="1"');
    expect(markup).toContain("Choice reveal");
    expect(markup).toContain('data-config-seconds-key="debateChoiceRevealTicks"');
    expect(markup).toContain('value="1"');
    expect(markup).toContain("Result reveal");
    expect(markup).toContain('data-config-seconds-key="debateResultTicks"');
    expect(markup).toContain('value="3"');
    expect(markup).toContain("Room move cooldown");
    expect(markup).toContain('data-config-seconds-key="roomMoveCooldownTicks"');
    expect(markup).toContain('value="60"');
    expect(markup).toContain("ticks at 2 tps");
  });

  it("keeps timing constants out of the generic params controls", () => {
    const markup = renderConfigPage(configPayload(), "params");

    expect(markup).toContain('data-config-key="debateDoubt"');
    expect(markup).toContain('data-config-key="debateWinCertaintyGain"');
    expect(markup).not.toContain('data-config-key="debatePrepTicks"');
    expect(markup).not.toContain("Debate prep ticks");
  });

  it("exposes the venue editor as a settings tab", () => {
    const markup = renderConfigPage(configPayload(), "venue");

    expect(markup).toContain('data-config-tab="venue"');
    expect(markup).toContain('aria-label="Venue"');
    expect(markup).toContain("data-venue-editor-host");
  });

  it("shows achievement conditions with timeout seconds and points together", () => {
    const markup = renderConfigPage(configPayload(), "achievements");

    expect(markup).toContain('data-config-tab="achievements"');
    expect(markup).toContain('aria-label="Achievements"');
    expect(markup).toContain("Debate Three Opponents");
    expect(markup).toContain("Complete at least one round in debate sessions against three distinct opponents.");
    expect(markup).toContain('class="config-achievement-meta"');
    expect(markup).toContain("450s");
    expect(markup).toContain("10 pts");
    expect(markup).not.toContain("timeout 180 ticks at 0.5s/tick");
  });

  it("shows achievement assigned, completed, current, and expired counts", () => {
    const markup = renderConfigPage(configPayload(), "achievements", snapshotWithAchievementCounts());

    expect(markup).toContain('class="config-achievement-counts"');
    expect(markup).toContain("assigned 4");
    expect(markup).toContain("completed 2");
    expect(markup).toContain("current 1");
    expect(markup).toContain("expired 1");
  });

  it("aggregates parameterized achievement counts under the template row", () => {
    const markup = renderConfigPage(configPayload(), "achievements", snapshotWithParameterizedAchievementCounts());

    expect(markup).toContain("Win Round in [ROOM]");
    expect(markup).toContain("assigned 5");
    expect(markup).toContain("completed 3");
    expect(markup).toContain("current 3");
    expect(markup).toContain("expired 1");
  });

  it("shows concise player and guidance descriptions for traits", () => {
    const payload = configPayload();
    payload.config = {
      ...payload.config,
      traitConfig: {
        ...payload.config.traitConfig,
        iconoclast: { dominantDoubtMultiplier: 0.6 },
      },
    };
    const traitMarkup = renderConfigPage(payload, "traits");

    expect(traitMarkup).toContain("Player:</strong> Largest-team pressure hurts 40% less.");
    expect(traitMarkup).toContain("Guidance:</strong> Largest-team pressure costs 40% less certainty.");
    expect(traitMarkup).not.toContain("configured");
    expect(traitMarkup).not.toContain("TeamGoals");
  });

  it("shows debate log entries with plays, certainty deltas, and conversions", () => {
    const markup = renderConfigPage(configPayload(), "debates", snapshotWithDebateLog());

    expect(markup).toContain('data-config-tab="debates"');
    expect(markup).toContain('aria-label="Debates"');
    expect(markup).toContain("Red");
    expect(markup).toContain("reason");
    expect(markup).toContain("Blue");
    expect(markup).toContain("spin");
    expect(markup).toContain("certainty +10");
    expect(markup).toContain("certainty -10");
    expect(markup).toContain("blue -> red");
  });

  it("renders preset choices without a native select menu", () => {
    const markup = renderConfigPage(
      {
        ...configPayload(),
        settingsDb: "david",
        presets: [
          { settingsDb: "default", name: "Default", updatedAt: "2026-05-11T00:00:00.000Z" },
          { settingsDb: "david", name: "david", updatedAt: "2026-05-11T00:00:00.000Z" },
        ],
      },
      "params",
    );

    expect(markup).not.toContain("<select");
    expect(markup).not.toContain("<option");
    expect(markup).toContain('data-settings-preset-choice="david"');
    expect(markup).toContain('aria-pressed="true"');
  });
});

function snapshotWithAchievementCounts(): WorldSnapshot {
  return {
    tick: 12,
    dimensions: { width: 10, height: 10 },
    cogs: [],
    objects: [],
    terrain: [],
    recentEvents: [],
    achievementCounts: [
      {
        achievementId: "debateThreeCogs",
        assigned: 4,
        completed: 2,
        current: 1,
        expired: 1,
      },
    ],
  };
}

function snapshotWithParameterizedAchievementCounts(): WorldSnapshot {
  return {
    tick: 12,
    dimensions: { width: 10, height: 10 },
    cogs: [],
    objects: [],
    terrain: [],
    recentEvents: [],
    achievementCounts: [
      {
        achievementId: "winInRoom",
        parameters: { roomKind: "bar" },
        assigned: 2,
        completed: 1,
        current: 1,
        expired: 0,
      },
      {
        achievementId: "winInRoom",
        parameters: { roomKind: "stage" },
        assigned: 3,
        completed: 2,
        current: 2,
        expired: 1,
      },
    ],
  };
}

function snapshotWithDebateLog(): WorldSnapshot {
  return {
    tick: 12,
    dimensions: { width: 10, height: 10 },
    cogs: [],
    objects: [],
    terrain: [],
    recentEvents: [],
    achievementCounts: [],
    debateLog: [
      {
        id: "debate_log_1",
        tick: 7,
        round: 1,
        outcome: "win",
        winnerCogId: "red",
        winnerColor: "red",
        actions: [
          { cogId: "red", cogName: "Red", color: "red", tactic: "reason" },
          { cogId: "blue", cogName: "Blue", color: "blue", tactic: "spin" },
        ],
        changes: [
          {
            cogId: "red",
            cogName: "Red",
            role: "participant",
            colorBefore: "red",
            colorAfter: "red",
            certaintyBefore: 480,
            certaintyAfter: 490,
            certaintyDelta: 10,
          },
          {
            cogId: "blue",
            cogName: "Blue",
            role: "participant",
            colorBefore: "blue",
            colorAfter: "red",
            certaintyBefore: 1,
            certaintyAfter: 490,
            certaintyDelta: -10,
          },
        ],
        conversions: [
          {
            cogId: "blue",
            cogName: "Blue",
            fromColor: "blue",
            toColor: "red",
            certaintyBefore: 1,
            certaintyAfter: 490,
          },
        ],
      },
    ],
  } as WorldSnapshot;
}
