import type { DebateTactic, Trait, VenueLocation } from "../../shared/types.js";
import { traitDefinitionFor } from "../../shared/traits/index.js";
import { stableIndex } from "../stable-index.js";

const TACTICS: DebateTactic[] = ["reason", "spin", "passion"];

export function preferredTacticForCog(cog: { id: string; defensiveTrait: Trait; activeTrait: Trait; location?: VenueLocation }): DebateTactic | undefined {
  for (const trait of new Set([cog.defensiveTrait, cog.activeTrait])) {
    const tactic = traitDefinitionFor(trait).code.fallbackTactic?.({ cog });
    if (tactic) {
      return tactic;
    }
  }
  return undefined;
}

export function fallbackTacticForCog(cog: { id: string; defensiveTrait: Trait; activeTrait: Trait; location?: VenueLocation }): DebateTactic {
  return preferredTacticForCog(cog) ?? TACTICS[stableIndex(cog.id, TACTICS.length)] ?? "reason";
}
