import type { Cog, Color, DebateTactic, Trait, VenueLocation } from "../types.js";
import type { RuleDescriptionAudience } from "./format.js";

export type TraitId = Trait;
export type TraitKind = "trait";
export type LegacyTraitKind = "active" | "defensive";

export type TraitParameter = {
  key: string;
  label: string;
  description: string;
  min: number;
  max: number;
  step: number;
};

export type TraitRuntimeConfig = {
  conversionThreshold: number;
  conversionDoubtPercent: number;
  witnessDoubt: number;
  traitConfig: Record<string, Record<string, number>>;
};

export type TraitDescriptionInput = {
  config: TraitRuntimeConfig;
  audience: RuleDescriptionAudience;
};

export type TraitWitnessEffect = {
  type: "selfDoubt";
  amount: number;
};

export type TraitConversionEffect = {
  recoveries?: Array<{ cogId: string; color: Color; amount: number }>;
  avengerTargets?: Array<{ cogId: string; color: Color }>;
};

export type TraitCode = {
  debateCooldownMultiplier?: (input: { cog: Cog; config: TraitRuntimeConfig }) => number | undefined;
  passiveCertaintyChange?: (input: {
    cog: Cog;
    teamShare: number;
    config: TraitRuntimeConfig;
  }) => number | undefined;
  passiveColorFlip?: (input: { cog: Cog; teamShare: number; config: TraitRuntimeConfig }) => boolean | undefined;
  drawCertaintyLoss?: (input: { cog: Cog; config: TraitRuntimeConfig }) => number | undefined;
  roomEntryCertaintyLoss?: (input: { cog: Cog; sameRoomCogs: Cog[]; config: TraitRuntimeConfig }) => number | undefined;
  ownConversion?: (input: {
    convertedCog: Cog;
    sameRoomCogs: Cog[];
    previousColor: Color;
    winningColor: Color;
    config: TraitRuntimeConfig;
  }) => TraitConversionEffect | undefined;
  teammateConverted?: (input: {
    teammate: Cog;
    convertedCog: Cog;
    previousColor: Color;
    winningColor: Color;
    config: TraitRuntimeConfig;
  }) => TraitConversionEffect | undefined;
  directSourceMultiplier?: (input: {
    source: Cog;
    target: Cog;
    tactic?: DebateTactic;
    avengerTargetColor?: Color;
    config: TraitRuntimeConfig;
  }) => number | undefined;
  directTargetMultiplier?: (input: { source: Cog; target: Cog; tactic?: DebateTactic; config: TraitRuntimeConfig }) => number | undefined;
  indirectTargetMultiplier?: (input: { source: Cog; target: Cog; tactic?: DebateTactic; config: TraitRuntimeConfig }) => number | undefined;
  pressureTargetMultiplier?: (input: {
    source: Cog;
    target: Cog;
    pressureColor: Color;
    pressureTeamShare: number;
    uniquePopulationColor: (kind: "highest" | "lowest") => Color | undefined;
    config: TraitRuntimeConfig;
  }) => number | undefined;
  witnessBaseAmount?: (input: { winner: Cog; loser: Cog; config: TraitRuntimeConfig }) => number | undefined;
  witnessAmountMultiplier?: (input: {
    winner: Cog;
    loser: Cog;
    uniquePopulationColor: (kind: "highest" | "lowest") => Color | undefined;
    config: TraitRuntimeConfig;
  }) => number | undefined;
  sameTeamWitnessEffect?: (input: {
    winner: Cog;
    loser: Cog;
    witness: Cog;
    uniquePopulationColor: (kind: "highest" | "lowest") => Color | undefined;
    config: TraitRuntimeConfig;
  }) => TraitWitnessEffect | undefined;
  blocksConversion?: (input: { cog: Cog; config: TraitRuntimeConfig }) => number | undefined;
  fallbackTactic?: (input: { cog: { id: string; defensiveTrait: Trait; activeTrait: Trait; location?: VenueLocation } }) => DebateTactic | undefined;
};

export type TraitDefinition = {
  kind: LegacyTraitKind;
  id: TraitId;
  label: string;
  description: string;
  userDescription: string;
  promptDescription: string;
  modifiers: string[];
  parameters?: TraitParameter[];
  defaultConfig: Record<string, number>;
  describe?: (input: TraitDescriptionInput) => string;
  code: TraitCode;
  integrationTest: string;
};
