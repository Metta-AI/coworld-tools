import { ACHIEVEMENT_POINTS, defineAchievement, eventsSinceAssigned, hasCounterComeback } from "./helpers.js";

export const counterComeback = defineAchievement({
  id: "counterComeback",
  name: "Counter Comeback",
  description: "Answers a lost round with a winning counter.",
  condition: "Lose a round, then win the next round in that debate session using a tactic that counters the opponent.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) => hasCounterComeback(eventsSinceAssigned(context), context.cog.id),
});
