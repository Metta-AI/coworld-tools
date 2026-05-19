import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { venueEditorStateSchema } from "../shared/protocol.js";
import type { VenueEditorState, VenueLayout } from "../shared/types.js";
import { assignVenueSpotsToNearestRooms, syncVenueRoomNeighborsFromPaths, venueRoomRect } from "../shared/venue.js";

export const VENUE_EDITOR_IMAGE_URL = "/assets/cogshambo/venue/gray-area-floor-plan.png";

type VenueEditorStateInput = Omit<VenueEditorState, "updatedAt">;
type NormalizeVenueEditorStateOptions = {
  assignSpotsToNearestRooms?: boolean;
  deriveRoomRects?: boolean;
};

export function defaultVenueGraphPath(): string {
  return path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../public/assets/cogshambo/venue/venue-graph.json");
}

export function readDefaultVenueGraphFile(options: NormalizeVenueEditorStateOptions = {}): VenueEditorState {
  return readVenueGraphFile(defaultVenueGraphPath(), undefined, options);
}

export function readVenueGraphFile(
  filePath = defaultVenueGraphPath(),
  seed?: () => VenueEditorStateInput,
  options: NormalizeVenueEditorStateOptions = {},
): VenueEditorState {
  if (!existsSync(filePath)) {
    if (seed) {
      return normalizeVenueEditorState(seed(), undefined, undefined, options);
    }
    throw new Error(`Venue graph JSON file not found: ${filePath}`);
  }

  const parsedJson = JSON.parse(readFileSync(filePath, "utf8")) as unknown;
  const parsed = venueEditorStateSchema.safeParse(parsedJson);
  if (!parsed.success) {
    throw new Error(`Invalid venue graph JSON at ${filePath}: ${parsed.error.message}`);
  }

  return normalizeVenueEditorState(
    parsed.data,
    parsed.data,
    parsed.data.updatedAt ?? statSync(filePath).mtime.toISOString(),
    options,
  );
}

export function writeVenueGraphFile(state: VenueEditorStateInput, filePath = defaultVenueGraphPath()): VenueEditorState {
  const saved = normalizeVenueEditorState(state, state, new Date().toISOString());
  mkdirSync(path.dirname(filePath), { recursive: true });
  writeFileSync(filePath, `${JSON.stringify(saved, null, 2)}\n`);
  return saved;
}

export function venueLayoutFromEditorState(state: Pick<VenueEditorState, "rooms" | "spots" | "paths">): VenueLayout {
  return {
    rooms: syncVenueRoomNeighborsFromPaths(state.rooms, state.paths),
    spots: state.spots,
    spotLinks: [],
    roomPaths: state.paths,
  };
}

export function normalizeVenueEditorState(
  seeded: VenueEditorStateInput,
  stored: Partial<VenueEditorStateInput> = seeded,
  updatedAt?: string,
  options: NormalizeVenueEditorStateOptions = {},
): VenueEditorState {
  const storedRooms = Array.isArray(stored.rooms) ? stored.rooms : seeded.rooms;
  const storedSpots = Array.isArray(stored.spots) ? normalizeStoredSpots(stored.spots, storedRooms) : seeded.spots;
  const deriveRoomRects = options.deriveRoomRects ?? true;
  const rooms = storedRooms.map((room) => {
    const seededRoom = seeded.rooms.find((candidate) => candidate.id === room.id);
    return {
      ...room,
      rect: room.rect ?? seededRoom?.rect ?? (deriveRoomRects ? venueRoomRect(room, storedSpots) : undefined),
    };
  });
  if (options.assignSpotsToNearestRooms === true) {
    const assigned = assignVenueSpotsToNearestRooms(rooms, storedSpots);
    return {
      ...seeded,
      ...stored,
      rooms: assigned.rooms,
      spots: assigned.spots,
      links: [],
      paths: Array.isArray(stored.paths) ? stored.paths : seeded.paths,
      updatedAt,
    };
  }

  const syncedRooms = syncVenueRoomSpotIdsFromSpots(rooms, storedSpots);
  return {
    ...seeded,
    ...stored,
    rooms: syncedRooms,
    spots: storedSpots.map((spot) => ({
      ...spot,
      position: { ...spot.position },
    })),
    links: [],
    paths: Array.isArray(stored.paths) ? stored.paths : seeded.paths,
    updatedAt,
  };
}

function syncVenueRoomSpotIdsFromSpots(rooms: VenueEditorState["rooms"], spots: VenueEditorState["spots"]): VenueEditorState["rooms"] {
  const spotIdsByRoom = new Map(rooms.map((room) => [room.id, [] as string[]] as const));
  spots.forEach((spot) => {
    spotIdsByRoom.get(spot.roomId)?.push(spot.id);
  });

  return rooms.map((room) => ({
    ...room,
    rect: room.rect ? { ...room.rect } : undefined,
    position: room.position ? { ...room.position } : undefined,
    spotIds: spotIdsByRoom.get(room.id) ?? [],
    neighborIds: [...room.neighborIds],
  }));
}

function normalizeStoredSpots(
  spots: Array<Partial<VenueEditorState["spots"][number]> & Pick<VenueEditorState["spots"][number], "id" | "label" | "position">>,
  rooms: VenueEditorState["rooms"],
): VenueEditorState["spots"] {
  return spots.map((spot) => {
    const role = spot.role === "audience" || spot.role === "speaker" ? spot.role : undefined;
    if (spot.roomId) {
      return {
        ...spot,
        roomId: spot.roomId,
        role,
      };
    }

    const room = rooms.find((candidate) => candidate.spotIds.includes(spot.id)) ?? rooms[0];
    return {
      ...spot,
      roomId: room?.id ?? "room",
      role,
    };
  });
}
