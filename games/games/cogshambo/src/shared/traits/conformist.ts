import { multiplierChange } from "./format.js";
import { traitSettings } from "./helpers.js";
import type { TraitDefinition } from "./types.js";

const defaultConfig = {
  fringeDoubtMultiplier: 0.75,
};

export const conformist: TraitDefinition = {
  kind: "defensive",
  id: "conformist",
  label: "Conformist",
  description: "Resists fringe colors.",
  userDescription: "Smallest-team pressure hurts less.",
  promptDescription: "Smallest-team pressure costs less certainty.",
  modifiers: ["Certainty loss from the unique smallest color uses the fringe-color multiplier."],
  parameters: [
    {
      key: "fringeDoubtMultiplier",
      label: "Fringe-color multiplier",
      description: "Multiplier applied to certainty loss from the unique smallest color.",
      min: 0,
      max: 2,
      step: 0.05,
    },
  ],
  defaultConfig,
  describe: ({ config, audience }) =>
    audience === "user"
      ? `Smallest-team pressure hurts ${multiplierChange(traitSettings<typeof defaultConfig>(config, "conformist").fringeDoubtMultiplier)}.`
      : `Smallest-team pressure costs ${multiplierChange(
          traitSettings<typeof defaultConfig>(config, "conformist").fringeDoubtMultiplier,
        )} certainty.`,
  code: {
    pressureTargetMultiplier: ({ pressureColor, uniquePopulationColor, config }) =>
      pressureColor === uniquePopulationColor("lowest")
        ? traitSettings<typeof defaultConfig>(config, "conformist").fringeDoubtMultiplier
        : undefined,
  },
  integrationTest: "tests/server/traits/conformist.test.ts",
};
