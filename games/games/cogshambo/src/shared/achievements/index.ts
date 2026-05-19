import { winInRoom } from "./winInRoom.js";
import { comebackRound } from "./comebackRound.js";
import { debateMarathon } from "./debateMarathon.js";
import { debateThreeCogs } from "./debateThreeCogs.js";
import { loseToTrait } from "./loseToTrait.js";
import { perfectDebate } from "./perfectDebate.js";
import { flipFlop } from "./flipFlop.js";
import { witnessTeamWins } from "./witnessTeamWins.js";
import { beatTrait } from "./beatTrait.js";
import { convertOpponent } from "./convertOpponent.js";
import { conversionWitnessStreak } from "./conversionWitnessStreak.js";
import { counterComeback } from "./counterComeback.js";
import { defeatOpponentTwice } from "./defeatOpponentTwice.js";
import { denySweep } from "./denySweep.js";
import { drawBreaker } from "./drawBreaker.js";
import { finalRoundWitness } from "./finalRoundWitness.js";
import { lowCertaintyWin } from "./lowCertaintyWin.js";
import { revengeRound } from "./revengeRound.js";
import { roomComeback } from "./roomComeback.js";
import { roomSpecialist } from "./roomSpecialist.js";
import { sameTacticSweep } from "./sameTacticSweep.js";
import { socialCircuit } from "./socialCircuit.js";
import { sweepDebate } from "./sweepDebate.js";
import { traitHunter } from "./traitHunter.js";
import { traitNemesis } from "./traitNemesis.js";
import { travelingDebater } from "./travelingDebater.js";
import { underdogWitness } from "./underdogWitness.js";
import { winFromBehind } from "./winFromBehind.js";
import { winAfterTwoLosses } from "./winAfterTwoLosses.js";
import { winFinalRound } from "./winFinalRound.js";
import { winWithAllTactics } from "./winWithAllTactics.js";
import { witnessComeback } from "./witnessComeback.js";
import { witnessConversion } from "./witnessConversion.js";
import { achievementKey, achievementTemplateVariables, formatAchievementText } from "./helpers.js";
import type { AchievementDefinition, AchievementRule } from "./types.js";

export { ACHIEVEMENT_IDS } from "./ids.js";
export { ACHIEVEMENT_POINTS } from "./helpers.js";
export type { AchievementCheckContext, AchievementDefinition, AchievementRule } from "./types.js";

export const ACHIEVEMENT_DEFINITIONS = [
  debateThreeCogs,
  winInRoom,
  witnessTeamWins,
  flipFlop,
  debateMarathon,
  comebackRound,
  perfectDebate,
  loseToTrait,
  winFinalRound,
  winAfterTwoLosses,
  beatTrait,
  defeatOpponentTwice,
  witnessComeback,
  sweepDebate,
  winWithAllTactics,
  roomSpecialist,
  travelingDebater,
  witnessConversion,
  traitNemesis,
  revengeRound,
  lowCertaintyWin,
  socialCircuit,
  underdogWitness,
  drawBreaker,
  denySweep,
  convertOpponent,
  finalRoundWitness,
  winFromBehind,
  sameTacticSweep,
  counterComeback,
  roomComeback,
  traitHunter,
  conversionWitnessStreak,
] as const satisfies readonly AchievementDefinition[];

export const ACHIEVEMENT_RULES: AchievementRule[] = ACHIEVEMENT_DEFINITIONS.map((definition) => ({
  id: definition.id,
  label: formatAchievementText(definition.name),
  description: formatAchievementText(definition.description),
  condition: formatAchievementText(definition.condition),
  timeoutTicks: definition.timeoutTicks,
  points: definition.points,
  templateVariables: achievementTemplateVariables(definition),
}));

export function achievementDefinitionById(id: AchievementDefinition["id"]): AchievementDefinition {
  const definition = ACHIEVEMENT_DEFINITIONS.find((achievement) => achievement.id === id);
  if (!definition) {
    throw new Error(`Unknown achievement: ${id}`);
  }
  return definition;
}

export function achievementRuleByAssignment(input: {
  achievementId: AchievementDefinition["id"];
  parameters?: AchievementRule["parameters"];
}): AchievementRule | undefined {
  const rule = ACHIEVEMENT_RULES.find((candidate) => candidate.id === input.achievementId);
  if (!rule) {
    return undefined;
  }
  const definition = achievementDefinitionById(input.achievementId);

  return {
    ...rule,
    label: formatAchievementText(definition.name, input.parameters),
    description: formatAchievementText(definition.description, input.parameters),
    condition: formatAchievementText(definition.condition, input.parameters),
    ...(input.parameters ? { parameters: { ...input.parameters } } : {}),
  };
}

export function achievementDisplayName(input: {
  achievementId: AchievementDefinition["id"];
  parameters?: AchievementRule["parameters"];
}): string {
  const rule = achievementRuleByAssignment(input);
  if (rule) {
    return rule.label;
  }

  return formatAchievementText(achievementDefinitionById(input.achievementId).name, input.parameters);
}

export { achievementKey };
