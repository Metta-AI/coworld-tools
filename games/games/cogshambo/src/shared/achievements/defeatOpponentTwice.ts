import { ACHIEVEMENT_POINTS, debateWins, defineAchievement, opponentId } from "./helpers.js";

export const defeatOpponentTwice = defineAchievement({
  id: "defeatOpponentTwice",
  name: "Defeat $COG Twice",
  description: "Wins two rounds against $COG.",
  condition: "Win two debate rounds against $COG.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) =>
    Boolean(context.assignment.parameters?.cogId) &&
    debateWins(context, (event) => opponentId(event, context.cog.id) === context.assignment.parameters?.cogId).length >= 2,
});
