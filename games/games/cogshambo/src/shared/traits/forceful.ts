import { hitChange, multiplierChange } from "./format.js";
import { traitSettings } from "./helpers.js";
import type { TraitDefinition } from "./types.js";

const defaultConfig = {
  winDoubtMultiplier: 1.25,
};

export const forceful: TraitDefinition = {
  kind: "active",
  id: "forceful",
  label: "Forceful",
  description: "Wins hit harder.",
  userDescription: "Debate wins hit harder.",
  promptDescription: "Debate wins cost opponents more certainty.",
  modifiers: ["Direct certainty loss from decisive debate wins uses the win loss multiplier."],
  parameters: [
    {
      key: "winDoubtMultiplier",
      label: "Win loss multiplier",
      description: "Multiplier applied to direct certainty loss this cog creates after winning a debate round.",
      min: 0,
      max: 3,
      step: 0.05,
    },
  ],
  defaultConfig,
  describe: ({ config, audience }) =>
    audience === "user"
      ? `Debate wins hit ${hitChange(traitSettings<typeof defaultConfig>(config, "forceful").winDoubtMultiplier)}.`
      : `Debate wins cost opponents ${multiplierChange(traitSettings<typeof defaultConfig>(config, "forceful").winDoubtMultiplier)} certainty.`,
  code: {
    directSourceMultiplier: ({ config }) => traitSettings<typeof defaultConfig>(config, "forceful").winDoubtMultiplier,
  },
  integrationTest: "tests/server/traits/forceful.test.ts",
};
