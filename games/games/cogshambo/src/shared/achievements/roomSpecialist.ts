import { ACHIEVEMENT_POINTS, debateRoomKind, debateWins, defineAchievement } from "./helpers.js";

export const roomSpecialist = defineAchievement({
  id: "roomSpecialist",
  name: "Win $ROUNDS Rounds in $ROOM",
  description: "Wins $ROUNDS debate rounds in a $ROOM room.",
  condition: "Win $ROUNDS rounds while both debaters are in a $ROOM room.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) =>
    Boolean(context.assignment.parameters?.roomKind) &&
    debateWins(context, (event) => debateRoomKind(context, event) === context.assignment.parameters?.roomKind).length >=
      (context.assignment.parameters?.rounds ?? 3),
});
