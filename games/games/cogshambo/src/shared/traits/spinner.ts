import { tacticAffinityCode, tacticAffinityDescription, tacticAffinityParameters, traitSettings } from "./helpers.js";
import type { TraitDefinition } from "./types.js";

const defaultConfig = {
  winDoubtMultiplier: 1.25,
  receivedDoubtMultiplier: 1.25,
};

export const spinner: TraitDefinition = {
  kind: "active",
  id: "spinner",
  label: "Spinner",
  description: "Specializes in spin.",
  userDescription: "Spin wins hit harder, but spin losses hurt more.",
  promptDescription: "Spin wins cost opponents more certainty; spin losses cost you more certainty.",
  modifiers: ["Winning with spin uses the spin win multiplier.", "Receiving spin uses the spin vulnerability multiplier."],
  parameters: tacticAffinityParameters("spin"),
  defaultConfig,
  describe: ({ config, audience }) => tacticAffinityDescription("Spin", traitSettings<typeof defaultConfig>(config, "spinner"), audience),
  code: tacticAffinityCode("spinner", "spin"),
  integrationTest: "tests/server/traits/spinner.test.ts",
};
