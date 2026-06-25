import { ACHIEVEMENT_POINTS, defineAchievement, witnessedWins } from "./helpers.js";

export const finalRoundWitness = defineAchievement({
  id: "finalRoundWitness",
  name: "Final Round Witness",
  description: "Watches the fifth round of a debate session.",
  condition: "Witness a round 5 debate exchange.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) => witnessedWins(context, (event) => (event.debate?.round ?? 0) >= 5).length > 0,
});
