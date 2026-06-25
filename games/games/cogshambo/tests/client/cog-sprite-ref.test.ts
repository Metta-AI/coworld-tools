import { describe, expect, it } from "vitest";

import { spriteEntriesForCog, spriteKeyForCog, spriteUrlForCog } from "../../src/client/render/cog-sprite-ref";
import type { Cog } from "../../src/shared/types";

const baseCog: Cog = {
  id: "cog-test",
  name: "Test",
  behaviorPrompt: "",
  position: { x: 0, y: 0 },
  spriteSheetKey: "generated-test",
  spriteUrl: "/assets/cogshambo/cogs/generated-test.png",
  attributes: {},
  color: "red",
  defensiveTrait: "stubborn",
  activeTrait: "forceful",
  personalGoal: "underdog",
  personalScore: 0,
  certainty: 100,
  controllerId: "wander",
  movementCooldown: 0,
  conversationLog: [],
};

describe("cog sprite refs", () => {
  it("uses the neutral base sprite when color variant sprites exist", () => {
    const cog: Cog = {
      ...baseCog,
      color: "blue",
      spriteUrls: {
        red: "/assets/cogshambo/cogs/generated-test-red.png",
        blue: "/assets/cogshambo/cogs/generated-test-blue.png",
      },
    };

    expect(spriteKeyForCog(cog)).toBe("generated-test");
    expect(spriteUrlForCog(cog)).toBe("/assets/cogshambo/cogs/generated-test.png");
    expect(spriteEntriesForCog(cog)).toEqual([
      { key: "generated-test", spriteUrl: "/assets/cogshambo/cogs/generated-test.png" },
    ]);
  });

  it("falls back to the legacy single sprite URL", () => {
    expect(spriteKeyForCog(baseCog)).toBe("generated-test");
    expect(spriteUrlForCog(baseCog)).toBe("/assets/cogshambo/cogs/generated-test.png");
    expect(spriteEntriesForCog(baseCog)).toEqual([
      { key: "generated-test", spriteUrl: "/assets/cogshambo/cogs/generated-test.png" },
    ]);
  });
});
