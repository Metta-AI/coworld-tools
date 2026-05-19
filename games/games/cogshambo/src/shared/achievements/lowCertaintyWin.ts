import { ACHIEVEMENT_POINTS, debateWins, defineAchievement } from "./helpers.js";

const LOW_CERTAINTY_THRESHOLD = 25;

export const lowCertaintyWin = defineAchievement({
  id: "lowCertaintyWin",
  name: "Low Certainty Win",
  description: "Wins a round while low on certainty.",
  condition: `Win one round while at or below ${LOW_CERTAINTY_THRESHOLD} certainty.`,
  timeoutTicks: 900,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) => context.cog.certainty <= LOW_CERTAINTY_THRESHOLD && debateWins(context).length > 0,
});
