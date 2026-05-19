import { hitChange } from "./format.js";
import { traitSettings } from "./helpers.js";
import type { TraitDefinition } from "./types.js";

const defaultConfig = {
  nextWinDoubtMultiplier: 1.5,
};

export const avenger: TraitDefinition = {
  kind: "active",
  id: "avenger",
  label: "Avenger",
  description: "Retaliates after same-room teammates flip.",
  userDescription: "Next win hits harder after a nearby teammate flips.",
  promptDescription: "When a same-room teammate flips, your next win against the converting team hits harder.",
  modifiers: ["A same-room teammate conversion arms a one-win avenger multiplier against the converter's color."],
  parameters: [
    {
      key: "nextWinDoubtMultiplier",
      label: "Avenger win multiplier",
      description: "Multiplier applied to the avenger's next direct win against the team that converted a teammate.",
      min: 0,
      max: 4,
      step: 0.05,
    },
  ],
  defaultConfig,
  describe: ({ config }) =>
    `After a nearby teammate flips, your next matching win hits ${hitChange(
      traitSettings<typeof defaultConfig>(config, "avenger").nextWinDoubtMultiplier,
    )}.`,
  code: {
    teammateConverted: ({ teammate, previousColor, winningColor }) =>
      teammate.color === previousColor ? { avengerTargets: [{ cogId: teammate.id, color: winningColor }] } : undefined,
    directSourceMultiplier: ({ avengerTargetColor, target, config }) =>
      avengerTargetColor === target.color ? traitSettings<typeof defaultConfig>(config, "avenger").nextWinDoubtMultiplier : undefined,
  },
  integrationTest: "tests/server/traits/avenger.test.ts",
};
