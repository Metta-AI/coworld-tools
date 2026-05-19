import { TRAITS } from "./ids.js";
import { avenger } from "./avenger.js";
import { bandwagoner } from "./bandwagoner.js";
import { charismatic } from "./charismatic.js";
import { conformist } from "./conformist.js";
import { contrarian } from "./contrarian.js";
import { defector } from "./defector.js";
import { diplomat } from "./diplomat.js";
import { doubter } from "./doubter.js";
import { forceful } from "./forceful.js";
import { heretic } from "./heretic.js";
import { hippie } from "./hippie.js";
import { iconoclast } from "./iconoclast.js";
import { insurgent } from "./insurgent.js";
import { insular } from "./insular.js";
import { martyr } from "./martyr.js";
import { passionate } from "./passionate.js";
import { polarizer } from "./polarizer.js";
import { rationalist } from "./rationalist.js";
import { spinner } from "./spinner.js";
import { stubborn } from "./stubborn.js";
import { zealot } from "./zealot.js";
import type { TraitDefinition, TraitId } from "./types.js";

export type {
  TraitCode,
  TraitConversionEffect,
  TraitDefinition,
  TraitId,
  TraitKind,
  TraitParameter,
  TraitRuntimeConfig,
} from "./types.js";

export const DEFENSIVE_TRAIT_MODULES = [
  stubborn,
  insular,
  iconoclast,
  conformist,
  defector,
  bandwagoner,
  martyr,
  doubter,
  diplomat,
  heretic,
  zealot,
] as const satisfies readonly TraitDefinition[];

export const ACTIVE_TRAIT_MODULES = [
  forceful,
  charismatic,
  contrarian,
  hippie,
  rationalist,
  spinner,
  passionate,
  avenger,
  insurgent,
  polarizer,
] as const satisfies readonly TraitDefinition[];

export const TRAIT_MODULES = [...DEFENSIVE_TRAIT_MODULES, ...ACTIVE_TRAIT_MODULES] as const satisfies readonly TraitDefinition[];

export const DEFAULT_TRAIT_CONFIG = Object.fromEntries(
  TRAIT_MODULES.map((trait) => [trait.id, { ...trait.defaultConfig }]),
) as Record<TraitId, Record<string, number>>;

export const TRAIT_RULES_FROM_MODULES = TRAIT_MODULES.map((trait) => ({
  kind: "trait" as const,
  id: trait.id,
  label: trait.label,
  description: trait.description,
  userDescription: trait.userDescription,
  playerDescription: trait.userDescription,
  promptDescription: trait.promptDescription,
  modifiers: trait.modifiers,
  parameters: trait.parameters,
}));

const TRAIT_MODULE_BY_ID = new Map<TraitId, TraitDefinition>(TRAIT_MODULES.map((trait) => [trait.id, trait]));
const LEGACY_TRAIT_IDS = {
  reasoner: "rationalist",
} as const satisfies Record<string, TraitId>;

assertRegistryOrder("traits", TRAITS, TRAIT_MODULES);

export function normalizeTraitId(traitId: TraitId | string): TraitId | string {
  if (traitId in LEGACY_TRAIT_IDS) {
    return LEGACY_TRAIT_IDS[traitId as keyof typeof LEGACY_TRAIT_IDS];
  }
  return traitId;
}

export function traitDefinitionFor(traitId: TraitId | string): TraitDefinition {
  const normalizedTraitId = normalizeTraitId(traitId);
  const definition = TRAIT_MODULE_BY_ID.get(normalizedTraitId as TraitId);
  if (!definition) {
    throw new Error(`Missing trait definition for ${traitId}`);
  }
  return definition;
}

function assertRegistryOrder(kind: string, ids: readonly string[], modules: readonly TraitDefinition[]): void {
  const moduleIds = modules.map((trait) => trait.id);
  const mismatch = ids.find((id, index) => moduleIds[index] !== id);
  if (mismatch) {
    throw new Error(`Trait registry order mismatch for ${kind}: expected ${mismatch}`);
  }
}
