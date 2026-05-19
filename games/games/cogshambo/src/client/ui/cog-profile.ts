import type { Attributes, PersonalGoal, Trait } from "../../shared/types";

export type CogProfileUpdate = {
  name: string;
  behaviorPrompt: string;
  attributes: Attributes;
  defensiveTrait: Trait;
  activeTrait: Trait;
  personalGoal?: PersonalGoal;
};
