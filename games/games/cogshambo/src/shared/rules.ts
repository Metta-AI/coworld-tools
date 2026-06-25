import {
  ACHIEVEMENT_DEFINITIONS,
  ACHIEVEMENT_POINTS,
  ACHIEVEMENT_RULES,
  achievementDisplayName,
  achievementKey,
  achievementDefinitionById,
  achievementRuleByAssignment,
} from "./achievements/index.js";
import { ACHIEVEMENT_IDS } from "./achievements/ids.js";
import {
  DEFAULT_TRAIT_CONFIG,
  TRAIT_RULES_FROM_MODULES,
  traitDefinitionFor,
} from "./traits/index.js";
import { legacyHalfSecondTicksToSimulationTicks, secondsToSimulationTicks } from "./timing.js";
import type { PersonalGoal, Trait } from "./types.js";

export {
  ACHIEVEMENT_DEFINITIONS,
  ACHIEVEMENT_IDS,
  ACHIEVEMENT_POINTS,
  ACHIEVEMENT_RULES,
  achievementDisplayName,
  achievementKey,
  achievementDefinitionById,
  achievementRuleByAssignment,
};
export type { AchievementRule } from "./achievements/types.js";

export type GameConfig = {
  debateDoubt: number;
  debateWinCertaintyGain: number;
  conversionThreshold: number;
  conversionDoubtPercent: number;
  maxDebatesPerTick: number;
  maxDebateRounds: number;
  debatePrepTicks: number;
  debateChoiceRevealTicks: number;
  debateResultTicks: number;
  debateCooldownTicks: number;
  witnessDoubt: number;
  roomMoveCooldownTicks: number;
  traitConfig: TraitConfig;
};

export type TraitConfig = {
  stubborn: {
    directDoubtMultiplier: number;
  };
  insular: {
    indirectDoubtMultiplier: number;
  };
  iconoclast: {
    dominantDoubtMultiplier: number;
  };
  conformist: {
    fringeDoubtMultiplier: number;
  };
  defector: {
    majorityThreshold: number;
    majorityDoubt: number;
  };
  bandwagoner: {
    majorityThreshold: number;
    majorityRecovery: number;
  };
  martyr: {
    teammateRecovery: number;
  };
  doubter: {
    drawDoubt: number;
  };
  diplomat: {
    majorityWinDoubt: number;
  };
  heretic: {
    crowdedRoomThreshold: number;
    crowdedRoomDoubt: number;
  };
  zealot: {
    minCertainty: number;
  };
  forceful: {
    winDoubtMultiplier: number;
  };
  charismatic: {
    witnessDoubt: number;
  };
  contrarian: {
    debateCooldownMultiplier: number;
    majorityPressureDiscount: number;
    overwhelmingTeamThreshold: number;
    unanimousRoomDoubt: number;
  };
  hippie: {
    reasonWinDoubtMultiplier: number;
    reasonReceivedDoubtMultiplier: number;
    passionWinDoubtMultiplier: number;
    passionReceivedDoubtMultiplier: number;
  };
  rationalist: {
    winDoubtMultiplier: number;
    receivedDoubtMultiplier: number;
  };
  spinner: {
    winDoubtMultiplier: number;
    receivedDoubtMultiplier: number;
  };
  passionate: {
    winDoubtMultiplier: number;
    receivedDoubtMultiplier: number;
  };
  avenger: {
    nextWinDoubtMultiplier: number;
  };
  insurgent: {
    minorityWitnessMultiplier: number;
  };
  polarizer: {
    lowCertaintyThreshold: number;
    sameTeamDoubt: number;
  };
};

export type TraitConfigInput = {
  [TraitId in keyof TraitConfig]?: Partial<TraitConfig[TraitId]>;
};

export type GameConfigInput = Partial<Omit<GameConfig, "traitConfig">> & {
  traitConfig?: TraitConfigInput;
};

export type GameParameterKey = Exclude<keyof GameConfig, "traitConfig">;

export type RuleParameter = {
  key: GameParameterKey;
  label: string;
  description: string;
  min: number;
  max: number;
  step: number;
};

export type TraitParameter = {
  key: string;
  label: string;
  description: string;
  min: number;
  max: number;
  step: number;
};

export type TraitRule = {
  kind: "trait";
  id: Trait;
  label: string;
  description: string;
  userDescription: string;
  playerDescription: string;
  promptDescription: string;
  modifiers: string[];
  parameters?: TraitParameter[];
};

export type GoalRule = {
  id: PersonalGoal;
  label: string;
  description: string;
  playerDescription: string;
  promptDescription: string;
  condition: string;
};

const TIMING_PARAMETER_KEYS = [
  "debatePrepTicks",
  "debateChoiceRevealTicks",
  "debateResultTicks",
  "debateCooldownTicks",
  "roomMoveCooldownTicks",
] as const satisfies readonly GameParameterKey[];

type TimingParameterKey = (typeof TIMING_PARAMETER_KEYS)[number];

const LEGACY_DEFAULT_TIMING_TICKS: Pick<GameConfig, TimingParameterKey> = {
  debatePrepTicks: 2,
  debateChoiceRevealTicks: 2,
  debateResultTicks: 6,
  debateCooldownTicks: 600,
  roomMoveCooldownTicks: 120,
};

const HIGH_FREQUENCY_DEFAULT_TIMING_TICKS: Pick<GameConfig, TimingParameterKey> = {
  debatePrepTicks: 60,
  debateChoiceRevealTicks: 60,
  debateResultTicks: 180,
  debateCooldownTicks: 18000,
  roomMoveCooldownTicks: 3600,
};

export const DEFAULT_GAME_CONFIG: GameConfig = {
  debateDoubt: 10,
  debateWinCertaintyGain: 5,
  conversionThreshold: 100,
  conversionDoubtPercent: 50,
  maxDebatesPerTick: 3,
  maxDebateRounds: 5,
  debatePrepTicks: secondsToSimulationTicks(1),
  debateChoiceRevealTicks: secondsToSimulationTicks(1),
  debateResultTicks: secondsToSimulationTicks(3),
  debateCooldownTicks: secondsToSimulationTicks(5 * 60),
  witnessDoubt: 2,
  roomMoveCooldownTicks: secondsToSimulationTicks(60),
  traitConfig: DEFAULT_TRAIT_CONFIG as TraitConfig,
};

export const RULE_PARAMETERS: RuleParameter[] = [
  {
    key: "debateDoubt",
    label: "Round loser certainty loss",
    description: "Base certainty removed from the loser of a decisive rock/paper/scissors round.",
    min: 0,
    max: 100,
    step: 1,
  },
  {
    key: "debateWinCertaintyGain",
    label: "Round winner certainty gain",
    description: "Base certainty restored to the winner of a decisive rock/paper/scissors round.",
    min: 0,
    max: 100,
    step: 1,
  },
  {
    key: "conversionThreshold",
    label: "Certainty scale",
    description: "Cogs start at this certainty value and flip teams when certainty reaches 0.",
    min: 1,
    max: 500,
    step: 1,
  },
  {
    key: "conversionDoubtPercent",
    label: "Post-conversion uncertainty",
    description: "Uncertainty retained after conversion, as a percent of the threshold.",
    min: 0,
    max: 100,
    step: 1,
  },
  {
    key: "maxDebatesPerTick",
    label: "Debates per tick",
    description: "Maximum number of new debates the game can start on a tick.",
    min: 1,
    max: 12,
    step: 1,
  },
  {
    key: "maxDebateRounds",
    label: "Debate rounds",
    description: "Maximum number of resolved rounds before a debate ends.",
    min: 1,
    max: 20,
    step: 1,
  },
  {
    key: "debatePrepTicks",
    label: "Debate prep ticks",
    description: "Ticks between starting a debate round and revealing tactic choices. Default is 1 second at 2 tps.",
    min: 0,
    max: legacyHalfSecondTicksToSimulationTicks(120),
    step: 1,
  },
  {
    key: "debateChoiceRevealTicks",
    label: "Choice reveal ticks",
    description: "Ticks tactic choices stay visible before the result is highlighted. Default is 1 second at 2 tps.",
    min: 0,
    max: legacyHalfSecondTicksToSimulationTicks(120),
    step: 1,
  },
  {
    key: "debateResultTicks",
    label: "Result reveal ticks",
    description: "Ticks the round result stays visible before the next round starts preparing. Default is 3 seconds at 2 tps.",
    min: 0,
    max: legacyHalfSecondTicksToSimulationTicks(120),
    step: 1,
  },
  {
    key: "debateCooldownTicks",
    label: "Pair cooldown ticks",
    description: "Ticks before the same two cogs can debate each other again. Default is 5 minutes at 2 tps.",
    min: 0,
    max: legacyHalfSecondTicksToSimulationTicks(3600),
    step: 1,
  },
  {
    key: "witnessDoubt",
    label: "Witness certainty swing",
    description: "Small certainty gain for winner-color witnesses and loss for other same-room witnesses after each decisive round.",
    min: 0,
    max: 50,
    step: 1,
  },
  {
    key: "roomMoveCooldownTicks",
    label: "Room move cooldown",
    description: "Ticks after entering a room before a cog can leave while other cogs are present. Default is 1 minute at 2 tps.",
    min: 0,
    max: legacyHalfSecondTicksToSimulationTicks(3600),
    step: 1,
  },
];

export const TRAIT_RULES: TraitRule[] = TRAIT_RULES_FROM_MODULES as TraitRule[];

export const GOAL_RULES: GoalRule[] = [];

export function traitPlayerDescription(rule: TraitRule, config: GameConfig = DEFAULT_GAME_CONFIG): string {
  return renderedTraitDescription(rule, config, "player");
}

export function traitPromptDescription(rule: TraitRule, config: GameConfig = DEFAULT_GAME_CONFIG): string {
  return renderedTraitDescription(rule, config, "prompt");
}

export function goalPlayerDescription(rule: GoalRule): string {
  return rule.playerDescription;
}

export function goalPromptDescription(rule: GoalRule): string {
  return rule.promptDescription;
}

type RuleDescriptionAudience = "player" | "prompt";

function renderedTraitDescription(rule: TraitRule, config: GameConfig, audience: RuleDescriptionAudience): string {
  const definition = traitDefinitionFor(rule.id);
  return definition.describe?.({
    config,
    audience: audience === "player" ? "user" : "prompt",
  }) ?? (audience === "player" ? rule.playerDescription : rule.promptDescription);
}

export function normalizeGameConfig(input: GameConfigInput = {}): GameConfig {
  const migratedInput = migrateLegacyDefaultTiming(input);
  const normalized = RULE_PARAMETERS.reduce<GameConfig>(
    (config, parameter) => {
      const value = migratedInput[parameter.key];
      if (typeof value !== "number" || !Number.isFinite(value)) {
        return config;
      }

      config[parameter.key] = clampToParameter(value, parameter) as never;
      return config;
    },
    cloneGameConfig(DEFAULT_GAME_CONFIG),
  );

  for (const trait of TRAIT_RULES) {
    const inputTraitConfig = input.traitConfig?.[trait.id];
    if (!inputTraitConfig || !trait.parameters?.length) {
      continue;
    }

    for (const parameter of trait.parameters) {
      const value = inputTraitConfig[parameter.key as keyof typeof inputTraitConfig];
      if (typeof value !== "number" || !Number.isFinite(value)) {
        continue;
      }

      (normalized.traitConfig[trait.id] as Record<string, number>)[parameter.key] = clampToParameter(value, parameter);
    }
  }

  return normalized;
}

function migrateLegacyDefaultTiming(input: GameConfigInput): GameConfigInput {
  if (
    !timingMatches(input, LEGACY_DEFAULT_TIMING_TICKS) &&
    !timingMatches(input, HIGH_FREQUENCY_DEFAULT_TIMING_TICKS)
  ) {
    return input;
  }

  return {
    ...input,
    debatePrepTicks: DEFAULT_GAME_CONFIG.debatePrepTicks,
    debateChoiceRevealTicks: DEFAULT_GAME_CONFIG.debateChoiceRevealTicks,
    debateResultTicks: DEFAULT_GAME_CONFIG.debateResultTicks,
    debateCooldownTicks: DEFAULT_GAME_CONFIG.debateCooldownTicks,
    roomMoveCooldownTicks: DEFAULT_GAME_CONFIG.roomMoveCooldownTicks,
  };
}

function timingMatches(input: GameConfigInput, timing: Pick<GameConfig, TimingParameterKey>): boolean {
  return TIMING_PARAMETER_KEYS.every((key) => input[key] === timing[key]);
}

export function cloneGameConfig(config: GameConfig): GameConfig {
  return {
    ...config,
    traitConfig: cloneTraitConfig(config.traitConfig),
  };
}

function clampToParameter(value: number, parameter: RuleParameter | TraitParameter): number {
  const stepped = parameter.step > 0 ? Math.round(value / parameter.step) * parameter.step : value;
  const normalized = Number(stepped.toFixed(6));
  return Math.max(parameter.min, Math.min(parameter.max, normalized));
}

function cloneTraitConfig(config: TraitConfig): TraitConfig {
  return Object.fromEntries(
    Object.entries(config).map(([traitId, traitConfig]) => [traitId, { ...traitConfig }]),
  ) as TraitConfig;
}
