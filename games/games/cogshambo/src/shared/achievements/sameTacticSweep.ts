import { ACHIEVEMENT_POINTS, cogTactic, debateWins, defineAchievement } from "./helpers.js";

export const sameTacticSweep = defineAchievement({
  id: "sameTacticSweep",
  name: "$TACTIC Sweep",
  description: "Wins three rounds with $TACTIC.",
  condition: "Win three rounds using the assigned $TACTIC tactic.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) =>
    Boolean(context.assignment.parameters?.tactic) &&
    debateWins(context, (event) => cogTactic(event, context.cog.id) === context.assignment.parameters?.tactic).length >= 3,
});
