import { ACHIEVEMENT_POINTS, debateRoomKind, defineAchievement, eventsSinceAssigned, isDebateParticipant, opponentId } from "./helpers.js";

export const socialCircuit = defineAchievement({
  id: "socialCircuit",
  name: "Social Circuit",
  description: "Debates three opponents across three room kinds.",
  condition: "Complete debate rounds with three different opponents in three different room kinds.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) => {
    const opponents = new Set<string>();
    const rooms = new Set<string>();
    for (const event of eventsSinceAssigned(context)) {
      if (event.type !== "debateExchange" || !isDebateParticipant(event, context.cog.id)) {
        continue;
      }
      const opponent = opponentId(event, context.cog.id);
      const room = debateRoomKind(context, event);
      if (opponent) {
        opponents.add(opponent);
      }
      if (room) {
        rooms.add(room);
      }
    }
    return opponents.size >= 3 && rooms.size >= 3;
  },
});
