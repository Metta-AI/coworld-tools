import { formatNumber } from "./format.js";
import { traitSettings } from "./helpers.js";
import type { TraitDefinition } from "./types.js";

const defaultConfig = {
  majorityWinDoubt: 6,
};

export const diplomat: TraitDefinition = {
  kind: "defensive",
  id: "diplomat",
  label: "Diplomat",
  description: "Distrusts dominant local streaks.",
  userDescription: "Majority wins nearby reduce certainty.",
  promptDescription: "Witnessing your majority team win lowers your certainty.",
  modifiers: ["Same-team witnesses lose certainty when the winner color is the unique global majority."],
  parameters: [
    {
      key: "majorityWinDoubt",
      label: "Majority win certainty loss",
      description: "Certainty lost by diplomats witnessing their majority color win.",
      min: 0,
      max: 50,
      step: 1,
    },
  ],
  defaultConfig,
  describe: ({ config }) =>
    `Witnessing your majority team win costs ${formatNumber(
      traitSettings<typeof defaultConfig>(config, "diplomat").majorityWinDoubt,
    )} certainty.`,
  code: {
    sameTeamWitnessEffect: ({ winner, uniquePopulationColor, config }) =>
      winner.color === uniquePopulationColor("highest")
        ? { type: "selfDoubt", amount: traitSettings<typeof defaultConfig>(config, "diplomat").majorityWinDoubt }
        : undefined,
  },
  integrationTest: "tests/server/traits/diplomat.test.ts",
};
