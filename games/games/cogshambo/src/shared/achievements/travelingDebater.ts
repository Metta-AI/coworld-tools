import { ACHIEVEMENT_POINTS, debateRoomKind, debateWins, defineAchievement } from "./helpers.js";

export const travelingDebater = defineAchievement({
  id: "travelingDebater",
  name: "Traveling Debater",
  description: "Wins debate rounds in three different room kinds.",
  condition: "Win debate rounds in three different room kinds.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) =>
    new Set(debateWins(context).map((event) => debateRoomKind(context, event)).filter(Boolean)).size >= 3,
});
