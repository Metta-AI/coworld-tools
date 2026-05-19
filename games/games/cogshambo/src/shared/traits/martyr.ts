import { formatNumber } from "./format.js";
import { traitSettings } from "./helpers.js";
import type { TraitDefinition } from "./types.js";

const defaultConfig = {
  teammateRecovery: 12,
};

export const martyr: TraitDefinition = {
  kind: "defensive",
  id: "martyr",
  label: "Martyr",
  description: "Their conversion hardens nearby former teammates.",
  userDescription: "Flipping restores nearby former teammates.",
  promptDescription: "When you flip, same-room former teammates regain certainty.",
  modifiers: ["Same-room cogs of the martyr's previous color regain certainty when the martyr converts."],
  parameters: [
    {
      key: "teammateRecovery",
      label: "Former teammate recovery",
      description: "Certainty restored to same-room former teammates when this cog converts.",
      min: 0,
      max: 100,
      step: 1,
    },
  ],
  defaultConfig,
  describe: ({ config }) =>
    `When you flip, same-room former teammates recover ${formatNumber(
      traitSettings<typeof defaultConfig>(config, "martyr").teammateRecovery,
    )} certainty.`,
  code: {
    ownConversion: ({ sameRoomCogs, previousColor, config }) => ({
      recoveries: sameRoomCogs
        .filter((teammate) => teammate.color === previousColor)
        .map((teammate) => ({
          cogId: teammate.id,
          color: previousColor,
          amount: traitSettings<typeof defaultConfig>(config, "martyr").teammateRecovery,
        })),
    }),
  },
  integrationTest: "tests/server/traits/martyr.test.ts",
};
