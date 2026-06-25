import { ACHIEVEMENT_POINTS, countEvents, defineAchievement } from "./helpers.js";

export const flipFlop = defineAchievement({
  id: "flipFlop",
  name: "FlipFlop",
  description: "Changes sides repeatedly.",
  condition: "Flip teams twice before the timer expires.",
  timeoutTicks: 1800,
  points: ACHIEVEMENT_POINTS,
  isAchieved: (context) => countEvents(context, (event) => event.type === "colorChange" && event.actorId === context.cog.id) >= 2,
});
