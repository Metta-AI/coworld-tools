import { ACHIEVEMENT_POINTS, defineAchievement, witnessedWins } from "./helpers.js";

const DEFAULT_ROUNDS = 3;

export const witnessTeamWins = defineAchievement({
  id: "witnessTeamWins",
  name: "Witness $TEAM Win $ROUNDS Rounds",
  description: "Watches $TEAM win $ROUNDS debate rounds.",
  condition: "Witness $ROUNDS rounds won by $TEAM.",
  timeoutTicks: 1200,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) =>
    Boolean(
      context.assignment.parameters?.team &&
        witnessedWins(context, (event) => event.debate?.winnerColor === context.assignment.parameters?.team).length >=
          (context.assignment.parameters.rounds ?? DEFAULT_ROUNDS),
    ),
});
