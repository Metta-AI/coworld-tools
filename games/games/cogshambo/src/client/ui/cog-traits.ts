import { SELECTABLE_TRAITS } from "../../shared/types";
import type { SelectableTrait } from "../../shared/types";

export type TraitKind = "defensiveTrait" | "activeTrait";

export const traits: readonly SelectableTrait[] = SELECTABLE_TRAITS;
export const defensiveTraits: readonly SelectableTrait[] = traits;
export const activeTraits: readonly SelectableTrait[] = traits;

export function isTrait(value: string): value is SelectableTrait {
  return traits.includes(value as SelectableTrait);
}

export function isDefensiveTrait(value: string): value is SelectableTrait {
  return isTrait(value);
}

export function isActiveTrait(value: string): value is SelectableTrait {
  return isTrait(value);
}
