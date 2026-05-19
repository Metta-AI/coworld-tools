import {
  DEFAULT_GAME_CONFIG,
  TRAIT_RULES,
  achievementDisplayName,
  achievementRuleByAssignment,
  traitPromptDescription,
  type GameConfig,
} from "../../shared/rules.js";
import type {
  AchievementAssignment,
  Cog,
  CogAction,
  CogDecisionInput,
  CogObservation,
  DebateTactic,
  Direction,
  VisibleEntity,
  WorldEvent,
} from "../../shared/types.js";
import { simulationTicksToSeconds } from "../../shared/timing.js";

const CONVERSION_THRESHOLD = 100;
const DEBATE_TACTICS: readonly DebateTactic[] = ["reason", "spin", "passion"];
const DIRECTIONS: readonly Direction[] = ["north", "south", "east", "west"];

export type ControllerDecisionChoice = {
  label: string;
  action: CogAction;
  randomTactic?: boolean;
};

export function buildControllerDecisionPrompt(input: CogDecisionInput): string {
  const gameConfig = input.gameConfig ?? DEFAULT_GAME_CONFIG;
  return [
    "Instructions:",
    ...instructionLines(input),
    ...behaviorPromptLines(input.observation.cog),
    "",
    "You are:",
    ...traitLines(input.observation.cog, gameConfig),
    "",
    "Your achievements are:",
    ...achievementLines(input),
    "",
    "Current State:",
    ...currentStateLines(input),
    "",
    "Transcript:",
    ...transcriptLines(input),
    "",
    "Pick an action:",
    ...validActions(input),
  ].join("\n");
}

function instructionLines(input: CogDecisionInput): string[] {
  const cog = input.observation.cog;
  return [
    `Your name is ${cog.name}, and you are attending a party at the Grey Area Foundation.`,
    `You are on team ${formatColor(cog.color)}, and are ${certaintyPercent(cog)}% certain that you're on the correct team.`,
    "You can move around the venue and talk with other guests.",
    "When you talk to members of the opposite team, you might start a debate session about which team is right.",
    "A debate is one two-cog session against a single opponent.",
    "A debate can last up to five rounds.",
    "Each round, choose Reason, Spin, or Passion to convince your opponent.",
    "",
    "Reason beats Spin",
    "Spin beats Passion",
    "Passion beats Reason",
    "",
    "If you win a round, their certainty will drop, and yours can increase.",
    "Others in the room can also be affected by each round's result.",
    "If certainty drops to 0, that cog flips to the other team.",
    "Return a Thoughts paragraph, then return Choice with one valid action number.",
  ];
}

function behaviorPromptLines(cog: Cog): string[] {
  const behaviorPrompt = cog.behaviorPrompt.trim();
  return behaviorPrompt ? ["", "Your approach:", behaviorPrompt] : [];
}

function validActions(input: CogDecisionInput): string[] {
  const choices = controllerDecisionChoices(input);

  if (choices.length === 0) {
    return ["No valid actions this tick."];
  }

  const lines = choices.map((choice, index) => `${index + 1}. ${choice.label}`);
  return lines;
}

export function controllerDecisionChoices(input: CogDecisionInput): ControllerDecisionChoice[] {
  const choices: ControllerDecisionChoice[] = [];
  const suppressWait = input.allowedActions.includes("debate");
  for (const action of input.allowedActions) {
    if (action === "wait" && suppressWait) {
      continue;
    }

    if (action === "chooseTactic") {
      choices.push(
        ...DEBATE_TACTICS.map((tactic) => ({
          label: titleCase(tactic),
          action: { type: "chooseTactic", tactic } satisfies CogAction,
        })),
        {
          label: "Random",
          action: { type: "chooseTactic", tactic: "reason" } satisfies CogAction,
          randomTactic: true,
        },
      );
    } else if (action === "move") {
      choices.push(...moveChoices(input));
    } else if (action === "debate") {
      choices.push({ label: "Debate", action: { type: "debate" } });
    } else if (action === "wait") {
      choices.push({ label: "Wait", action: { type: "wait" } });
    } else {
      choices.push({ label: titleCase(action), action: { type: action } as CogAction });
    }
  }

  return choices;
}

function traitLines(cog: Cog, gameConfig: GameConfig): string[] {
  return [cog.defensiveTrait, cog.activeTrait].map((trait) => {
    const rule = TRAIT_RULES.find((candidate) => candidate.id === trait);
    const details = rule ? traitPromptDescription(rule, gameConfig) : "No rule text found.";
    return `  [${rule?.label ?? titleCase(trait)}] - ${details}`;
  });
}

function achievementLines(input: CogDecisionInput): string[] {
  const cog = input.observation.cog;
  const lines: string[] = [];
  for (const achievement of cog.achievements ?? []) {
    lines.push(`   - ${achievementLine(achievement, input.tick)}`);
  }
  return lines.length ? lines : ["   - No active achievements."];
}

function achievementLine(achievement: AchievementAssignment, tick: number): string {
  const rule = achievementRuleByAssignment(achievement);
  const name = achievementDisplayName(achievement);
  const remainingSeconds = Math.ceil(simulationTicksToSeconds(Math.max(0, achievement.timeoutTick - tick)));
  const condition = rule?.condition ? ` - ${rule.condition}` : "";
  return `${name} [${remainingSeconds}s left]${condition}`;
}

function currentStateLines(input: CogDecisionInput): string[] {
  return [
    `Nearby Team Size: ${teamSizeLine(input)}`,
    currentLocationLine(input),
    ...humanSteerLines(input),
    `Nearby guests: ${audienceLine(input)}`,
  ];
}

function humanSteerLines(input: CogDecisionInput): string[] {
  const intent = input.observation.cog.intent?.trim();
  return intent?.startsWith("player steer:") ? [`Human steer: ${intent.slice("player steer:".length).trim()}`] : [];
}

function teamSizeLine(input: CogDecisionInput): string {
  const selfColor = formatColor(input.observation.cog.color);
  const counts = new Map<string, number>([[selfColor, 1]]);
  for (const cog of visibleCogs(input.observation)) {
    const color = formatColor(cog.color);
    counts.set(color, (counts.get(color) ?? 0) + 1);
  }

  return Array.from(counts.entries())
    .sort(([left], [right]) => (left === selfColor ? -1 : right === selfColor ? 1 : left.localeCompare(right)))
    .map(([color, count]) => `${color} - ${count}`)
    .join(", ");
}

function currentLocationLine(input: CogDecisionInput): string {
  const cog = input.observation.cog;
  if (cog.debate) {
    const opponent = entityName(input, cog.debate.opponentId);
    const opponentColor = entityColor(input, cog.debate.opponentId);
    return `You're in [${locationDisplayName(input)}] debating ${opponent} (${opponentColor}, ${opponentCertainty(input, cog.debate.opponentId)})`;
  }
  if (cog.moving) {
    return `You're moving to [${cog.moving.to.roomId}], arriving t${cog.moving.arriveTick}.`;
  }
  const witnessedDebate = witnessedDebateLine(input);
  if (witnessedDebate) {
    return `You're in [${locationDisplayName(input)}] witnessing ${witnessedDebate}.`;
  }

  return `You're in [${locationDisplayName(input)}] chilling; available for movement or debate.`;
}

function witnessedDebateLine(input: CogDecisionInput): string | undefined {
  const roomId = input.observation.cog.location?.roomId;
  if (!roomId) {
    return undefined;
  }

  const cogs = visibleCogs(input.observation);
  const cogsById = new Map(cogs.map((cog) => [cog.id, cog]));
  const seenDebates = new Set<string>();

  for (const cog of cogs) {
    const opponentId = cog.debate?.opponentId;
    if (!opponentId || cog.location?.roomId !== roomId) {
      continue;
    }

    const opponent = cogsById.get(opponentId);
    if (!opponent || opponent.location?.roomId !== roomId || opponent.id === input.observation.cog.id) {
      continue;
    }

    const debateKey = [cog.id, opponent.id].sort().join(":");
    if (seenDebates.has(debateKey)) {
      continue;
    }

    seenDebates.add(debateKey);
    return `${cog.name} and ${opponent.name} debate`;
  }

  return undefined;
}

function locationDisplayName(input: CogDecisionInput): string {
  const location = input.observation.cog.location;
  if (!location) {
    const position = input.observation.cog.position;
    return `${position.x},${position.y}`;
  }

  const room = input.observation.venue?.rooms.find((candidate) => candidate.id === location.roomId);
  return room?.label ?? location.roomId;
}

function audienceLine(input: CogDecisionInput): string {
  const cog = input.observation.cog;
  const roomId = cog.location?.roomId;
  const opponentId = cog.debate?.opponentId;
  const audience = visibleCogs(input.observation)
    .filter((entity) => entity.id !== opponentId)
    .filter((entity) => !roomId || entity.location?.roomId === roomId)
    .map((entity) => `${entity.name} (${formatColor(entity.color)} ${certaintyPercent(entity)})`);

  return audience.length > 0 ? audience.join(", ") : "none";
}

function transcriptLines(input: CogDecisionInput): string[] {
  const lines = input.observation.recentEvents.slice(-8).map((event) => `   ${transcriptEventLine(input, event)}`);
  return lines.length > 0 ? lines : ["   No transcript yet."];
}

function transcriptEventLine(input: CogDecisionInput, event: WorldEvent): string {
  if (event.type === "debateStart" && event.actorId === input.observation.cog.id && event.targetId) {
    return `You and ${entityName(input, event.targetId)} start debating`;
  }

  if (event.type === "debateExchange" && event.debate) {
    return debateTranscriptLine(input, event);
  }

  return personalizeEventMessage(input, event);
}

function debateTranscriptLine(input: CogDecisionInput, event: WorldEvent): string {
  const cog = input.observation.cog;
  const self = event.debate?.actions.find((action) => action.cogId === cog.id);
  const opponent = event.debate?.actions.find((action) => action.cogId !== cog.id);
  if (!self || !opponent) {
    return personalizeEventMessage(input, event);
  }

  const opponentName = entityName(input, opponent.cogId);
  const outcome = debateOutcomeFor(cog.id, event);
  const result = outcome === "tie" ? "Tie" : outcome === "you win" ? "You win" : `${opponentName} wins`;
  return `${opponentName}: ${titleCase(opponent.action)}, You: ${titleCase(self.action)} = ${result}.`;
}

function personalizeEventMessage(input: CogDecisionInput, event: WorldEvent): string {
  if (event.actorId !== input.observation.cog.id) {
    return event.message;
  }

  const selfName = input.observation.cog.name;
  if (event.message.startsWith(`${selfName} `)) {
    return `You ${event.message.slice(selfName.length + 1)}`;
  }

  return event.message.replace(selfName, "You");
}

function debateOutcomeFor(cogId: string, event: WorldEvent): string {
  if (!event.debate?.winnerCogId) {
    return "tie";
  }

  return event.debate.winnerCogId === cogId ? "you win" : "you lose";
}

function moveChoices(input: CogDecisionInput): ControllerDecisionChoice[] {
  if (input.allowedRoomIds?.length) {
    return input.allowedRoomIds.map((roomId) => {
      const room = input.observation.venue?.rooms.find((candidate) => candidate.id === roomId);
      return {
        label: `Move to ${room ? `${room.label} (${room.id})` : roomId}`,
        action: { type: "move", roomId },
      };
    });
  }

  if (input.allowedDirections?.length) {
    return input.allowedDirections.map((direction) => ({
      label: `Move ${direction}`,
      action: { type: "move", direction },
    }));
  }

  return DIRECTIONS.map((direction) => ({
    label: `Move ${direction}`,
    action: { type: "move", direction },
  }));
}

function entityName(input: CogDecisionInput, id: string): string {
  if (input.observation.cog.id === id) {
    return input.observation.cog.name;
  }

  return visibleCogs(input.observation).find((entity) => entity.id === id)?.name ?? id;
}

function opponentCertainty(input: CogDecisionInput, id: string): string {
  const entity = visibleCogs(input.observation).find((candidate) => candidate.id === id);
  return entity ? `certainty ${certaintyPercent(entity)}` : "certainty unknown";
}

function entityColor(input: CogDecisionInput, id: string): string {
  const entity = visibleCogs(input.observation).find((candidate) => candidate.id === id);
  return entity ? formatColor(entity.color) : "team unknown";
}

function visibleCogs(observation: CogObservation): Array<Extract<VisibleEntity, { kind: "cog" }>> {
  return observation.visibleEntities.filter(
    (entity): entity is Extract<VisibleEntity, { kind: "cog" }> => entity.kind === "cog",
  );
}

function certaintyPercent(
  cog: Pick<Cog, "color" | "certainty"> | Pick<Extract<VisibleEntity, { kind: "cog" }>, "color" | "certainty">,
): number {
  return Math.max(0, Math.min(CONVERSION_THRESHOLD, Math.round(cog.certainty ?? CONVERSION_THRESHOLD)));
}

function formatColor(color: string): string {
  return titleCase(color);
}

function titleCase(value: string): string {
  return `${value.slice(0, 1).toUpperCase()}${value.slice(1)}`;
}
