import { ACHIEVEMENT_POINTS, convertedDebatersFromWitnessedDebates, defineAchievement, eventsSinceAssigned } from "./helpers.js";

export const conversionWitnessStreak = defineAchievement({
  id: "conversionWitnessStreak",
  name: "Conversion Witness Streak",
  description: "Watches two different debaters change teams after debate rounds.",
  condition: "Witness debate rounds that lead to two different debaters changing teams.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) => convertedDebatersFromWitnessedDebates(eventsSinceAssigned(context), context.cog.id).size >= 2,
});
