import { ACHIEVEMENT_POINTS, defineAchievement, eventsSinceAssigned, hasDrawBreaker } from "./helpers.js";

export const drawBreaker = defineAchievement({
  id: "drawBreaker",
  name: "Draw Breaker",
  description: "Wins the round after a draw.",
  condition: "After a draw, win the next recorded round in the same debate session.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) => hasDrawBreaker(eventsSinceAssigned(context), context.cog.id),
});
