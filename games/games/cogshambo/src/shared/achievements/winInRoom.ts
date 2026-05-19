import { ACHIEVEMENT_POINTS, debateRoom, debateWins, defineAchievement } from "./helpers.js";

export const winInRoom = defineAchievement({
  id: "winInRoom",
  name: "Win Round in $ROOM",
  description: "Wins a debate round in a $ROOM room.",
  condition: "Win one round while both debaters are in a $ROOM room.",
  timeoutTicks: 600,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) =>
    debateWins(
      context,
      (event) => debateRoom(context, event)?.kind === (context.assignment.parameters?.roomKind ?? "bar"),
    ).length >= 1,
});
