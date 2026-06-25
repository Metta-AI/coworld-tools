import { formatNumber } from "./format.js";
import { traitSettings } from "./helpers.js";
import type { TraitDefinition } from "./types.js";

const defaultConfig = {
  lowCertaintyThreshold: 50,
  sameTeamDoubt: 5,
};

export const polarizer: TraitDefinition = {
  kind: "active",
  id: "polarizer",
  label: "Polarizer",
  description: "Makes shaky allies doubt the winning style.",
  userDescription: "Wins can unsettle low-certainty allies.",
  promptDescription: "Your wins lower low-certainty same-team witnesses.",
  modifiers: ["Same-team witnesses at or below the low certainty threshold lose certainty instead of being reinforced."],
  parameters: [
    {
      key: "lowCertaintyThreshold",
      label: "Low certainty threshold",
      description: "Same-team witnesses at or below this certainty are affected by polarizer wins.",
      min: 0,
      max: 500,
      step: 1,
    },
    {
      key: "sameTeamDoubt",
      label: "Same-team certainty loss",
      description: "Certainty lost by low-certainty same-team witnesses after a polarizer wins.",
      min: 0,
      max: 100,
      step: 1,
    },
  ],
  defaultConfig,
  describe: ({ config }) => {
    const settings = traitSettings<typeof defaultConfig>(config, "polarizer");
    return `Same-team witnesses at ${formatNumber(settings.lowCertaintyThreshold)} certainty or below lose ${formatNumber(
      settings.sameTeamDoubt,
    )} certainty when you win.`;
  },
  code: {
    sameTeamWitnessEffect: ({ witness, config }) => {
      const settings = traitSettings<typeof defaultConfig>(config, "polarizer");
      return witness.certainty <= settings.lowCertaintyThreshold ? { type: "selfDoubt", amount: settings.sameTeamDoubt } : undefined;
    },
  },
  integrationTest: "tests/server/traits/polarizer.test.ts",
};
