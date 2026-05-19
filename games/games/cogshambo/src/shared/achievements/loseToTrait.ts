import { ACHIEVEMENT_POINTS, defineAchievement, lostToTrait } from "./helpers.js";

export const loseToTrait = defineAchievement({
  id: "loseToTrait",
  name: "Lose Round to Cog with $TRAIT",
  description: "Takes a round loss from a cog with $TRAIT.",
  condition: "Lose one round to a cog with the $TRAIT trait.",
  timeoutTicks: 900,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) => lostToTrait(context, context.assignment.parameters?.trait),
});
