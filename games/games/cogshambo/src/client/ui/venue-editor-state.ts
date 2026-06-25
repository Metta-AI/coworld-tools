import type {
  Position,
  VenueEditorState,
  VenueRect,
  VenueRoom,
  VenueRoomPath,
  VenueSpot,
  VenueSpotLink,
} from "../../shared/types";
import {
  normalizeVenueRoomPath,
  syncVenueRoomNeighborsFromPaths,
  venueRoomRect,
} from "../../shared/venue";

export type VenueEditorDraft = Omit<VenueEditorState, "updatedAt">;

export type VenueEditorClipboard = {
  spots: VenueSpot[];
  links: VenueSpotLink[];
};

const DEFAULT_NEW_ROOM_SPEAKER_SLOTS = 3;

export function selectSpot(
  selectedSpotIds: ReadonlySet<string>,
  spotId: string,
  options: { additive: boolean },
): Set<string> {
  if (!options.additive) {
    return new Set([spotId]);
  }

  const next = new Set(selectedSpotIds);
  if (next.has(spotId)) {
    next.delete(spotId);
  } else {
    next.add(spotId);
  }
  return next;
}

export function toggleSelectedSpotRoles(
  draft: VenueEditorDraft,
  selectedSpotIds: ReadonlySet<string>,
): VenueEditorDraft {
  if (selectedSpotIds.size === 0) {
    return draft;
  }

  return {
    ...draft,
    spots: draft.spots.map((spot) => {
      if (!selectedSpotIds.has(spot.id)) {
        return spot;
      }

      return {
        ...spot,
        role: (spot.role ?? "speaker") === "speaker" ? "audience" : "speaker",
      };
    }),
  };
}

export function copySelectedSpots(
  draft: VenueEditorDraft,
  selectedSpotIds: ReadonlySet<string>,
): VenueEditorClipboard {
  const spots = draft.spots.filter((spot) => selectedSpotIds.has(spot.id));

  return {
    spots: spots.map(cloneSpot),
    links: [],
  };
}

export function pasteCopiedSpots(
  draft: VenueEditorDraft,
  clipboard: VenueEditorClipboard,
  offset: Position,
): { draft: VenueEditorDraft; selectedSpotIds: Set<string> } {
  const existingIds = new Set(draft.spots.map((spot) => spot.id));
  const pastedSpots = clipboard.spots.map((spot) => {
    const id = nextCopyId(spot.id, existingIds);
    existingIds.add(id);
    return {
      ...cloneSpot(spot),
      id,
      label: id,
      position: {
        x: spot.position.x + offset.x,
        y: spot.position.y + offset.y,
      },
    };
  });

  return {
    draft: {
      ...draft,
      spots: [...draft.spots, ...pastedSpots],
      links: [],
      rooms: appendRoomSpotIds(draft.rooms, pastedSpots),
    },
    selectedSpotIds: new Set(pastedSpots.map((spot) => spot.id)),
  };
}

export function pasteCopiedSpotsIntoRoom(
  draft: VenueEditorDraft,
  clipboard: VenueEditorClipboard,
  roomId: string,
  offset: Position,
): { draft: VenueEditorDraft; selectedSpotIds: Set<string> } {
  if (!draft.rooms.some((room) => room.id === roomId)) {
    return { draft, selectedSpotIds: new Set() };
  }

  const roomClipboard: VenueEditorClipboard = {
    spots: clipboard.spots.map((spot) => ({ ...cloneSpot(spot), roomId })),
    links: [],
  };
  return pasteCopiedSpots(draft, roomClipboard, offset);
}

export function moveSelectedSpots(
  draft: VenueEditorDraft,
  selectedSpotIds: ReadonlySet<string>,
  delta: Position,
): VenueEditorDraft {
  if (selectedSpotIds.size === 0 || (delta.x === 0 && delta.y === 0)) {
    return draft;
  }

  return {
    ...draft,
    spots: draft.spots.map((spot) =>
      selectedSpotIds.has(spot.id)
        ? {
            ...spot,
            position: {
              x: spot.position.x + delta.x,
              y: spot.position.y + delta.y,
            },
          }
        : spot,
    ),
  };
}

export function moveRoomNode(draft: VenueEditorDraft, roomId: string, position: Position): VenueEditorDraft {
  if (!draft.rooms.some((room) => room.id === roomId)) {
    return draft;
  }

  return {
    ...draft,
    rooms: draft.rooms.map((room) =>
      room.id === roomId
        ? {
            ...room,
            position: { ...position },
          }
        : room,
    ),
  };
}

export function moveRoomRect(draft: VenueEditorDraft, roomId: string, position: Position): VenueEditorDraft {
  const room = draft.rooms.find((candidate) => candidate.id === roomId);
  if (!room) {
    return draft;
  }

  const rect = roomRect(room, draft);
  return {
    ...draft,
    rooms: draft.rooms.map((candidate) =>
      candidate.id === roomId
        ? {
            ...candidate,
            rect: {
              ...rect,
              x: position.x,
              y: position.y,
            },
          }
        : candidate,
    ),
  };
}

export function resizeRoomRect(
  draft: VenueEditorDraft,
  roomId: string,
  size: Pick<VenueRect, "width" | "height">,
): VenueEditorDraft {
  const room = draft.rooms.find((candidate) => candidate.id === roomId);
  if (!room) {
    return draft;
  }

  const rect = roomRect(room, draft);
  return {
    ...draft,
    rooms: draft.rooms.map((candidate) =>
      candidate.id === roomId
        ? {
            ...candidate,
            rect: {
              ...rect,
              width: Math.max(1, size.width),
              height: Math.max(1, size.height),
            },
          }
        : candidate,
    ),
  };
}

export function createRoom(
  draft: VenueEditorDraft,
  options: { center?: Position } = {},
): { draft: VenueEditorDraft; room: VenueRoom } {
  const id = nextRoomId(draft.rooms);
  const baseRoom: VenueRoom = {
    id,
    label: roomLabelFromId(id),
    kind: "lounge",
    rect: options.center ? roomRectCenteredAt(draft, options.center) : defaultRoomRect(draft),
    spotIds: [],
    neighborIds: [],
  };
  const speakerSpots = defaultSpeakerSpotsForRoom(draft, baseRoom, DEFAULT_NEW_ROOM_SPEAKER_SLOTS);
  const roomWithSpots = {
    ...baseRoom,
    spotIds: speakerSpots.map((spot) => spot.id),
  };
  const connectedRoomIds = closestRoomIds(draft, roomWithSpots, 4);
  const newPaths = connectedRoomIds
    .map((roomId) => normalizeRoomPath(roomWithSpots.id, roomId))
    .sort((left, right) => left.id.localeCompare(right.id));
  const draftWithRoom = syncRoomNeighborsFromPaths({
    ...draft,
    rooms: [...draft.rooms, roomWithSpots],
    spots: [...draft.spots, ...speakerSpots],
    paths: [...draft.paths, ...newPaths],
  });
  const room = draftWithRoom.rooms.find((candidate) => candidate.id === roomWithSpots.id) ?? roomWithSpots;

  return {
    draft: draftWithRoom,
    room,
  };
}

export function upsertRoomPath(
  draft: VenueEditorDraft,
  firstRoomId: string,
  secondRoomId: string,
  points: Position[] = [],
): VenueEditorDraft {
  if (firstRoomId === secondRoomId || !hasRoom(draft, firstRoomId) || !hasRoom(draft, secondRoomId)) {
    return draft;
  }

  const path = normalizeRoomPath(firstRoomId, secondRoomId, points);
  const paths = [
    ...draft.paths.filter((candidate) => candidate.id !== path.id),
    path,
  ].sort((left, right) => left.id.localeCompare(right.id));

  return syncRoomNeighborsFromPaths({
    ...draft,
    paths,
  });
}

export function addRoomPathPoint(draft: VenueEditorDraft, pathId: string, point: Position): VenueEditorDraft {
  if (!draft.paths.some((path) => path.id === pathId)) {
    return draft;
  }

  return {
    ...draft,
    paths: draft.paths.map((path) =>
      path.id === pathId
        ? {
            ...path,
            points: [...path.points.map(clonePosition), clonePosition(point)],
          }
        : path,
    ),
  };
}

export function deleteRoomPath(draft: VenueEditorDraft, pathId: string): VenueEditorDraft {
  if (!draft.paths.some((path) => path.id === pathId)) {
    return draft;
  }

  return syncRoomNeighborsFromPaths({
    ...draft,
    paths: draft.paths.filter((path) => path.id !== pathId),
  });
}

export function moveRoomPathPoint(
  draft: VenueEditorDraft,
  pathId: string,
  pointIndex: number,
  position: Position,
): VenueEditorDraft {
  return {
    ...draft,
    paths: draft.paths.map((path) => {
      if (path.id !== pathId || pointIndex < 0 || pointIndex >= path.points.length) {
        return path;
      }

      return {
        ...path,
        points: path.points.map((point, index) => index === pointIndex ? clonePosition(position) : clonePosition(point)),
      };
    }),
  };
}

export function deleteRoomPathPoint(
  draft: VenueEditorDraft,
  pathId: string,
  pointIndex: number,
): VenueEditorDraft {
  return {
    ...draft,
    paths: draft.paths.map((path) => {
      if (path.id !== pathId || pointIndex < 0 || pointIndex >= path.points.length) {
        return path;
      }

      return {
        ...path,
        points: path.points
          .filter((_, index) => index !== pointIndex)
          .map(clonePosition),
      };
    }),
  };
}

export function normalizeRoomPath(firstRoomId: string, secondRoomId: string, points: Position[] = []): VenueRoomPath {
  return normalizeVenueRoomPath(firstRoomId, secondRoomId, points);
}

export function assignSelectedSpotsToRoom(
  draft: VenueEditorDraft,
  selectedSpotIds: ReadonlySet<string>,
  roomId: string,
): VenueEditorDraft {
  if (selectedSpotIds.size === 0 || !draft.rooms.some((room) => room.id === roomId)) {
    return draft;
  }

  const selectedIds = new Set(selectedSpotIds);
  const updatedSpots = draft.spots.map((spot) => selectedIds.has(spot.id) ? { ...spot, roomId } : spot);

  return {
    ...draft,
    rooms: draft.rooms.map((room) => {
      const retainedSpotIds = room.spotIds.filter((spotId) => room.id === roomId || !selectedIds.has(spotId));
      if (room.id !== roomId) {
        return { ...room, spotIds: retainedSpotIds };
      }

      const retainedIds = new Set(retainedSpotIds);
      return {
        ...room,
        spotIds: [
          ...retainedSpotIds,
          ...updatedSpots
            .filter((spot) => selectedIds.has(spot.id) && !retainedIds.has(spot.id))
            .map((spot) => spot.id),
        ],
      };
    }),
    spots: updatedSpots,
  };
}

export function toggleSpotRoomAssignment(draft: VenueEditorDraft, spotId: string, roomId: string): VenueEditorDraft {
  const spot = draft.spots.find((candidate) => candidate.id === spotId);
  if (!spot || !draft.rooms.some((room) => room.id === roomId)) {
    return draft;
  }

  const assigning = spot.roomId !== roomId;
  if (!assigning) {
    return draft;
  }

  return {
    ...draft,
    rooms: draft.rooms.map((room) => {
      const spotIds = room.spotIds.filter((candidate) => candidate !== spotId);
      return room.id === roomId
        ? {
            ...room,
            spotIds: [...spotIds, spotId],
          }
        : {
            ...room,
            spotIds,
          };
    }),
    spots: draft.spots.map((candidate) => {
      if (candidate.id !== spotId) {
        return candidate;
      }

      return {
        ...candidate,
        roomId,
      };
    }),
  };
}

export function roomRect(room: VenueRoom, draft: VenueEditorDraft): VenueRect {
  return venueRoomRect(room, draft.spots);
}

function cloneSpot(spot: VenueSpot): VenueSpot {
  return {
    ...spot,
    position: { ...spot.position },
  };
}

function clonePosition(position: Position): Position {
  return { ...position };
}

function hasRoom(draft: VenueEditorDraft, roomId: string): boolean {
  return draft.rooms.some((room) => room.id === roomId);
}

function appendRoomSpotIds(rooms: VenueRoom[], spots: VenueSpot[]): VenueRoom[] {
  const spotIdsByRoom = new Map<string, string[]>();
  spots.forEach((spot) => {
    spotIdsByRoom.set(spot.roomId, [...(spotIdsByRoom.get(spot.roomId) ?? []), spot.id]);
  });

  if (spotIdsByRoom.size === 0) {
    return rooms;
  }

  return rooms.map((room) => {
    const newSpotIds = spotIdsByRoom.get(room.id) ?? [];
    if (newSpotIds.length === 0) {
      return room;
    }

    const seen = new Set(room.spotIds);
    return {
      ...room,
      spotIds: [
        ...room.spotIds,
        ...newSpotIds.filter((spotId) => {
          if (seen.has(spotId)) {
            return false;
          }
          seen.add(spotId);
          return true;
        }),
      ],
    };
  });
}

function nextRoomId(rooms: VenueRoom[]): string {
  const existingRoomIds = new Set(rooms.map((room) => room.id));
  let index = 1;
  let candidate = "new_room";
  while (existingRoomIds.has(candidate)) {
    index += 1;
    candidate = `new_room_${index}`;
  }
  return candidate;
}

function roomLabelFromId(roomId: string): string {
  const match = /^new_room_(\d+)$/.exec(roomId);
  return match ? `New Room ${match[1]}` : "New Room";
}

function defaultRoomRect(draft: VenueEditorDraft): VenueRect {
  const width = Math.min(8, draft.dimensions.width);
  const height = Math.min(5, draft.dimensions.height);
  const maxX = Math.max(0, draft.dimensions.width - width);
  const maxY = Math.max(0, draft.dimensions.height - height);
  const existingRects = draft.rooms.map((room) => roomRect(room, draft));

  for (let y = 1; y <= maxY; y += 2) {
    for (let x = 1; x <= maxX; x += 2) {
      const rect = { x, y, width, height };
      if (!existingRects.some((existingRect) => rectsOverlap(rect, existingRect))) {
        return rect;
      }
    }
  }

  const offset = draft.rooms.length % 6;
  return {
    x: clampNumber(Math.round(maxX / 2) + offset, 0, maxX),
    y: clampNumber(Math.round(maxY / 2) + offset, 0, maxY),
    width,
    height,
  };
}

function roomRectCenteredAt(draft: VenueEditorDraft, center: Position): VenueRect {
  const width = Math.min(8, draft.dimensions.width);
  const height = Math.min(5, draft.dimensions.height);
  const maxX = Math.max(0, draft.dimensions.width - width);
  const maxY = Math.max(0, draft.dimensions.height - height);

  return {
    x: clampNumber(roundToTenth(center.x - width / 2), 0, maxX),
    y: clampNumber(roundToTenth(center.y - height / 2), 0, maxY),
    width,
    height,
  };
}

function defaultSpeakerSpotsForRoom(draft: VenueEditorDraft, room: VenueRoom, count: number): VenueSpot[] {
  const rect = roomRect(room, { ...draft, rooms: [...draft.rooms, room] });
  const existingSpotIds = new Set(draft.spots.map((spot) => spot.id));
  return Array.from({ length: count }, (_, index) => {
    const id = nextRoomSpotId(room.id, existingSpotIds);
    existingSpotIds.add(id);
    return {
      id,
      roomId: room.id,
      label: id,
      role: "speaker",
      position: {
        x: clampNumber(roundToTenth(rect.x + rect.width * ((index + 1) / (count + 1))), 0, draft.dimensions.width - 1),
        y: clampNumber(roundToTenth(rect.y + rect.height / 2), 0, draft.dimensions.height - 1),
      },
    };
  });
}

function nextRoomSpotId(roomId: string, existingSpotIds: Set<string>): string {
  const roomSlug = roomId
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "") || "room";
  let index = 1;
  let candidate = `${roomSlug}_spot_${index}`;
  while (existingSpotIds.has(candidate)) {
    index += 1;
    candidate = `${roomSlug}_spot_${index}`;
  }
  return candidate;
}

function closestRoomIds(draft: VenueEditorDraft, room: VenueRoom, limit: number): string[] {
  const rect = roomRect(room, { ...draft, rooms: [...draft.rooms, room] });
  const center = rectCenter(rect);
  return draft.rooms
    .map((candidate) => {
      const candidateRect = roomRect(candidate, draft);
      return {
        roomId: candidate.id,
        rectDistance: squaredRectDistance(rect, candidateRect),
        centerDistance: squaredDistance(center, rectCenter(candidateRect)),
      };
    })
    .sort((left, right) =>
      left.rectDistance - right.rectDistance
      || left.centerDistance - right.centerDistance
      || left.roomId.localeCompare(right.roomId)
    )
    .slice(0, limit)
    .map((candidate) => candidate.roomId);
}

function rectCenter(rect: VenueRect): Position {
  return {
    x: rect.x + rect.width / 2,
    y: rect.y + rect.height / 2,
  };
}

function squaredDistance(first: Position, second: Position): number {
  const dx = first.x - second.x;
  const dy = first.y - second.y;
  return dx * dx + dy * dy;
}

function squaredRectDistance(first: VenueRect, second: VenueRect): number {
  const dx = first.x + first.width < second.x
    ? second.x - (first.x + first.width)
    : Math.max(0, first.x - (second.x + second.width));
  const dy = first.y + first.height < second.y
    ? second.y - (first.y + first.height)
    : Math.max(0, first.y - (second.y + second.height));
  return dx * dx + dy * dy;
}

function rectsOverlap(first: VenueRect, second: VenueRect): boolean {
  return (
    first.x < second.x + second.width &&
    first.x + first.width > second.x &&
    first.y < second.y + second.height &&
    first.y + first.height > second.y
  );
}

function clampNumber(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum);
}

function roundToTenth(value: number): number {
  return Math.round(value * 10) / 10;
}

function syncRoomNeighborsFromPaths(draft: VenueEditorDraft): VenueEditorDraft {
  return {
    ...draft,
    rooms: syncVenueRoomNeighborsFromPaths(draft.rooms, draft.paths),
  };
}

function nextCopyId(sourceId: string, existingIds: ReadonlySet<string>): string {
  let index = 1;
  let candidate = `${sourceId}_copy_${index}`;
  while (existingIds.has(candidate)) {
    index += 1;
    candidate = `${sourceId}_copy_${index}`;
  }
  return candidate;
}
