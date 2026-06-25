import { multiplierChange } from "./format.js";
import { traitSettings } from "./helpers.js";
import type { TraitDefinition } from "./types.js";

const defaultConfig = {
  indirectDoubtMultiplier: 0.5,
};

export const insular: TraitDefinition = {
  kind: "defensive",
  id: "insular",
  label: "Insular",
  description: "Less affected by indirect social pressure.",
  userDescription: "Witness and indirect pressure hurts less.",
  promptDescription: "Witness and indirect pressure costs less certainty.",
  modifiers: ["Indirect and witness certainty loss uses the indirect loss multiplier."],
  parameters: [
    {
      key: "indirectDoubtMultiplier",
      label: "Indirect loss multiplier",
      description: "Multiplier applied to non-direct certainty loss this cog receives.",
      min: 0,
      max: 2,
      step: 0.05,
    },
  ],
  defaultConfig,
  describe: ({ config, audience }) =>
    audience === "user"
      ? `Witness and indirect pressure hurts ${multiplierChange(traitSettings<typeof defaultConfig>(config, "insular").indirectDoubtMultiplier)}.`
      : `Witness and indirect pressure costs ${multiplierChange(
          traitSettings<typeof defaultConfig>(config, "insular").indirectDoubtMultiplier,
        )} certainty.`,
  code: {
    indirectTargetMultiplier: ({ config }) => traitSettings<typeof defaultConfig>(config, "insular").indirectDoubtMultiplier,
  },
  integrationTest: "tests/server/traits/insular.test.ts",
};
