import { cooldownChange, formatNumber, formatPercent } from "./format.js";
import { traitSettings } from "./helpers.js";
import type { TraitDefinition } from "./types.js";

const defaultConfig = {
  debateCooldownMultiplier: 0.5,
  majorityPressureDiscount: 0.5,
  overwhelmingTeamThreshold: 0.9,
  unanimousRoomDoubt: 7,
};

export const contrarian: TraitDefinition = {
  kind: "active",
  id: "contrarian",
  label: "Contrarian",
  description: "Rejects overwhelming consensus.",
  userDescription: "Majority pressure matters less; overwhelming team dominance makes you flip.",
  promptDescription: "Majority-color pressure is discounted, repeat debates unlock sooner, overwhelming team dominance flips you, and unanimous rooms lower certainty.",
  modifiers: [
    "Repeat-pair debate cooldown uses the pair cooldown multiplier when either debater is contrarian.",
    "Majority-color certainty loss is discounted by current team share.",
    "Flips teams when this cog's team share is above the overwhelming team threshold.",
    "Unanimous same-color room entry applies the unanimous room certainty loss.",
  ],
  parameters: [
    {
      key: "debateCooldownMultiplier",
      label: "Pair cooldown multiplier",
      description: "Multiplier applied to the post-debate pair cooldown.",
      min: 0,
      max: 2,
      step: 0.05,
    },
    {
      key: "majorityPressureDiscount",
      label: "Majority pressure discount",
      description: "How strongly majority-color pressure is discounted when this cog receives certainty loss.",
      min: 0,
      max: 1,
      step: 0.05,
    },
    {
      key: "overwhelmingTeamThreshold",
      label: "Overwhelming team threshold",
      description: "Team share above which this cog flips to the other team.",
      min: 0.5,
      max: 1,
      step: 0.05,
    },
    {
      key: "unanimousRoomDoubt",
      label: "Unanimous room certainty loss",
      description: "Certainty lost after entering a room where every cog shares this cog's color.",
      min: 0,
      max: 100,
      step: 1,
    },
  ],
  defaultConfig,
  describe: ({ config }) => {
    const settings = traitSettings<typeof defaultConfig>(config, "contrarian");
    return `Repeat debates unlock ${cooldownChange(settings.debateCooldownMultiplier)}; majority pressure is discounted by up to ${formatPercent(
      settings.majorityPressureDiscount * 100,
    )}%; flips above ${formatPercent(settings.overwhelmingTeamThreshold * 100)}% team share; all-same-team rooms cost ${formatNumber(
      settings.unanimousRoomDoubt,
    )} certainty.`;
  },
  code: {
    debateCooldownMultiplier: ({ config }) => traitSettings<typeof defaultConfig>(config, "contrarian").debateCooldownMultiplier,
    passiveColorFlip: ({ teamShare, config }) =>
      teamShare > traitSettings<typeof defaultConfig>(config, "contrarian").overwhelmingTeamThreshold,
    pressureTargetMultiplier: ({ pressureTeamShare, config }) => {
      if (pressureTeamShare <= 0.5) {
        return undefined;
      }

      const normalizedMajority = (pressureTeamShare - 0.5) / 0.5;
      const discount = normalizedMajority * traitSettings<typeof defaultConfig>(config, "contrarian").majorityPressureDiscount;
      return Math.max(0, 1 - discount);
    },
    roomEntryCertaintyLoss: ({ cog, sameRoomCogs, config }) =>
      sameRoomCogs.some((candidate) => candidate.id !== cog.id) && sameRoomCogs.every((candidate) => candidate.color === cog.color)
        ? traitSettings<typeof defaultConfig>(config, "contrarian").unanimousRoomDoubt
        : undefined,
  },
  integrationTest: "tests/server/traits/contrarian.test.ts",
};
