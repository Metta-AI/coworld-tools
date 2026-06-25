import type { DebateTactic, Trait } from "../types.js";
import { hitChange, multiplierChange, type RuleDescriptionAudience } from "./format.js";
import type { TraitCode, TraitParameter, TraitRuntimeConfig } from "./types.js";

export function traitSettings<T extends Record<string, number>>(config: TraitRuntimeConfig, traitId: string): T {
  return config.traitConfig[traitId] as T;
}

export function tacticAffinityParameters(tactic: string): TraitParameter[] {
  return [
    {
      key: "winDoubtMultiplier",
      label: `${tactic[0]?.toUpperCase() ?? ""}${tactic.slice(1)} win multiplier`,
      description: `Multiplier applied when this cog wins a debate round with ${tactic}.`,
      min: 0,
      max: 3,
      step: 0.05,
    },
    {
      key: "receivedDoubtMultiplier",
      label: `${tactic[0]?.toUpperCase() ?? ""}${tactic.slice(1)} vulnerability`,
      description: `Multiplier applied when this cog receives direct certainty loss from ${tactic}.`,
      min: 0,
      max: 3,
      step: 0.05,
    },
  ];
}

export function tacticAffinityDescription(
  tactic: string,
  values: { winDoubtMultiplier: number; receivedDoubtMultiplier: number },
  audience: RuleDescriptionAudience,
): string {
  const lowerTactic = tactic.toLowerCase();
  if (audience === "user") {
    return `${tactic} wins hit ${hitChange(values.winDoubtMultiplier)}; ${lowerTactic} losses hurt ${multiplierChange(
      values.receivedDoubtMultiplier,
    )}.`;
  }

  return `${tactic} wins cost opponents ${multiplierChange(values.winDoubtMultiplier)} certainty; ${lowerTactic} losses cost you ${multiplierChange(
    values.receivedDoubtMultiplier,
  )} certainty.`;
}

export function tacticAffinityCode(traitId: Trait, tactic: DebateTactic): TraitCode {
  return {
    fallbackTactic: () => tactic,
    directSourceMultiplier: (input) => {
      if (input.tactic !== tactic) {
        return undefined;
      }

      return traitSettings<{ winDoubtMultiplier: number }>(input.config, traitId).winDoubtMultiplier;
    },
    directTargetMultiplier: (input) => {
      if (input.tactic !== tactic) {
        return undefined;
      }

      return traitSettings<{ receivedDoubtMultiplier: number }>(input.config, traitId).receivedDoubtMultiplier;
    },
  };
}
