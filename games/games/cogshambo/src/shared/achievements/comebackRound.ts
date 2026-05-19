import { ACHIEVEMENT_POINTS, debateWins, defineAchievement } from "./helpers.js";

export const comebackRound = defineAchievement({
  id: "comebackRound",
  name: "Comeback Round",
  description: "Wins a round after taking losses.",
  condition: "Win a round after at least one recorded round loss.",
  timeoutTicks: 900,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) => context.cog.stats.argumentsLost > 0 && debateWins(context).length > 0,
});
