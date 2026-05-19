import type {
  Cog,
  CogObservation,
  Position,
  TerrainCell,
  VisibleEntity,
  WorldObject,
  WorldSnapshot,
} from "../../shared/types.js";

export const COG_SIGHT_RADIUS = 5;

export function squaredDistance(a: Position, b: Position): number {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  return dx * dx + dy * dy;
}

export function isInsideRadius(origin: Position, target: Position, radius: number): boolean {
  return squaredDistance(origin, target) <= radius * radius;
}

export function visibleCells(origin: Position, width: number, height: number, radius = COG_SIGHT_RADIUS): Position[] {
  const cells: Position[] = [];

  for (let y = Math.max(0, origin.y - radius); y <= Math.min(height - 1, origin.y + radius); y += 1) {
    for (let x = Math.max(0, origin.x - radius); x <= Math.min(width - 1, origin.x + radius); x += 1) {
      const position = { x, y };
      if (isInsideRadius(origin, position, radius)) {
        cells.push(position);
      }
    }
  }

  return cells;
}

export function createObservation(cog: Cog, snapshot: WorldSnapshot): CogObservation {
  const visibleRoomIds = visibleVenueRoomIds(cog, snapshot);
  const canSeePosition = (position: Position): boolean => {
    if (!visibleRoomIds) {
      return isInsideRadius(cog.position, position, COG_SIGHT_RADIUS);
    }

    return (
      snapshot.venue?.spots.some(
        (spot) => typeof spot.roomId === "string" && visibleRoomIds.has(spot.roomId) && samePosition(spot.position, position),
      ) ?? false
    );
  };
  const canSeeCog = (candidate: Cog): boolean => {
    if (!visibleRoomIds) {
      return isInsideRadius(cog.position, candidate.position, COG_SIGHT_RADIUS);
    }

    return candidate.location ? visibleRoomIds.has(candidate.location.roomId) : canSeePosition(candidate.position);
  };
  const visibleEntities: VisibleEntity[] = [
    ...snapshot.cogs
      .filter((candidate) => candidate.id !== cog.id)
      .filter((candidate) => canSeeCog(candidate))
      .map((candidate) => ({
        kind: "cog" as const,
        id: candidate.id,
        name: candidate.name,
        position: candidate.position,
        location: candidate.location,
        color: candidate.color,
        certainty: candidate.certainty,
        activity: candidate.activity,
        debate: candidate.debate,
        moving: candidate.moving,
        spriteSheetKey: candidate.spriteSheetKey,
        spriteUrl: candidate.spriteUrl,
        spriteUrls: candidate.spriteUrls,
      })),
    ...snapshot.objects
      .filter((object) => canSeePosition(object.position))
      .map((object) => objectToVisibleEntity(object)),
  ];

  const visibleTerrain = visibleRoomIds ? [] : snapshot.terrain.filter((cell) => canSeePosition(cell.position));

  const recentEvents = snapshot.recentEvents.filter((event) => isEventRelevantToCog(event, cog.id));

  return {
    cog,
    dimensions: snapshot.dimensions,
    venue: snapshot.venue,
    visibleEntities,
    visibleTerrain: visibleTerrain.map((cell) => cloneTerrainCell(cell)),
    visibleCells: visibleRoomIds
      ? snapshot.venue?.spots
          .filter((spot) => typeof spot.roomId === "string" && visibleRoomIds.has(spot.roomId))
          .map((spot) => ({ ...spot.position })) ?? []
      : visibleCells(cog.position, snapshot.dimensions.width, snapshot.dimensions.height),
    recentEvents,
  };
}

function isEventRelevantToCog(event: WorldSnapshot["recentEvents"][number], cogId: string): boolean {
  return (
    event.actorId === cogId ||
    event.targetId === cogId ||
    event.debate?.winnerCogId === cogId ||
    event.debate?.actions.some((action) => action.cogId === cogId) === true
  );
}

function visibleVenueRoomIds(cog: Cog, snapshot: WorldSnapshot): Set<string> | undefined {
  if (!snapshot.venue || !cog.location) {
    return undefined;
  }

  const room = snapshot.venue.rooms.find((candidate) => candidate.id === cog.location?.roomId);
  if (!room) {
    return undefined;
  }

  return new Set([room.id, ...room.neighborIds]);
}

function samePosition(a: Position, b: Position): boolean {
  return a.x === b.x && a.y === b.y;
}

function objectToVisibleEntity(object: WorldObject): VisibleEntity {
  return {
    kind: "object",
    id: object.id,
    objectType: object.type,
    position: object.position,
    spriteKey: object.spriteKey,
  };
}

function cloneTerrainCell(cell: TerrainCell): TerrainCell {
  return {
    position: { ...cell.position },
    terrain: cell.terrain,
  };
}
