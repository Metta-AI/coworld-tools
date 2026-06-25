import { ACHIEVEMENT_POINTS, debateWins, defineAchievement } from "./helpers.js";

export const winFinalRound = defineAchievement({
  id: "winFinalRound",
  name: "Win Final Round",
  description: "Wins the fifth round of a debate session.",
  condition: "Win round five of a debate session.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) => debateWins(context, (event) => (event.debate?.round ?? 0) >= 5).length > 0,
});
