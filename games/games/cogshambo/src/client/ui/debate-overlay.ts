import type { Position, WorldEvent, WorldSnapshot } from "../../shared/types";

type SnapshotCog = WorldSnapshot["cogs"][number];

export function debatePairKey(firstId: string, secondId: string): string {
  return [firstId, secondId].sort().join(":");
}

export function settledDebateEventsForOverlay(
  snapshot: Pick<WorldSnapshot, "cogs" | "recentEvents" | "tick">,
  activeDebatePairKeys: ReadonlySet<string>,
): WorldEvent[] {
  const settledEvents: WorldEvent[] = [];
  const displayedPairKeys = new Set(activeDebatePairKeys);

  for (let index = snapshot.recentEvents.length - 1; index >= 0; index -= 1) {
    const event = snapshot.recentEvents[index];
    if (!isVisibleSettledDebateEvent(event, snapshot)) {
      continue;
    }

    const key = debateEventPairKey(event);
    if (!key || displayedPairKeys.has(key)) {
      continue;
    }

    displayedPairKeys.add(key);
    settledEvents.push(event);
  }

  return settledEvents;
}

export function debateBubbleBoardPosition(first: Pick<SnapshotCog, "position">, second: Pick<SnapshotCog, "position">): Position {
  return {
    x: (first.position.x + second.position.x) / 2 + 0.5,
    y: (first.position.y + second.position.y) / 2 + 0.5,
  };
}

function isVisibleSettledDebateEvent(event: WorldEvent, snapshot: Pick<WorldSnapshot, "cogs" | "recentEvents" | "tick">): boolean {
  if (event.type !== "debateExchange" || !event.debate || event.debate.expiresAtTick <= snapshot.tick) {
    return false;
  }

  const participants = debateEventParticipants(event, snapshot.cogs);
  if (!participants) {
    return false;
  }

  const [first, second] = participants;
  return (
    first.color !== second.color &&
    !first.moving &&
    !second.moving &&
    !debateParticipantIsInDifferentActiveDebate(first, second) &&
    debateParticipantsAreStillTogether(first, second) &&
    !hasParticipantConversion(event, snapshot.recentEvents, snapshot.tick)
  );
}

function debateEventPairKey(event: WorldEvent): string | undefined {
  if (!event.debate) {
    return undefined;
  }

  const [firstAction, secondAction] = event.debate.actions;
  return debatePairKey(firstAction.cogId, secondAction.cogId);
}

function hasParticipantConversion(event: WorldEvent, events: WorldEvent[], currentTick: number): boolean {
  if (!event.debate) {
    return false;
  }

  const participantIds = new Set(event.debate.actions.map((action) => action.cogId));
  return events.some(
    (candidate) =>
      candidate.type === "colorChange" &&
      candidate.actorId !== undefined &&
      participantIds.has(candidate.actorId) &&
      candidate.tick >= event.tick &&
      candidate.tick <= currentTick,
  );
}

function debateEventParticipants(event: WorldEvent, cogs: WorldSnapshot["cogs"]): [SnapshotCog, SnapshotCog] | undefined {
  if (!event.debate) {
    return undefined;
  }

  const [firstAction, secondAction] = event.debate.actions;
  const first = cogs.find((cog) => cog.id === firstAction.cogId);
  const second = cogs.find((cog) => cog.id === secondAction.cogId);
  return first && second ? [first, second] : undefined;
}

function debateParticipantIsInDifferentActiveDebate(first: SnapshotCog, second: SnapshotCog): boolean {
  return (
    (first.debate !== undefined && first.debate.opponentId !== second.id) ||
    (second.debate !== undefined && second.debate.opponentId !== first.id)
  );
}

function debateParticipantsAreStillTogether(first: SnapshotCog, second: SnapshotCog): boolean {
  if (first.location || second.location) {
    return first.location?.roomId === second.location?.roomId;
  }

  return Math.abs(first.position.x - second.position.x) + Math.abs(first.position.y - second.position.y) <= 1;
}
