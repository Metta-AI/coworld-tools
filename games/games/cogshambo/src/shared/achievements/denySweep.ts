import { ACHIEVEMENT_POINTS, defineAchievement, eventsSinceAssigned, hasDenySweep } from "./helpers.js";

export const denySweep = defineAchievement({
  id: "denySweep",
  name: "Deny Sweep",
  description: "Stops a debate sweep after losing the first two rounds.",
  condition: "Lose the first two decisive rounds in one debate session, then win a later round in that session.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) => hasDenySweep(eventsSinceAssigned(context), context.cog.id),
});
