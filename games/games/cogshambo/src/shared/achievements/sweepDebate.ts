import { ACHIEVEMENT_POINTS, debatePairKey, defineAchievement, eventsSinceAssigned, isDebateParticipant } from "./helpers.js";

export const sweepDebate = defineAchievement({
  id: "sweepDebate",
  name: "Sweep Debate",
  description: "Wins three rounds in one debate session without losing a round.",
  condition: "Win three rounds against the same opponent with no round losses in that debate session.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) => {
    const sessions = new Map<string, { wins: number; losses: number }>();
    for (const event of eventsSinceAssigned(context)) {
      if (event.type !== "debateExchange" || !isDebateParticipant(event, context.cog.id)) {
        continue;
      }
      const key = debatePairKey(event);
      if (!key) {
        continue;
      }
      const session = sessions.get(key) ?? { wins: 0, losses: 0 };
      if (event.debate?.winnerCogId === context.cog.id) {
        session.wins += 1;
      } else if (event.debate?.winnerCogId) {
        session.losses += 1;
      }
      sessions.set(key, session);
    }
    return [...sessions.values()].some((session) => session.wins >= 3 && session.losses === 0);
  },
});
