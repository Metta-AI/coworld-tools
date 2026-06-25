import { ACHIEVEMENT_POINTS, debatePairKey, defineAchievement, eventsSinceAssigned } from "./helpers.js";

export const witnessComeback = defineAchievement({
  id: "witnessComeback",
  name: "Witness $TEAM Comeback",
  description: "Watches $TEAM win after losing the previous round in the same debate.",
  condition: "Witness $TEAM win a round after $TEAM lost the previous round in that debate session.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) => {
    const team = context.assignment.parameters?.team;
    if (!team) {
      return false;
    }
    const previousWinnerByDebate = new Map<string, string | undefined>();
    for (const event of eventsSinceAssigned(context).filter((candidate) => candidate.type === "debateExchange").sort((a, b) => a.tick - b.tick)) {
      const key = debatePairKey(event);
      if (!key) {
        continue;
      }
      const previousWinner = previousWinnerByDebate.get(key);
      if (
        previousWinner &&
        previousWinner !== team &&
        event.debate?.winnerColor === team &&
        event.debate?.witnessCogIds?.includes(context.cog.id)
      ) {
        return true;
      }
      previousWinnerByDebate.set(key, event.debate?.winnerColor);
    }
    return false;
  },
});
