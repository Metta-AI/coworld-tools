import { multiplierChange } from "./format.js";
import { traitSettings } from "./helpers.js";
import type { TraitDefinition } from "./types.js";

const defaultConfig = {
  dominantDoubtMultiplier: 0.75,
};

export const iconoclast: TraitDefinition = {
  kind: "defensive",
  id: "iconoclast",
  label: "Iconoclast",
  description: "Resists the dominant color.",
  userDescription: "Largest-team pressure hurts less.",
  promptDescription: "Largest-team pressure costs less certainty.",
  modifiers: ["Certainty loss from the unique largest color uses the dominant-color multiplier."],
  parameters: [
    {
      key: "dominantDoubtMultiplier",
      label: "Dominant-color multiplier",
      description: "Multiplier applied to certainty loss from the unique largest color.",
      min: 0,
      max: 2,
      step: 0.05,
    },
  ],
  defaultConfig,
  describe: ({ config, audience }) =>
    audience === "user"
      ? `Largest-team pressure hurts ${multiplierChange(traitSettings<typeof defaultConfig>(config, "iconoclast").dominantDoubtMultiplier)}.`
      : `Largest-team pressure costs ${multiplierChange(
          traitSettings<typeof defaultConfig>(config, "iconoclast").dominantDoubtMultiplier,
        )} certainty.`,
  code: {
    pressureTargetMultiplier: ({ pressureColor, uniquePopulationColor, config }) =>
      pressureColor === uniquePopulationColor("highest")
        ? traitSettings<typeof defaultConfig>(config, "iconoclast").dominantDoubtMultiplier
        : undefined,
  },
  integrationTest: "tests/server/traits/iconoclast.test.ts",
};
