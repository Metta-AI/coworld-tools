import { ACHIEVEMENT_POINTS, cogTactic, debateWins, defineAchievement } from "./helpers.js";

export const winWithAllTactics = defineAchievement({
  id: "winWithAllTactics",
  name: "Win With All Tactics",
  description: "Wins rounds with Reason, Spin, and Passion.",
  condition: "Win at least one round each with Reason, Spin, and Passion.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) => new Set(debateWins(context).map((event) => cogTactic(event, context.cog.id))).size >= 3,
});
