import { formatNumber, normalAmountSuffix } from "./format.js";
import { traitSettings } from "./helpers.js";
import type { TraitDefinition } from "./types.js";

const defaultConfig = {
  witnessDoubt: 4,
};

export const charismatic: TraitDefinition = {
  kind: "active",
  id: "charismatic",
  label: "Charismatic",
  description: "Moves the crowd when winning debates.",
  userDescription: "Wins move witnesses more.",
  promptDescription: "Witnesses shift more when you win.",
  modifiers: ["Same-room witness certainty loss uses the witness certainty loss amount."],
  parameters: [
    {
      key: "witnessDoubt",
      label: "Witness certainty loss",
      description: "Witness certainty loss applied when a charismatic cog wins a decisive debate round.",
      min: 0,
      max: 20,
      step: 1,
    },
  ],
  defaultConfig,
  describe: ({ config }) => {
    const amount = traitSettings<typeof defaultConfig>(config, "charismatic").witnessDoubt;
    return `Witnesses shift ${formatNumber(amount)} certainty when you win${normalAmountSuffix(amount, config.witnessDoubt)}.`;
  },
  code: {
    witnessBaseAmount: ({ config }) => traitSettings<typeof defaultConfig>(config, "charismatic").witnessDoubt,
  },
  integrationTest: "tests/server/traits/charismatic.test.ts",
};
