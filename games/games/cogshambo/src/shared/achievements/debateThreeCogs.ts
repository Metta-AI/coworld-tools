import { ACHIEVEMENT_POINTS, debateOpponentIds, defineAchievement } from "./helpers.js";

export const debateThreeCogs = defineAchievement({
  id: "debateThreeCogs",
  name: "Debate Three Opponents",
  description: "Starts debate sessions with different opponents.",
  condition: "Complete at least one round in debate sessions against three distinct opponents.",
  timeoutTicks: 900,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) => debateOpponentIds(context).size >= 3,
});
