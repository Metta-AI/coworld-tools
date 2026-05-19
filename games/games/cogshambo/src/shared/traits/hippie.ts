import { hitChange, multiplierChange } from "./format.js";
import { traitSettings } from "./helpers.js";
import type { TraitDefinition } from "./types.js";

const defaultConfig = {
  reasonWinDoubtMultiplier: 0.75,
  reasonReceivedDoubtMultiplier: 1.25,
  passionWinDoubtMultiplier: 1.25,
  passionReceivedDoubtMultiplier: 0.75,
};

export const hippie: TraitDefinition = {
  kind: "active",
  id: "hippie",
  label: "Hippie",
  description: "Reason lands softly but hurts to receive; passion does the opposite.",
  userDescription: "Reason wins hit softer and reason losses hurt more; passion wins hit harder and passion losses hurt less.",
  promptDescription:
    "Reason wins cost opponents less certainty and reason losses cost you more certainty; passion wins cost opponents more certainty and passion losses cost you less certainty.",
  modifiers: [
    "Winning with reason uses the reason win multiplier.",
    "Receiving direct certainty loss from reason uses the reason vulnerability multiplier.",
    "Winning with passion uses the passion win multiplier.",
    "Receiving direct certainty loss from passion uses the passion vulnerability multiplier.",
  ],
  parameters: [
    {
      key: "reasonWinDoubtMultiplier",
      label: "Reason win multiplier",
      description: "Multiplier applied when this cog wins a debate round with reason.",
      min: 0,
      max: 3,
      step: 0.05,
    },
    {
      key: "reasonReceivedDoubtMultiplier",
      label: "Reason vulnerability",
      description: "Multiplier applied when this cog receives direct certainty loss from reason.",
      min: 0,
      max: 3,
      step: 0.05,
    },
    {
      key: "passionWinDoubtMultiplier",
      label: "Passion win multiplier",
      description: "Multiplier applied when this cog wins a debate round with passion.",
      min: 0,
      max: 3,
      step: 0.05,
    },
    {
      key: "passionReceivedDoubtMultiplier",
      label: "Passion vulnerability",
      description: "Multiplier applied when this cog receives direct certainty loss from passion.",
      min: 0,
      max: 3,
      step: 0.05,
    },
  ],
  defaultConfig,
  describe: ({ config, audience }) => {
    const settings = traitSettings<typeof defaultConfig>(config, "hippie");
    if (audience === "user") {
      return `Reason wins hit ${hitChange(settings.reasonWinDoubtMultiplier)} and reason losses hurt ${multiplierChange(settings.reasonReceivedDoubtMultiplier)}; passion wins hit ${hitChange(settings.passionWinDoubtMultiplier)} and passion losses hurt ${multiplierChange(settings.passionReceivedDoubtMultiplier)}.`;
    }

    return `Reason wins cost opponents ${multiplierChange(settings.reasonWinDoubtMultiplier)} certainty and reason losses cost you ${multiplierChange(settings.reasonReceivedDoubtMultiplier)} certainty; passion wins cost opponents ${multiplierChange(settings.passionWinDoubtMultiplier)} certainty and passion losses cost you ${multiplierChange(settings.passionReceivedDoubtMultiplier)} certainty.`;
  },
  code: {
    directSourceMultiplier: ({ tactic, config }) => {
      const settings = traitSettings<typeof defaultConfig>(config, "hippie");
      if (tactic === "reason") {
        return settings.reasonWinDoubtMultiplier;
      }
      if (tactic === "passion") {
        return settings.passionWinDoubtMultiplier;
      }
      return undefined;
    },
    directTargetMultiplier: ({ tactic, config }) => {
      const settings = traitSettings<typeof defaultConfig>(config, "hippie");
      if (tactic === "reason") {
        return settings.reasonReceivedDoubtMultiplier;
      }
      if (tactic === "passion") {
        return settings.passionReceivedDoubtMultiplier;
      }
      return undefined;
    },
  },
  integrationTest: "tests/server/traits/hippie.test.ts",
};
