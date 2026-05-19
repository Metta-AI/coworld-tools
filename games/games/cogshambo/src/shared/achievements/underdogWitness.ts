import { ACHIEVEMENT_POINTS, defineAchievement, witnessedWins } from "./helpers.js";
import { TEAM_COLORS } from "../types.js";

export const underdogWitness = defineAchievement({
  id: "underdogWitness",
  name: "Underdog Witness",
  description: "Watches the smaller team win three rounds.",
  condition: "Witness three debate rounds won by the team with fewer cogs.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) => {
    const counts = TEAM_COLORS.map((color) => ({
      color,
      count: context.snapshot.cogs.filter((cog) => cog.color === color).length,
    })).sort((a, b) => a.count - b.count);
    const underdog = counts[0]?.count < counts[1]?.count ? counts[0].color : undefined;
    return Boolean(underdog && witnessedWins(context, (event) => event.debate?.winnerColor === underdog).length >= 3);
  },
});
