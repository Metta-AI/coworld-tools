import { ACHIEVEMENT_POINTS, debateWins, defineAchievement, hasTrait, opponentCog } from "./helpers.js";

export const traitHunter = defineAchievement({
  id: "traitHunter",
  name: "$TRAIT Hunter",
  description: "Wins $ROUNDS rounds against cogs with $TRAIT.",
  condition: "Win $ROUNDS rounds against opponents who have the $TRAIT trait.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) =>
    Boolean(context.assignment.parameters?.trait) &&
    debateWins(context, (event) => hasTrait(opponentCog(context, event), context.assignment.parameters?.trait)).length >=
      (context.assignment.parameters?.rounds ?? 3),
});
