import { describe, expect, it } from "vitest";

import { renderCogProfilePage, renderProfileAchievements } from "../../src/client/ui/hud";
import type { Cog } from "../../src/shared/types";

const cog: Cog = {
  id: "cog-ada",
  name: "Ada",
  behaviorPrompt: "",
  position: { x: 2, y: 3 },
  spriteSheetKey: "cog-ada",
  attributes: {},
  color: "red",
  defensiveTrait: "stubborn",
  activeTrait: "forceful",
  personalGoal: "majority",
  personalScore: 5,
  achievements: [
    {
      achievementId: "debateThreeCogs",
      assignedTick: 10,
      assignmentId: "active-debate-three",
      timeoutTick: 70,
    },
  ],
  completedAchievements: [
    {
      achievementId: "winInRoom",
      assignedTick: 1,
      assignmentId: "completed-bar-debate",
      completedTick: 8,
      parameters: { roomKind: "bar" },
      points: 10,
      timeoutTick: 80,
    },
  ],
  goalScores: [
    {
      goal: "majority",
      points: 5,
      history: [
        { tick: 0, points: 0 },
        { tick: 1, points: 2 },
        { tick: 2, points: 5 },
      ],
    },
  ],
  stats: { argumentsWon: 0, argumentsLost: 0, teamFlips: 0 },
  certainty: 100,
  controllerId: "wander",
  movementCooldown: 0,
  conversationLog: [],
};

describe("profile goal scores", () => {
  it("omits TeamGoal scoring surfaces from the profile", () => {
    const markup = renderCogProfilePage(cog, { cogs: [cog], recentEvents: [], tick: 0 } as never, {
      name: "Ada Draft",
      behaviorPrompt: "Keep the room calm.",
      attributes: { energy: 7 },
      defensiveTrait: "stubborn",
      activeTrait: "passionate",
      personalGoal: "majority",
    });

    expect(markup).toContain(">Achievements<");
    expect(markup).toMatch(/<span>Score<\/span>\s*<strong>5000<\/strong>\s*<span>personal pts<\/span>/);
    expect(markup).not.toContain("TeamGoals");
    expect(markup).not.toContain("TeamGoal");
    expect(markup).not.toContain("Majority");
    expect(markup).not.toContain("Underdog");
    expect(markup).not.toContain('class="profile-goals-block"');
    expect(markup).not.toContain('class="profile-goal-score-row');
    expect(markup).not.toContain('data-trait-kind="personalGoal"');
    expect(markup).not.toContain('data-trait-value="majority"');
  });

  it("renders active and completed achievements on the profile", () => {
    const markup = renderProfileAchievements(
      {
        ...cog,
        achievements: [
          {
            ...cog.achievements[0],
            timeoutTick: 410,
          },
        ],
      },
      { tick: 10 },
    );

    expect(markup).toContain("Current");
    expect(markup).toContain("Debate Three Opponents");
    expect(markup).toContain("in 3m 20s");
    expect(markup).toContain("Starts debate sessions with different opponents.");
    expect(markup).toContain("Completed");
    expect(markup).toContain("Win Round in Bar");
    expect(markup).toContain("+10");
    expect(markup).toContain("Wins a debate round in a Bar room.");
    expect(markup).toContain('data-achievement-assignment="active-debate-three"');
    expect(markup).toContain('data-achievement-assignment="completed-bar-debate"');
    expect(markup.match(/<details\s+class="profile-achievement-row/g)).toHaveLength(2);
    expect(markup.match(/<details\s+class="profile-achievement-row is-completed"/g)).toHaveLength(1);
    expect(markup).not.toContain('data-achievement="debateThreeCogs" open');
  });

  it("renders profile editing as a guidance-only surface above the diary", () => {
    const markup = renderCogProfilePage(cog, { cogs: [cog], recentEvents: [], tick: 0 } as never, {
      name: "Ada Draft",
      behaviorPrompt: "Keep the room calm.",
      attributes: { energy: 7 },
      defensiveTrait: "stubborn",
      activeTrait: "passionate",
      personalGoal: "majority",
    });

    expect(markup).toContain('data-profile-field="behaviorPrompt"');
    expect(markup).toContain(">Send Guidance<");
    expect(markup).toContain('aria-label="Send guidance"');
    expect(markup).toContain(">Guidance<");
    expect(markup).toContain('aria-label="Guidance"');
    expect(markup.indexOf('class="profile-block profile-editor-block"')).toBeLessThan(
      markup.indexOf('class="profile-block profile-diary-block"'),
    );
    expect(markup).not.toContain(">Main Strategy<");
    expect(markup).not.toContain('aria-label="Main strategy prompt"');
    expect(markup).not.toContain(">Edit Strategy<");
    expect(markup).not.toContain('data-profile-field="name"');
    expect(markup).not.toContain('class="trait-editor"');
    expect(markup).not.toContain('class="attribute-editor"');
    expect(markup).not.toContain("Save profile");
  });

  it("renders an abandon button at the bottom of the profile page", () => {
    const markup = renderCogProfilePage(cog, { cogs: [cog], recentEvents: [], tick: 0 } as never, {
      name: "Ada Draft",
      behaviorPrompt: "Keep the room calm.",
      attributes: { energy: 7 },
      defensiveTrait: "stubborn",
      activeTrait: "passionate",
      personalGoal: "majority",
    });
    const gridIndex = markup.indexOf('class="profile-page-grid"');
    const abandonIndex = markup.indexOf('data-action="abandon-cog"');

    expect(abandonIndex).toBeGreaterThan(gridIndex);
    expect(markup).toContain('class="profile-abandon-button"');
    expect(markup).toContain('data-cog-id="cog-ada"');
    expect(markup).toContain(">Abandon<");
  });

  it("renders Send below profile guidance without Poke controls", () => {
    const markup = renderCogProfilePage(cog, { cogs: [cog], recentEvents: [], tick: 0 } as never, {
      name: "Ada Draft",
      behaviorPrompt: "Keep the room calm.",
      attributes: { energy: 7 },
      defensiveTrait: "stubborn",
      activeTrait: "passionate",
      personalGoal: "majority",
    });
    const editorSection = profileEditorSection(markup);
    const mobileActionRow = profileMobilePromptActionRow(markup);
    const textareaIndex = editorSection.indexOf('name="behaviorPrompt"');
    const sendIndex = editorSection.indexOf('class="profile-form-actions"');

    expect(markup).not.toContain('data-action="poke-cog"');
    expect(markup).not.toContain("profile-poke-button");
    expect(markup).not.toContain(">Poke<");
    expect(profileHeroSection(markup)).not.toContain('data-action="poke-cog"');
    expect(editorSection).toContain(">Send Guidance<");
    expect(editorSection).toContain('data-action="save-profile"');
    expect(editorSection).toContain('class="profile-form-actions"');
    expect(editorSection).toContain('class="profile-send-button"');
    expect(editorSection).toContain(">Send</button>");
    expect(textareaIndex).toBeGreaterThan(-1);
    expect(sendIndex).toBeGreaterThan(textareaIndex);
    expect(mobileActionRow).toContain(">Send</button>");
    expect(mobileActionRow).not.toContain(">Send Guidance<");
  });

  it("omits close controls from the profile page", () => {
    const markup = renderCogProfilePage(cog, { cogs: [cog], recentEvents: [], tick: 0 } as never, {
      name: "Ada Draft",
      behaviorPrompt: "Keep the room calm.",
      attributes: { energy: 7 },
      defensiveTrait: "stubborn",
      activeTrait: "passionate",
      personalGoal: "majority",
    });

    expect(markup).not.toContain('data-action="close-profile-page"');
    expect(markup).not.toContain('class="profile-close-button"');
    expect(markup).not.toContain('class="profile-mobile-close-button"');
  });

  it("omits the profile About panel entirely", () => {
    const markup = renderCogProfilePage(cog, { cogs: [cog], recentEvents: [], tick: 0 } as never, {
      name: "Ada Draft",
      behaviorPrompt: "Keep the room calm.",
      attributes: { energy: 7 },
      defensiveTrait: "stubborn",
      activeTrait: "passionate",
      personalGoal: "majority",
    });

    expect(markup).not.toContain('class="profile-block profile-about-block"');
    expect(markup).not.toContain('aria-label="Profile details"');
    expect(markup).not.toContain("<span>About</span>");
    expect(markup).not.toContain('class="profile-about-grid"');
    expect(markup).not.toContain('class="profile-about-item"');
  });

  it("omits the profile Score panel entirely", () => {
    const markup = renderCogProfilePage(cog, { cogs: [cog], recentEvents: [], tick: 0 } as never, {
      name: "Ada Draft",
      behaviorPrompt: "Keep the room calm.",
      attributes: { energy: 7 },
      defensiveTrait: "stubborn",
      activeTrait: "passionate",
      personalGoal: "majority",
    });

    expect(markup).toContain('class="profile-stat-band"');
    expect(markup).not.toContain('class="profile-block profile-score-block"');
    expect(markup).not.toContain('aria-label="Certainty and score"');
    expect(markup).not.toContain('class="profile-doubt-panel"');
    expect(markup).not.toContain("No personal score moments yet.");
  });

  it("renders the profile hero with location and trait pills", () => {
    const locatedCog: Cog = {
      ...cog,
      activeTrait: "passionate",
      defensiveTrait: "zealot",
      location: { roomId: "stage", spotId: "stage_host" },
    };
    const markup = renderCogProfilePage(
      locatedCog,
      {
        cogs: [locatedCog],
        recentEvents: [],
        tick: 0,
        venue: {
          rooms: [{ id: "stage", label: "Main Stage", kind: "stage", neighborIds: [], spotIds: ["stage_host"] }],
          spots: [{ id: "stage_host", roomId: "stage", label: "stage_host", position: { x: 2, y: 3 } }],
          spotLinks: [],
          roomPaths: [],
        },
      } as never,
      {
        name: "Ada Draft",
        behaviorPrompt: "Keep the room calm.",
        attributes: { energy: 7 },
        defensiveTrait: "zealot",
        activeTrait: "passionate",
        personalGoal: "majority",
      },
    );
    const heroSection = profileHeroSection(markup);

    expect(heroSection).toContain('class="profile-location-pill"');
    expect(heroSection).toContain("Main Stage / Stage Host");
    expect(heroSection).toContain('class="profile-subtitle-traits"');
    expect(heroSection).toContain('data-trait-value="zealot"');
    expect(heroSection).toContain('data-trait-value="passionate"');
    expect(heroSection).not.toContain('data-trait-kind="personalGoal"');
    expect(heroSection).not.toContain('data-trait-value="majority"');
    expect(heroSection).not.toContain("controller");
  });

  it("renders fractional score values as integers", () => {
    const fractionalScoreCog: Cog = {
      ...cog,
      completedAchievements: [
        {
          ...cog.completedAchievements[0],
          points: 0.49,
        },
      ],
      goalScores: [
        {
          goal: "majority",
          points: 2.51,
          history: [
            { tick: 0, points: 0 },
            { tick: 1, points: 2.51 },
          ],
        },
      ],
    };

    const achievementsMarkup = renderProfileAchievements(fractionalScoreCog);

    expect(achievementsMarkup).toContain("+0");
    expect(achievementsMarkup).not.toContain("+0.49");
  });
});

function profileHeroSection(markup: string): string {
  const match = markup.match(/<header class="profile-hero"[\s\S]*?<\/header>/);
  expect(match).toBeTruthy();
  return match?.[0] ?? "";
}

function profileEditorSection(markup: string): string {
  const match = markup.match(/<section class="profile-block profile-editor-block"[\s\S]*?<\/section>/);
  expect(match).toBeTruthy();
  return match?.[0] ?? "";
}

function profileMobilePromptActionRow(markup: string): string {
  const match = markup.match(/<div class="profile-mobile-prompt-action-row"[\s\S]*?<\/div>/);
  expect(match).toBeTruthy();
  return match?.[0] ?? "";
}
