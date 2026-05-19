import { ACHIEVEMENT_POINTS, defineAchievement, eventsSinceAssigned, participantIds } from "./helpers.js";

export const witnessConversion = defineAchievement({
  id: "witnessConversion",
  name: "Witness Conversion",
  description: "Watches a debate round lead to a team conversion.",
  condition: "Witness a debate round where one of the debaters changes teams.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) => {
    const events = eventsSinceAssigned(context);
    for (const event of events) {
      if (event.type !== "debateExchange" || !event.debate?.witnessCogIds?.includes(context.cog.id)) {
        continue;
      }
      const debaterIds = new Set(participantIds(event));
      if (events.some((candidate) => candidate.type === "colorChange" && candidate.tick >= event.tick && candidate.actorId && debaterIds.has(candidate.actorId))) {
        return true;
      }
    }
    return false;
  },
});
