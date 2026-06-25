import { ACHIEVEMENT_POINTS, defineAchievement, eventsSinceAssigned, isDebateParticipant, opponentId } from "./helpers.js";

export const revengeRound = defineAchievement({
  id: "revengeRound",
  name: "Revenge Round vs $COG",
  description: "Loses to $COG, then wins a later round against $COG.",
  condition: "Lose one round to $COG, then later win one round against $COG.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) => {
    const targetId = context.assignment.parameters?.cogId;
    if (!targetId) {
      return false;
    }
    let lostToTarget = false;
    for (const event of eventsSinceAssigned(context).filter((candidate) => candidate.type === "debateExchange").sort((a, b) => a.tick - b.tick)) {
      if (!isDebateParticipant(event, context.cog.id) || opponentId(event, context.cog.id) !== targetId) {
        continue;
      }
      if (event.debate?.winnerCogId === context.cog.id && lostToTarget) {
        return true;
      }
      if (event.debate?.winnerCogId === targetId) {
        lostToTarget = true;
      }
    }
    return false;
  },
});
