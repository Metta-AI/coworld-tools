import { secondsToSimulationTicks } from "../timing.js";
import { formatNumber, formatPercent } from "./format.js";
import { traitSettings } from "./helpers.js";
import type { TraitDefinition } from "./types.js";

const defaultConfig = {
  majorityThreshold: 0.6,
  majorityRecovery: 10,
};
const TICKS_PER_MINUTE = secondsToSimulationTicks(60);

export const bandwagoner: TraitDefinition = {
  kind: "defensive",
  id: "bandwagoner",
  label: "Bandwagoner",
  description: "Gains confidence when their team dominates.",
  userDescription: "Large-team consensus restores certainty.",
  promptDescription: "When your team is large enough, you recover certainty.",
  modifiers: ["Passive certainty recovery applies while this cog's team share is above the majority threshold."],
  parameters: [
    {
      key: "majorityThreshold",
      label: "Majority threshold",
      description: "Team share above which this cog starts recovering certainty.",
      min: 0.5,
      max: 1,
      step: 0.05,
    },
    {
      key: "majorityRecovery",
      label: "Majority certainty gain per minute",
      description: "Certainty restored per minute while this cog's team is large enough.",
      min: 0,
      max: 50,
      step: 1,
    },
  ],
  defaultConfig,
  describe: ({ config }) => {
    const settings = traitSettings<typeof defaultConfig>(config, "bandwagoner");
    return `Recover ${formatNumber(settings.majorityRecovery)} certainty per minute while your team is more than ${formatPercent(
      settings.majorityThreshold * 100,
    )}% of all cogs.`;
  },
  code: {
    passiveCertaintyChange: ({ teamShare, config }) => {
      const settings = traitSettings<typeof defaultConfig>(config, "bandwagoner");
      return teamShare > settings.majorityThreshold ? settings.majorityRecovery / TICKS_PER_MINUTE : undefined;
    },
  },
  integrationTest: "tests/server/traits/bandwagoner.test.ts",
};
