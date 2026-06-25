import { ACHIEVEMENT_POINTS, defineAchievement } from "./helpers.js";

export const perfectDebate = defineAchievement({
  id: "perfectDebate",
  name: "Perfect Rounds",
  description: "Builds a clean round win streak.",
  condition: "Record at least three round wins and zero round losses.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) => context.cog.stats.argumentsWon >= 3 && context.cog.stats.argumentsLost === 0,
});
