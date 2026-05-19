import { formatNumber } from "./format.js";
import { traitSettings } from "./helpers.js";
import type { TraitDefinition } from "./types.js";

const defaultConfig = {
  drawDoubt: 6,
};

export const doubter: TraitDefinition = {
  kind: "defensive",
  id: "doubter",
  label: "Doubter",
  description: "Drawn debates make them less sure.",
  userDescription: "Draws cost certainty.",
  promptDescription: "Drawing a debate round lowers your certainty.",
  modifiers: ["Drawn debate rounds apply the draw certainty loss."],
  parameters: [
    {
      key: "drawDoubt",
      label: "Draw certainty loss",
      description: "Certainty lost by this cog after a drawn debate round.",
      min: 0,
      max: 50,
      step: 1,
    },
  ],
  defaultConfig,
  describe: ({ config }) => `Drawn debate rounds cost ${formatNumber(traitSettings<typeof defaultConfig>(config, "doubter").drawDoubt)} certainty.`,
  code: {
    drawCertaintyLoss: ({ config }) => traitSettings<typeof defaultConfig>(config, "doubter").drawDoubt,
  },
  integrationTest: "tests/server/traits/doubter.test.ts",
};
