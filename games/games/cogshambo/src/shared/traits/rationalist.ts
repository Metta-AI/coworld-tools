import { tacticAffinityCode, tacticAffinityDescription, tacticAffinityParameters, traitSettings } from "./helpers.js";
import type { TraitDefinition } from "./types.js";

const defaultConfig = {
  winDoubtMultiplier: 1.25,
  receivedDoubtMultiplier: 1.25,
};

export const rationalist: TraitDefinition = {
  kind: "active",
  id: "rationalist",
  label: "Rationalist",
  description: "Specializes in reason.",
  userDescription: "Reason wins hit harder, but reason losses hurt more.",
  promptDescription: "Reason wins cost opponents more certainty; reason losses cost you more certainty.",
  modifiers: ["Winning with reason uses the reason win multiplier.", "Receiving reason uses the reason vulnerability multiplier."],
  parameters: tacticAffinityParameters("reason"),
  defaultConfig,
  describe: ({ config, audience }) => tacticAffinityDescription("Reason", traitSettings<typeof defaultConfig>(config, "rationalist"), audience),
  code: tacticAffinityCode("rationalist", "reason"),
  integrationTest: "tests/server/traits/rationalist.test.ts",
};
