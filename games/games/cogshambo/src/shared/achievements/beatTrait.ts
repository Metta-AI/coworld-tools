import { ACHIEVEMENT_POINTS, debateWins, defineAchievement, hasTrait, opponentCog } from "./helpers.js";

export const beatTrait = defineAchievement({
  id: "beatTrait",
  name: "Beat Cog with $TRAIT",
  description: "Wins a debate round against a cog with $TRAIT.",
  condition: "Win one round against a cog with the $TRAIT trait.",
  timeoutTicks: 900,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) =>
    Boolean(context.assignment.parameters?.trait) &&
    debateWins(context, (event) => hasTrait(opponentCog(context, event), context.assignment.parameters?.trait)).length > 0,
});
