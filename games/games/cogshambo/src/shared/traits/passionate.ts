import { tacticAffinityCode, tacticAffinityDescription, tacticAffinityParameters, traitSettings } from "./helpers.js";
import type { TraitDefinition } from "./types.js";

const defaultConfig = {
  winDoubtMultiplier: 1.25,
  receivedDoubtMultiplier: 1.25,
};

export const passionate: TraitDefinition = {
  kind: "active",
  id: "passionate",
  label: "Passionate",
  description: "Specializes in passion.",
  userDescription: "Passion wins hit harder, but passion losses hurt more.",
  promptDescription: "Passion wins cost opponents more certainty; passion losses cost you more certainty.",
  modifiers: [
    "Winning with passion uses the passion win multiplier.",
    "Receiving passion uses the passion vulnerability multiplier.",
  ],
  parameters: tacticAffinityParameters("passion"),
  defaultConfig,
  describe: ({ config, audience }) =>
    tacticAffinityDescription("Passion", traitSettings<typeof defaultConfig>(config, "passionate"), audience),
  code: tacticAffinityCode("passionate", "passion"),
  integrationTest: "tests/server/traits/passionate.test.ts",
};
