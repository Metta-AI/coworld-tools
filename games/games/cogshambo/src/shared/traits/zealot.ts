import { formatNumber } from "./format.js";
import { traitSettings } from "./helpers.js";
import type { TraitDefinition } from "./types.js";

const defaultConfig = {
  minCertainty: 1,
};

export const zealot: TraitDefinition = {
  kind: "defensive",
  id: "zealot",
  label: "Zealot",
  description: "Never flips teams.",
  userDescription: "Cannot convert.",
  promptDescription: "Your certainty can fall, but you never change teams.",
  modifiers: ["Zealots clamp at the minimum certainty instead of converting."],
  parameters: [
    {
      key: "minCertainty",
      label: "Minimum certainty",
      description: "Lowest certainty a zealot can reach without converting.",
      min: 0,
      max: 100,
      step: 1,
    },
  ],
  defaultConfig,
  describe: ({ config }) =>
    `Cannot convert; certainty bottoms out at ${formatNumber(traitSettings<typeof defaultConfig>(config, "zealot").minCertainty)}.`,
  code: {
    blocksConversion: ({ config }) => traitSettings<typeof defaultConfig>(config, "zealot").minCertainty,
  },
  integrationTest: "tests/server/traits/zealot.test.ts",
};
