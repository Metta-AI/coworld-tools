import { formatNumber } from "./format.js";
import { traitSettings } from "./helpers.js";
import type { TraitDefinition } from "./types.js";

const defaultConfig = {
  crowdedRoomThreshold: 3,
  crowdedRoomDoubt: 8,
};

export const heretic: TraitDefinition = {
  kind: "defensive",
  id: "heretic",
  label: "Heretic",
  description: "Cannot stand a crowded room.",
  userDescription: "Entering a crowded room costs certainty.",
  promptDescription: "Entering a room with too many total cogs lowers your certainty.",
  modifiers: ["Crowded room entry applies the crowded room certainty loss."],
  parameters: [
    {
      key: "crowdedRoomThreshold",
      label: "Crowded room threshold",
      description: "Total cogs in a room must be above this count to trigger certainty loss.",
      min: 0,
      max: 12,
      step: 1,
    },
    {
      key: "crowdedRoomDoubt",
      label: "Crowded room certainty loss",
      description: "Certainty lost after entering a room with more than the threshold count of cogs.",
      min: 0,
      max: 100,
      step: 1,
    },
  ],
  defaultConfig,
  describe: ({ config }) => {
    const settings = traitSettings<typeof defaultConfig>(config, "heretic");
    return `Entering a room with more than ${formatNumber(settings.crowdedRoomThreshold)} total cogs costs ${formatNumber(
      settings.crowdedRoomDoubt,
    )} certainty.`;
  },
  code: {
    roomEntryCertaintyLoss: ({ sameRoomCogs, config }) => {
      const settings = traitSettings<typeof defaultConfig>(config, "heretic");
      return sameRoomCogs.length > settings.crowdedRoomThreshold ? settings.crowdedRoomDoubt : undefined;
    },
  },
  integrationTest: "tests/server/traits/heretic.test.ts",
};
