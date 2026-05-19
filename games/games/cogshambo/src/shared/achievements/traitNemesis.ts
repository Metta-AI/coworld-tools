import { ACHIEVEMENT_POINTS, debateLosses, defineAchievement, hasTrait, winnerCog } from "./helpers.js";

export const traitNemesis = defineAchievement({
  id: "traitNemesis",
  name: "Lose $ROUNDS Rounds to $TRAIT",
  description: "Loses $ROUNDS rounds to cogs with $TRAIT.",
  condition: "Lose $ROUNDS rounds to cogs with the $TRAIT trait.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) =>
    Boolean(context.assignment.parameters?.trait) &&
    debateLosses(context, (event) => hasTrait(winnerCog(context, event), context.assignment.parameters?.trait)).length >=
      (context.assignment.parameters?.rounds ?? 3),
});
