import { ACHIEVEMENT_POINTS, defineAchievement, eventsSinceAssigned, hasWinFromBehind } from "./helpers.js";

export const winFromBehind = defineAchievement({
  id: "winFromBehind",
  name: "Win From Behind",
  description: "Wins a debate session after falling behind.",
  condition: "Fall behind in one debate session, then reach three round wins and lead the session.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) => hasWinFromBehind(eventsSinceAssigned(context), context.cog.id),
});
