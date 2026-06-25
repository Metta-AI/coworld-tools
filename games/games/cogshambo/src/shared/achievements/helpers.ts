import type { AchievementParameters, Color, Cog, DebateTactic, Trait, VenueRoom, VenueRoomKind, WorldEvent } from "../types.js";
import { TEAM_COLORS, TRAITS } from "../types.js";
import { legacyHalfSecondTicksToSimulationTicks } from "../timing.js";
import type { AchievementCheckContext, AchievementDefinition, AchievementTemplateVariable } from "./types.js";

export const ACHIEVEMENT_POINTS = 10;
export const ACHIEVEMENT_TRAITS = TRAITS satisfies readonly NonNullable<AchievementParameters["trait"]>[];
export const ACHIEVEMENT_TEAMS = TEAM_COLORS;
export const ACHIEVEMENT_TACTICS = ["reason", "spin", "passion"] as const satisfies readonly DebateTactic[];

const TEMPLATE_VARIABLES = [
  { key: "trait", token: "$TRAIT" },
  { key: "team", token: "$TEAM" },
  { key: "room", token: "$ROOM" },
  { key: "tactic", token: "$TACTIC" },
  { key: "rounds", token: "$ROUNDS" },
  { key: "cog", token: "$COG" },
] as const satisfies readonly { key: AchievementTemplateVariable; token: string }[];

export function defineAchievement(definition: AchievementDefinition): AchievementDefinition {
  // Achievement definitions are still authored in the old half-second tick unit.
  return {
    ...definition,
    timeoutTicks: legacyHalfSecondTicksToSimulationTicks(definition.timeoutTicks),
  };
}

export function achievementKey(input: { achievementId?: string; id?: string; parameters?: AchievementParameters }): string {
  const id = input.achievementId ?? input.id;
  const parameterKey = achievementParameterKey(input.parameters);
  return parameterKey ? `${id}?${parameterKey}` : `${id}`;
}

function achievementParameterKey(parameters: AchievementParameters | undefined): string {
  if (!parameters) {
    return "";
  }

  return [
    ["trait", parameters.trait],
    ["team", parameters.team],
    ["roomKind", parameters.roomKind],
    ["tactic", parameters.tactic],
    ["rounds", parameters.rounds],
    ["cogId", parameters.cogId],
  ]
    .flatMap(([key, value]) => (value === undefined ? [] : `${key}=${encodeURIComponent(String(value))}`))
    .join("&");
}

export function formatAchievementText(template: string, parameters?: AchievementParameters): string {
  return template
    .replaceAll("$TRAIT", traitLabel(parameters?.trait))
    .replaceAll("[Trait]", traitLabel(parameters?.trait))
    .replaceAll("$TEAM", teamLabel(parameters?.team))
    .replaceAll("[Team]", teamLabel(parameters?.team))
    .replaceAll("$ROOM", roomKindLabel(parameters?.roomKind))
    .replaceAll("[Room]", roomKindLabel(parameters?.roomKind))
    .replaceAll("$TACTIC", tacticLabel(parameters?.tactic))
    .replaceAll("[Tactic]", tacticLabel(parameters?.tactic))
    .replaceAll("$ROUNDS", roundsLabel(parameters?.rounds))
    .replaceAll("[Rounds]", roundsLabel(parameters?.rounds))
    .replaceAll("$COG", cogLabel(parameters))
    .replaceAll("[Cog]", cogLabel(parameters));
}

export function achievementTemplateVariables(definition: Pick<AchievementDefinition, "name" | "description" | "condition">): readonly AchievementTemplateVariable[] {
  const templateText = `${definition.name}\n${definition.description}\n${definition.condition}`;
  return TEMPLATE_VARIABLES.filter((variable) => templateText.includes(variable.token)).map((variable) => variable.key);
}

export function traitLabel(trait: AchievementParameters["trait"]): string {
  if (!trait) {
    return "[TRAIT]";
  }
  return `${trait[0]?.toUpperCase() ?? ""}${trait.slice(1)}`;
}

export function teamLabel(team: Color | undefined): string {
  if (!team) {
    return "[TEAM]";
  }
  return `${team[0]?.toUpperCase() ?? ""}${team.slice(1)}`;
}

export function roomKindLabel(roomKind: AchievementParameters["roomKind"]): string {
  if (!roomKind) {
    return "[ROOM]";
  }
  return `${roomKind[0]?.toUpperCase() ?? ""}${roomKind.slice(1)}`;
}

export function tacticLabel(tactic: AchievementParameters["tactic"]): string {
  if (!tactic) {
    return "[TACTIC]";
  }
  return `${tactic[0]?.toUpperCase() ?? ""}${tactic.slice(1)}`;
}

export function roundsLabel(rounds: AchievementParameters["rounds"]): string {
  if (!rounds) {
    return "[ROUNDS]";
  }
  return String(rounds);
}

export function cogLabel(parameters: AchievementParameters | undefined): string {
  return parameters?.cogName?.trim() || "[COG]";
}

export function eventsSinceAssigned(context: AchievementCheckContext): WorldEvent[] {
  return context.events.filter(
    (event) => event.tick >= context.assignment.assignedTick && event.tick <= context.tick,
  );
}

export function countEvents(
  context: AchievementCheckContext,
  predicate: (event: WorldEvent) => boolean,
): number {
  return eventsSinceAssigned(context).filter(predicate).length;
}

export function isDebateParticipant(event: WorldEvent, cogId: string): boolean {
  return Boolean(event.debate?.actions.some((action) => action.cogId === cogId));
}

export function debateOpponentIds(context: AchievementCheckContext): Set<string> {
  const opponentIds = new Set<string>();
  for (const event of eventsSinceAssigned(context)) {
    if (event.type !== "debateExchange" || !isDebateParticipant(event, context.cog.id)) {
      continue;
    }
    for (const action of event.debate?.actions ?? []) {
      if (action.cogId !== context.cog.id) {
        opponentIds.add(action.cogId);
      }
    }
  }
  return opponentIds;
}

export function debateWins(
  context: AchievementCheckContext,
  predicate: (event: WorldEvent) => boolean = () => true,
): WorldEvent[] {
  return eventsSinceAssigned(context).filter(
    (event) => event.type === "debateExchange" && event.debate?.winnerCogId === context.cog.id && predicate(event),
  );
}

export function debateLosses(
  context: AchievementCheckContext,
  predicate: (event: WorldEvent) => boolean = () => true,
): WorldEvent[] {
  return eventsSinceAssigned(context).filter((event) => {
    if (event.type !== "debateExchange" || !event.debate || event.debate.winnerCogId === context.cog.id) {
      return false;
    }
    return isDebateParticipant(event, context.cog.id) && predicate(event);
  });
}

export function hasTrait(cog: Cog | undefined, trait: AchievementParameters["trait"]): boolean {
  return Boolean(trait && cog && (cog.activeTrait === trait || cog.defensiveTrait === trait));
}

export function lostToTrait(context: AchievementCheckContext, trait: AchievementParameters["trait"]): boolean {
  if (!trait) {
    return false;
  }
  return debateLosses(context, (event) => hasTrait(winnerCog(context, event), trait)).length > 0;
}

export function winnerCog(context: AchievementCheckContext, event: WorldEvent) {
  const winnerId = event.debate?.winnerCogId;
  return winnerId ? context.snapshot.cogs.find((cog) => cog.id === winnerId) : undefined;
}

export function debateRoom(context: AchievementCheckContext, event: WorldEvent): VenueRoom | undefined {
  const participantIds = event.debate?.actions.map((action) => action.cogId) ?? [];
  const participants = participantIds.flatMap((id) => context.snapshot.cogs.find((cog) => cog.id === id) ?? []);
  const roomId = participants[0]?.location?.roomId;
  if (!roomId || participants.some((cog) => cog.location?.roomId !== roomId)) {
    return undefined;
  }
  return context.snapshot.venue?.rooms.find((room) => room.id === roomId);
}

export function debateRoomKind(context: AchievementCheckContext, event: WorldEvent): VenueRoomKind | undefined {
  return event.debate?.roomKind ?? debateRoom(context, event)?.kind;
}

export function participantIds(event: WorldEvent): string[] {
  return event.debate?.actions.map((action) => action.cogId) ?? [];
}

export function opponentId(event: WorldEvent, cogId: string): string | undefined {
  return participantIds(event).find((id) => id !== cogId);
}

export function opponentCog(context: AchievementCheckContext, event: WorldEvent): Cog | undefined {
  const id = opponentId(event, context.cog.id);
  return id ? context.snapshot.cogs.find((cog) => cog.id === id) : undefined;
}

export function cogTactic(event: WorldEvent, cogId: string): DebateTactic | undefined {
  return event.debate?.actions.find((action) => action.cogId === cogId)?.action;
}

export function tacticBeats(tactic: DebateTactic | undefined, opponentTactic: DebateTactic | undefined): boolean {
  return (
    (tactic === "reason" && opponentTactic === "spin") ||
    (tactic === "spin" && opponentTactic === "passion") ||
    (tactic === "passion" && opponentTactic === "reason")
  );
}

export function debatePairKey(event: WorldEvent): string | undefined {
  const ids = participantIds(event).sort();
  return ids.length === 2 ? ids.join("__") : undefined;
}

export function debateEventsForCog(events: readonly WorldEvent[], cogId: string): WorldEvent[] {
  return events
    .filter((event) => event.type === "debateExchange" && isDebateParticipant(event, cogId))
    .sort((a, b) => a.tick - b.tick);
}

export function hasDrawBreaker(events: readonly WorldEvent[], cogId: string): boolean {
  const previousByPair = new Map<string, WorldEvent>();
  for (const event of debateEventsForCog(events, cogId)) {
    const key = debatePairKey(event);
    if (!key) {
      continue;
    }
    if (previousByPair.get(key)?.debate?.outcome === "draw" && event.debate?.winnerCogId === cogId) {
      return true;
    }
    previousByPair.set(key, event);
  }
  return false;
}

export function hasDenySweep(events: readonly WorldEvent[], cogId: string): boolean {
  const sessions = new Map<string, { decisiveRounds: number; openingLosses: number }>();
  for (const event of debateEventsForCog(events, cogId)) {
    const key = debatePairKey(event);
    const winnerId = event.debate?.winnerCogId;
    if (!key || !winnerId) {
      continue;
    }

    const session = sessions.get(key) ?? { decisiveRounds: 0, openingLosses: 0 };
    const won = winnerId === cogId;
    if (won && session.decisiveRounds >= 2 && session.openingLosses >= 2) {
      return true;
    }
    if (!won && session.decisiveRounds < 2) {
      session.openingLosses += 1;
    }
    session.decisiveRounds += 1;
    sessions.set(key, session);
  }
  return false;
}

export function hasWinFromBehind(events: readonly WorldEvent[], cogId: string): boolean {
  const sessions = new Map<string, { wins: number; losses: number; wasBehind: boolean }>();
  for (const event of debateEventsForCog(events, cogId)) {
    const key = debatePairKey(event);
    const winnerId = event.debate?.winnerCogId;
    if (!key || !winnerId) {
      continue;
    }

    const session = sessions.get(key) ?? { wins: 0, losses: 0, wasBehind: false };
    if (winnerId === cogId) {
      session.wins += 1;
      if (session.wasBehind && session.wins >= 3 && session.wins > session.losses) {
        return true;
      }
    } else {
      session.losses += 1;
      session.wasBehind = session.wasBehind || session.losses > session.wins;
    }
    sessions.set(key, session);
  }
  return false;
}

export function hasCounterComeback(events: readonly WorldEvent[], cogId: string): boolean {
  const previousByPair = new Map<string, WorldEvent>();
  for (const event of debateEventsForCog(events, cogId)) {
    const key = debatePairKey(event);
    if (!key) {
      continue;
    }
    const opponent = opponentId(event, cogId);
    const previous = previousByPair.get(key);
    if (
      previous?.debate?.winnerCogId &&
      previous.debate.winnerCogId !== cogId &&
      event.debate?.winnerCogId === cogId &&
      tacticBeats(cogTactic(event, cogId), opponent ? cogTactic(event, opponent) : undefined)
    ) {
      return true;
    }
    previousByPair.set(key, event);
  }
  return false;
}

export function hasRoomComeback(
  events: readonly WorldEvent[],
  cogId: string,
  roomKind: AchievementParameters["roomKind"],
  roomKindForEvent: (event: WorldEvent) => AchievementParameters["roomKind"],
): boolean {
  if (!roomKind) {
    return false;
  }

  let sawLoss = false;
  for (const event of debateEventsForCog(events, cogId)) {
    if (roomKindForEvent(event) !== roomKind) {
      continue;
    }
    if (event.debate?.winnerCogId === cogId && sawLoss) {
      return true;
    }
    if (event.debate?.winnerCogId && event.debate.winnerCogId !== cogId) {
      sawLoss = true;
    }
  }
  return false;
}

export function convertedOpponentsAfterDebate(events: readonly WorldEvent[], cogId: string): Set<string> {
  const convertedOpponents = new Set<string>();
  for (const event of debateEventsForCog(events, cogId)) {
    const opponent = opponentId(event, cogId);
    if (
      opponent &&
      events.some((candidate) => candidate.type === "colorChange" && candidate.actorId === opponent && candidate.tick >= event.tick)
    ) {
      convertedOpponents.add(opponent);
    }
  }
  return convertedOpponents;
}

export function convertedDebatersFromWitnessedDebates(events: readonly WorldEvent[], cogId: string): Set<string> {
  const convertedDebaters = new Set<string>();
  for (const event of events) {
    if (event.type !== "debateExchange" || !event.debate?.witnessCogIds?.includes(cogId)) {
      continue;
    }
    const debaterIds = new Set(participantIds(event));
    for (const candidate of events) {
      if (candidate.type === "colorChange" && candidate.actorId && candidate.tick >= event.tick && debaterIds.has(candidate.actorId)) {
        convertedDebaters.add(candidate.actorId);
      }
    }
  }
  return convertedDebaters;
}

export function witnessedWins(
  context: AchievementCheckContext,
  predicate: (event: WorldEvent) => boolean,
): WorldEvent[] {
  return eventsSinceAssigned(context).filter((event) => {
    if (event.type !== "debateExchange" || !event.debate?.witnessCogIds?.includes(context.cog.id)) {
      return false;
    }
    return predicate(event);
  });
}
