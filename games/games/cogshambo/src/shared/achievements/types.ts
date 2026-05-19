import type { AchievementAssignment, AchievementId, AchievementParameters, Cog, WorldEvent, WorldSnapshot } from "../types.js";

export type AchievementTemplateVariable = "trait" | "team" | "room" | "tactic" | "rounds" | "cog";

export type AchievementCheckContext = {
  assignment: AchievementAssignment;
  cog: Cog;
  events: WorldEvent[];
  snapshot: WorldSnapshot;
  tick: number;
};

export type AchievementDefinition = {
  id: AchievementId;
  name: string;
  description: string;
  condition: string;
  timeoutTicks: number;
  points: number;
  isAchieved: (context: AchievementCheckContext) => boolean;
};

export type AchievementRule = {
  id: AchievementId;
  label: string;
  description: string;
  condition: string;
  timeoutTicks: number;
  points: number;
  parameters?: AchievementParameters;
  templateVariables: readonly AchievementTemplateVariable[];
};
