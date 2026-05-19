import { hitChange } from "./format.js";
import { traitSettings } from "./helpers.js";
import type { TraitDefinition } from "./types.js";

const defaultConfig = {
  minorityWitnessMultiplier: 2,
};

export const insurgent: TraitDefinition = {
  kind: "active",
  id: "insurgent",
  label: "Insurgent",
  description: "Minority wins shake the room.",
  userDescription: "Minority wins hit witnesses harder.",
  promptDescription: "When your team is smallest, your wins cost witnesses more certainty.",
  modifiers: ["Witness certainty loss from wins uses the minority witness multiplier while the winner color is uniquely smallest."],
  parameters: [
    {
      key: "minorityWitnessMultiplier",
      label: "Minority witness multiplier",
      description: "Multiplier applied to witness certainty loss when an insurgent wins from the unique smallest team.",
      min: 0,
      max: 4,
      step: 0.05,
    },
  ],
  defaultConfig,
  describe: ({ config }) =>
    `Minority-team wins make witnesses shift ${hitChange(
      traitSettings<typeof defaultConfig>(config, "insurgent").minorityWitnessMultiplier,
    )}.`,
  code: {
    witnessAmountMultiplier: ({ winner, uniquePopulationColor, config }) =>
      winner.color === uniquePopulationColor("lowest")
        ? traitSettings<typeof defaultConfig>(config, "insurgent").minorityWitnessMultiplier
        : undefined,
  },
  integrationTest: "tests/server/traits/insurgent.test.ts",
};
