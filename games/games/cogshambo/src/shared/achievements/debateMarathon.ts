import { ACHIEVEMENT_POINTS, debateWins, defineAchievement, eventsSinceAssigned, isDebateParticipant } from "./helpers.js";

export const debateMarathon = defineAchievement({
  id: "debateMarathon",
  name: "Five-Round Debate",
  description: "Stays in a debate session until the final round.",
  condition: "Participate in a debate session that reaches round five.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) =>
    debateWins(context).some((event) => (event.debate?.round ?? 0) >= 5) ||
    eventsSinceAssigned(context).some(
      (event) => event.type === "debateExchange" && isDebateParticipant(event, context.cog.id) && (event.debate?.round ?? 0) >= 5,
    ),
});
