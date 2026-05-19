import { ACHIEVEMENT_POINTS, debateWins, defineAchievement } from "./helpers.js";

export const winAfterTwoLosses = defineAchievement({
  id: "winAfterTwoLosses",
  name: "Win After Two Losses",
  description: "Wins a round after taking two losses.",
  condition: "Win one round after at least two recorded round losses.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) => context.cog.stats.argumentsLost >= 2 && debateWins(context).length > 0,
});
