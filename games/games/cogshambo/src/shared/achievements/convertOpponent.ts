import { ACHIEVEMENT_POINTS, convertedOpponentsAfterDebate, defineAchievement, eventsSinceAssigned } from "./helpers.js";

export const convertOpponent = defineAchievement({
  id: "convertOpponent",
  name: "Convert Opponent",
  description: "Debates an opponent who then changes teams.",
  condition: "Debate a cog and have that opponent change teams after the round.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) => convertedOpponentsAfterDebate(eventsSinceAssigned(context), context.cog.id).size > 0,
});
