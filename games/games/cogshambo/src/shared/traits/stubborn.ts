import { multiplierChange } from "./format.js";
import { traitSettings } from "./helpers.js";
import type { TraitDefinition } from "./types.js";

const defaultConfig = {
  directDoubtMultiplier: 0.75,
};

export const stubborn: TraitDefinition = {
  kind: "defensive",
  id: "stubborn",
  label: "Stubborn",
  description: "Hard to move in a direct argument.",
  userDescription: "Direct debate losses hurt less.",
  promptDescription: "Direct debate losses cost less certainty.",
  modifiers: ["Direct debate certainty loss uses the direct loss multiplier."],
  parameters: [
    {
      key: "directDoubtMultiplier",
      label: "Direct loss multiplier",
      description: "Multiplier applied to direct debate certainty loss this cog receives.",
      min: 0,
      max: 2,
      step: 0.05,
    },
  ],
  defaultConfig,
  describe: ({ config, audience }) =>
    audience === "user"
      ? `Direct debate losses hurt ${multiplierChange(traitSettings<typeof defaultConfig>(config, "stubborn").directDoubtMultiplier)}.`
      : `Direct debate losses cost ${multiplierChange(traitSettings<typeof defaultConfig>(config, "stubborn").directDoubtMultiplier)} certainty.`,
  code: {
    directTargetMultiplier: ({ config }) => traitSettings<typeof defaultConfig>(config, "stubborn").directDoubtMultiplier,
  },
  integrationTest: "tests/server/traits/stubborn.test.ts",
};
