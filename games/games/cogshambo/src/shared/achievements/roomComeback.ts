import { ACHIEVEMENT_POINTS, debateRoomKind, defineAchievement, eventsSinceAssigned, hasRoomComeback } from "./helpers.js";

export const roomComeback = defineAchievement({
  id: "roomComeback",
  name: "$ROOM Comeback",
  description: "Wins in $ROOM after losing there.",
  condition: "Lose a round in a $ROOM room, then win a later round in a $ROOM room.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) =>
    hasRoomComeback(eventsSinceAssigned(context), context.cog.id, context.assignment.parameters?.roomKind, (event) =>
      debateRoomKind(context, event),
    ),
});
