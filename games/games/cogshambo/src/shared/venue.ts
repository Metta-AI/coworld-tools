import type { Position, VenueLayout, VenueRect, VenueRoom, VenueRoomPath, VenueSpot, VenueSpotRole, WorldDimensions } from "./types.js";

export type VenueSection = "west" | "center" | "east";

export function assignVenueSpotsToNearestRooms(
  rooms: VenueRoom[],
  spots: VenueSpot[],
): { rooms: VenueRoom[]; spots: VenueSpot[] } {
  if (rooms.length === 0) {
    return {
      rooms: [],
      spots: spots.map((spot) => ({ ...spot, position: { ...spot.position } })),
    };
  }

  const assignedSpots = spots.map((spot) => ({
    ...spot,
    position: { ...spot.position },
    roomId: nearestVenueRoomId(spot.position, rooms),
  }));
  const spotIdsByRoom = new Map(rooms.map((room) => [room.id, [] as string[]] as const));
  assignedSpots.forEach((spot) => {
    spotIdsByRoom.get(spot.roomId)?.push(spot.id);
  });

  return {
    rooms: rooms.map((room) => ({
      ...room,
      rect: room.rect ? { ...room.rect } : undefined,
      position: room.position ? { ...room.position } : undefined,
      spotIds: spotIdsByRoom.get(room.id) ?? [],
      neighborIds: [...room.neighborIds],
    })),
    spots: assignedSpots,
  };
}

export function venueRoomRect(room: VenueRoom, spots: VenueSpot[]): VenueRect {
  if (room.rect) {
    return { ...room.rect };
  }

  const roomSpots = spots.filter((spot) => spot.roomId === room.id || room.spotIds.includes(spot.id));
  if (roomSpots.length === 0) {
    return {
      x: room.position?.x ?? 0,
      y: room.position?.y ?? 0,
      width: 4,
      height: 3,
    };
  }

  const xs = roomSpots.map((spot) => spot.position.x);
  const ys = roomSpots.map((spot) => spot.position.y);
  const padding = 1.2;
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);

  return {
    x: minX - padding,
    y: minY - padding,
    width: Math.max(3.2, maxX - minX + padding * 2),
    height: Math.max(2.8, maxY - minY + padding * 2),
  };
}

export function normalizeVenueRoomPath(
  firstRoomId: string,
  secondRoomId: string,
  points: Position[] = [],
): VenueRoomPath {
  const [fromRoomId, toRoomId] = [firstRoomId, secondRoomId].sort();
  return {
    id: `${fromRoomId}__${toRoomId}`,
    fromRoomId,
    toRoomId,
    points: points.map(clonePosition),
  };
}

export function venueRoomPathsFromNeighbors(rooms: VenueRoom[]): VenueRoomPath[] {
  const roomIds = new Set(rooms.map((room) => room.id));
  const paths = new Map<string, VenueRoomPath>();
  rooms.forEach((room) => {
    room.neighborIds.forEach((neighborId) => {
      if (!roomIds.has(neighborId)) {
        return;
      }

      const path = normalizeVenueRoomPath(room.id, neighborId);
      paths.set(path.id, path);
    });
  });
  return [...paths.values()].sort((left, right) => left.id.localeCompare(right.id));
}

export function syncVenueRoomNeighborsFromPaths(rooms: VenueRoom[], paths: VenueRoomPath[]): VenueRoom[] {
  const neighbors = new Map(rooms.map((room) => [room.id, new Set<string>()] as const));
  paths.forEach((path) => {
    if (!neighbors.has(path.fromRoomId) || !neighbors.has(path.toRoomId) || path.fromRoomId === path.toRoomId) {
      return;
    }

    neighbors.get(path.fromRoomId)?.add(path.toRoomId);
    neighbors.get(path.toRoomId)?.add(path.fromRoomId);
  });

  return rooms.map((room) => ({
    ...room,
    neighborIds: [...(neighbors.get(room.id) ?? new Set<string>())].sort(),
  }));
}

export function venueRoomSection(roomId: string, dimensions: WorldDimensions, venue: VenueLayout): VenueSection | undefined {
  const room = venue.rooms.find((candidate) => candidate.id === roomId);
  if (!room) {
    return undefined;
  }

  return venueSectionForX(venueRoomCenterX(room, venue.spots), dimensions);
}

export function venueSpotRole(spot: Pick<VenueSpot, "role">): VenueSpotRole {
  return spot.role ?? "speaker";
}

export function venueSpotIsSpeaker(spot: Pick<VenueSpot, "role"> | undefined): boolean {
  return Boolean(spot && venueSpotRole(spot) === "speaker");
}

export function venueSectionForX(x: number, dimensions: WorldDimensions): VenueSection {
  const width = Math.max(1, dimensions.width);
  if (x < width / 3) {
    return "west";
  }
  if (x < (width * 2) / 3) {
    return "center";
  }
  return "east";
}

function venueRoomCenterX(room: VenueRoom, spots: VenueSpot[]): number {
  const roomSpots = spots.filter((spot) => spot.roomId === room.id || room.spotIds.includes(spot.id));
  if (roomSpots.length > 0) {
    return roomSpots.reduce((sum, spot) => sum + spot.position.x, 0) / roomSpots.length;
  }

  if (room.rect) {
    return room.rect.x + room.rect.width / 2;
  }

  return room.position?.x ?? 0;
}

function nearestVenueRoomId(position: Position, rooms: VenueRoom[]): string {
  const [nearest] = rooms
    .map((room) => {
      const rect = room.rect ?? {
        x: room.position?.x ?? 0,
        y: room.position?.y ?? 0,
        width: 0,
        height: 0,
      };
      return {
        roomId: room.id,
        rectDistance: squaredDistanceToRect(position, rect),
        centerDistance: squaredDistance(position, {
          x: rect.x + rect.width / 2,
          y: rect.y + rect.height / 2,
        }),
      };
    })
    .sort((left, right) =>
      left.rectDistance - right.rectDistance
      || left.centerDistance - right.centerDistance
      || left.roomId.localeCompare(right.roomId)
    );

  return nearest.roomId;
}

function squaredDistanceToRect(position: Position, rect: VenueRect): number {
  const dx = position.x < rect.x ? rect.x - position.x : Math.max(0, position.x - (rect.x + rect.width));
  const dy = position.y < rect.y ? rect.y - position.y : Math.max(0, position.y - (rect.y + rect.height));
  return dx * dx + dy * dy;
}

function squaredDistance(left: Position, right: Position): number {
  const dx = left.x - right.x;
  const dy = left.y - right.y;
  return dx * dx + dy * dy;
}

function clonePosition(position: Position): Position {
  return { ...position };
}
