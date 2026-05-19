import { secondsToSimulationTicks } from "../timing.js";
import { formatNumber, formatPercent } from "./format.js";
import { traitSettings } from "./helpers.js";
import type { TraitDefinition } from "./types.js";

const defaultConfig = {
  majorityThreshold: 0.6,
  majorityDoubt: 10,
};
const TICKS_PER_MINUTE = secondsToSimulationTicks(60);

export const defector: TraitDefinition = {
  kind: "defensive",
  id: "defector",
  label: "Defector",
  description: "Gets restless when their team dominates.",
  userDescription: "Large-team consensus lowers certainty.",
  promptDescription: "When your team is too large, you lose certainty.",
  modifiers: ["Passive certainty loss applies while this cog's team share meets the majority threshold."],
  parameters: [
    {
      key: "majorityThreshold",
      label: "Majority threshold",
      description: "Team share at or above which this cog starts losing certainty.",
      min: 0.5,
      max: 1,
      step: 0.05,
    },
    {
      key: "majorityDoubt",
      label: "Majority certainty loss per minute",
      description: "Certainty lost per minute while this cog's team is too large.",
      min: 0,
      max: 50,
      step: 1,
    },
  ],
  defaultConfig,
  describe: ({ config }) => {
    const settings = traitSettings<typeof defaultConfig>(config, "defector");
    return `Lose ${formatNumber(settings.majorityDoubt)} certainty per minute while your team is at least ${formatPercent(
      settings.majorityThreshold * 100,
    )}% of all cogs.`;
  },
  code: {
    passiveCertaintyChange: ({ teamShare, config }) => {
      const settings = traitSettings<typeof defaultConfig>(config, "defector");
      return teamShare >= settings.majorityThreshold ? -settings.majorityDoubt / TICKS_PER_MINUTE : undefined;
    },
  },
  integrationTest: "tests/server/traits/defector.test.ts",
};
