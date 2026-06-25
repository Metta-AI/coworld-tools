import { describe, expect, it } from "vitest";

import { createSeedWorld } from "../../src/server/simulation/seed-world.js";
import { GridWorld } from "../../src/server/simulation/world.js";

describe("chaotic trait seeding and locks", () => {
  it("seeds exactly one zealot on each team", () => {
    const zealots = createSeedWorld().snapshot().cogs.filter((cog) => cog.defensiveTrait === "zealot");

    expect(zealots.map((cog) => cog.color).sort()).toEqual(["blue", "red"]);
  });

  it("keeps zealot assignment locked to seeded cogs", () => {
    const world = new GridWorld({ width: 8, height: 4 });
    const ordinary = world.addCog({ name: "Ordinary", color: "red", position: { x: 1, y: 1 } });
    const zealot = world.addCog({ name: "Zealot", color: "blue", defensiveTrait: "zealot", position: { x: 2, y: 1 } });

    expect(() =>
      world.updateCogProfile(ordinary.id, {
        name: ordinary.name,
        behaviorPrompt: ordinary.behaviorPrompt,
        attributes: ordinary.attributes,
        defensiveTrait: "zealot",
        activeTrait: ordinary.activeTrait,
        personalGoal: ordinary.personalGoal,
      }),
    ).toThrow(/seed-only/);

    expect(() =>
      world.updateCogProfile(zealot.id, {
        name: zealot.name,
        behaviorPrompt: zealot.behaviorPrompt,
        attributes: zealot.attributes,
        defensiveTrait: "stubborn",
        activeTrait: zealot.activeTrait,
        personalGoal: zealot.personalGoal,
      }),
    ).toThrow(/seed-only/);
  });
});
