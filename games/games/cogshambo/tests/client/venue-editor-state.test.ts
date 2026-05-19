import { describe, expect, it } from "vitest";

import {
  addRoomPathPoint,
  copySelectedSpots,
  assignSelectedSpotsToRoom,
  createRoom,
  deleteRoomPathPoint,
  moveRoomPathPoint,
  deleteRoomPath,
  moveRoomRect,
  moveRoomNode,
  moveSelectedSpots,
  pasteCopiedSpots,
  pasteCopiedSpotsIntoRoom,
  resizeRoomRect,
  selectSpot,
  toggleSelectedSpotRoles,
  toggleSpotRoomAssignment,
  upsertRoomPath,
  type VenueEditorDraft,
} from "../../src/client/ui/venue-editor-state";

const draft: VenueEditorDraft = {
  imageUrl: "/assets/cogshambo/venue/gray-area-floor-plan.png",
  dimensions: { width: 50, height: 28 },
  rooms: [
    {
      id: "room-a",
      label: "Room A",
      kind: "lounge",
      rect: { x: 1, y: 2, width: 8, height: 6 },
      spotIds: ["spot-a", "spot-b"],
      neighborIds: ["room-b"],
    },
    {
      id: "room-b",
      label: "Room B",
      kind: "table",
      rect: { x: 8, y: 9, width: 7, height: 5 },
      spotIds: ["spot-c"],
      neighborIds: ["room-a"],
    },
  ],
  spots: [
    { id: "spot-a", roomId: "room-a", label: "A", position: { x: 2, y: 3 } },
    { id: "spot-b", roomId: "room-a", label: "B", position: { x: 5, y: 7 } },
    { id: "spot-c", roomId: "room-b", label: "C", position: { x: 9, y: 11 } },
  ],
  links: [],
  paths: [{ id: "room-a__room-b", fromRoomId: "room-a", toRoomId: "room-b", points: [{ x: 6, y: 7 }] }],
};

describe("venue editor state", () => {
  it("selects one spot normally and toggles multiple spots with shift-click", () => {
    let selected = selectSpot(new Set<string>(), "spot-a", { additive: false });
    expect([...selected]).toEqual(["spot-a"]);

    selected = selectSpot(selected, "spot-b", { additive: true });
    expect([...selected].sort()).toEqual(["spot-a", "spot-b"]);

    selected = selectSpot(selected, "spot-a", { additive: true });
    expect([...selected]).toEqual(["spot-b"]);
  });

  it("toggles selected spots between default participant and audience roles", () => {
    const audience = toggleSelectedSpotRoles(draft, new Set(["spot-a", "spot-b"]));

    expect(audience.spots.find((spot) => spot.id === "spot-a")?.role).toBe("audience");
    expect(audience.spots.find((spot) => spot.id === "spot-b")?.role).toBe("audience");
    expect(audience.spots.find((spot) => spot.id === "spot-c")?.role).toBeUndefined();

    const speakers = toggleSelectedSpotRoles(audience, new Set(["spot-a"]));

    expect(speakers.spots.find((spot) => spot.id === "spot-a")?.role).toBe("speaker");
    expect(speakers.spots.find((spot) => spot.id === "spot-b")?.role).toBe("audience");
  });

  it("copies, pastes, and offsets selected spot groups without carrying legacy links", () => {
    const linkedDraft = {
      ...draft,
      links: [{ id: "spot-a__spot-b", fromSpotId: "spot-a", toSpotId: "spot-b" }],
    };
    const clipboard = copySelectedSpots(linkedDraft, new Set(["spot-a", "spot-b"]));

    const pasted = pasteCopiedSpots(linkedDraft, clipboard, { x: 4, y: 2 });

    expect(pasted.draft.spots).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ id: "spot-a_copy_1", label: "spot-a_copy_1", position: { x: 6, y: 5 } }),
        expect.objectContaining({ id: "spot-b_copy_1", label: "spot-b_copy_1", position: { x: 9, y: 9 } }),
      ]),
    );
    expect([...pasted.selectedSpotIds].sort()).toEqual(["spot-a_copy_1", "spot-b_copy_1"]);
    expect(clipboard.links).toEqual([]);
    expect(pasted.draft.links).toEqual([]);
  });

  it("drags selected spots as a group", () => {
    const moved = moveSelectedSpots(draft, new Set(["spot-a", "spot-c"]), { x: 3, y: -1 });

    expect(moved.spots.find((spot) => spot.id === "spot-a")?.position).toEqual({ x: 5, y: 2 });
    expect(moved.spots.find((spot) => spot.id === "spot-b")?.position).toEqual({ x: 5, y: 7 });
    expect(moved.spots.find((spot) => spot.id === "spot-c")?.position).toEqual({ x: 12, y: 10 });
  });

  it("drags a room node without moving spots in that room", () => {
    const moved = moveRoomNode(draft, "room-a", { x: 12, y: 14 });

    expect(moved.rooms.find((room) => room.id === "room-a")?.position).toEqual({ x: 12, y: 14 });
    expect(moved.spots.find((spot) => spot.id === "spot-a")?.position).toEqual({ x: 2, y: 3 });
    expect(moved.spots.find((spot) => spot.id === "spot-b")?.position).toEqual({ x: 5, y: 7 });
  });

  it("moves and resizes room rectangles without moving room spots", () => {
    const moved = moveRoomRect(draft, "room-a", { x: 4, y: 5 });
    const resized = resizeRoomRect(moved, "room-a", { width: 12, height: 9 });

    expect(resized.rooms.find((room) => room.id === "room-a")?.rect).toEqual({
      x: 4,
      y: 5,
      width: 12,
      height: 9,
    });
    expect(resized.spots.find((spot) => spot.id === "spot-a")?.position).toEqual({ x: 2, y: 3 });
    expect(resized.spots.find((spot) => spot.id === "spot-b")?.position).toEqual({ x: 5, y: 7 });
  });

  it("creates uniquely named room rectangles and connects them to nearby rooms", () => {
    const created = createRoom(draft);

    expect(created.room).toEqual({
      id: "new_room",
      label: "New Room",
      kind: "lounge",
      rect: { x: 9, y: 1, width: 8, height: 5 },
      spotIds: ["new_room_spot_1", "new_room_spot_2", "new_room_spot_3"],
      neighborIds: ["room-a", "room-b"],
    });
    expect(created.draft.rooms[created.draft.rooms.length - 1]).toEqual(created.room);
    expect(created.draft.spots.slice(draft.spots.length)).toEqual([
      { id: "new_room_spot_1", roomId: "new_room", label: "new_room_spot_1", role: "speaker", position: { x: 11, y: 3.5 } },
      { id: "new_room_spot_2", roomId: "new_room", label: "new_room_spot_2", role: "speaker", position: { x: 13, y: 3.5 } },
      { id: "new_room_spot_3", roomId: "new_room", label: "new_room_spot_3", role: "speaker", position: { x: 15, y: 3.5 } },
    ]);
    expect(created.draft.paths).toEqual([
      ...draft.paths,
      { id: "new_room__room-a", fromRoomId: "new_room", toRoomId: "room-a", points: [] },
      { id: "new_room__room-b", fromRoomId: "new_room", toRoomId: "room-b", points: [] },
    ]);
    expect(created.draft.rooms.find((room) => room.id === "room-a")?.neighborIds).toEqual(["new_room", "room-b"]);
    expect(created.draft.rooms.find((room) => room.id === "room-b")?.neighborIds).toEqual(["new_room", "room-a"]);

    const second = createRoom(created.draft);
    expect(second.room.id).toBe("new_room_2");
    expect(second.room.label).toBe("New Room 2");
    expect(second.room.rect?.x).toBeGreaterThanOrEqual(0);
    expect(second.room.rect?.y).toBeGreaterThanOrEqual(0);
    expect((second.room.rect?.x ?? 0) + (second.room.rect?.width ?? 0)).toBeLessThanOrEqual(draft.dimensions.width);
    expect((second.room.rect?.y ?? 0) + (second.room.rect?.height ?? 0)).toBeLessThanOrEqual(draft.dimensions.height);
  });

  it("creates room rectangles centered on requested board positions", () => {
    const created = createRoom(draft, { center: { x: 20, y: 12 } });

    expect(created.room.rect).toEqual({ x: 16, y: 9.5, width: 8, height: 5 });
    expect(created.room.spotIds).toEqual(["new_room_spot_1", "new_room_spot_2", "new_room_spot_3"]);
    expect(created.draft.spots.slice(draft.spots.length)).toEqual([
      { id: "new_room_spot_1", roomId: "new_room", label: "new_room_spot_1", role: "speaker", position: { x: 18, y: 12 } },
      { id: "new_room_spot_2", roomId: "new_room", label: "new_room_spot_2", role: "speaker", position: { x: 20, y: 12 } },
      { id: "new_room_spot_3", roomId: "new_room", label: "new_room_spot_3", role: "speaker", position: { x: 22, y: 12 } },
    ]);

    const clamped = createRoom(created.draft, { center: { x: 49, y: 27 } });

    expect(clamped.room.rect).toEqual({ x: 42, y: 23, width: 8, height: 5 });
  });

  it("connects new rooms to only the four closest existing rooms", () => {
    const rooms = [
      { id: "north", center: { x: 10, y: 7 } },
      { id: "west", center: { x: 6, y: 10 } },
      { id: "east", center: { x: 15, y: 10 } },
      { id: "south", center: { x: 10, y: 16 } },
      { id: "far", center: { x: 30, y: 10 } },
    ];
    const crowdedDraft: VenueEditorDraft = {
      ...draft,
      rooms: rooms.map(({ id, center }) => ({
        id,
        label: id,
        kind: "lounge",
        rect: { x: center.x - 1, y: center.y - 1, width: 2, height: 2 },
        spotIds: [],
        neighborIds: [],
      })),
      spots: [],
      paths: [],
    };

    const created = createRoom(crowdedDraft, { center: { x: 10, y: 10 } });

    expect(created.room.neighborIds).toEqual(["east", "north", "south", "west"]);
    expect(created.draft.paths.map((path) => path.id)).toEqual([
      "east__new_room",
      "new_room__north",
      "new_room__south",
      "new_room__west",
    ]);
    expect(created.draft.rooms.find((room) => room.id === "far")?.neighborIds).toEqual([]);
  });

  it("creates and edits room paths while syncing room neighbors", () => {
    const disconnected = {
      ...draft,
      rooms: draft.rooms.map((room) => ({ ...room, neighborIds: [] })),
      paths: [],
    };

    const connected = upsertRoomPath(disconnected, "room-b", "room-a", [{ x: 7, y: 8 }]);
    const path = connected.paths.find((candidate) => candidate.id === "room-a__room-b");

    expect(path).toEqual({
      id: "room-a__room-b",
      fromRoomId: "room-a",
      toRoomId: "room-b",
      points: [{ x: 7, y: 8 }],
    });
    expect(connected.rooms.find((room) => room.id === "room-a")?.neighborIds).toEqual(["room-b"]);
    expect(connected.rooms.find((room) => room.id === "room-b")?.neighborIds).toEqual(["room-a"]);

    const added = addRoomPathPoint(connected, "room-a__room-b", { x: 10, y: 11 });
    expect(added.paths.find((candidate) => candidate.id === "room-a__room-b")?.points).toEqual([
      { x: 7, y: 8 },
      { x: 10, y: 11 },
    ]);

    const moved = moveRoomPathPoint(added, "room-a__room-b", 0, { x: 9, y: 6 });
    expect(moved.paths.find((candidate) => candidate.id === "room-a__room-b")?.points[0]).toEqual({ x: 9, y: 6 });

    const trimmed = deleteRoomPathPoint(moved, "room-a__room-b", 0);
    expect(trimmed.paths.find((candidate) => candidate.id === "room-a__room-b")?.points).toEqual([
      { x: 10, y: 11 },
    ]);
  });

  it("deletes room paths while syncing room neighbors", () => {
    const deleted = deleteRoomPath(draft, "room-a__room-b");

    expect(deleted.paths).toEqual([]);
    expect(deleted.rooms.find((room) => room.id === "room-a")?.neighborIds).toEqual([]);
    expect(deleted.rooms.find((room) => room.id === "room-b")?.neighborIds).toEqual([]);
  });

  it("pastes copied spots into the active room and keeps room spot ids in sync", () => {
    const linkedDraft = {
      ...draft,
      links: [{ id: "spot-a__spot-b", fromSpotId: "spot-a", toSpotId: "spot-b" }],
    };
    const clipboard = copySelectedSpots(linkedDraft, new Set(["spot-a", "spot-b"]));

    const pasted = pasteCopiedSpotsIntoRoom(linkedDraft, clipboard, "room-b", { x: 4, y: 2 });

    expect(pasted.draft.spots).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ id: "spot-a_copy_1", label: "spot-a_copy_1", roomId: "room-b", position: { x: 6, y: 5 } }),
        expect.objectContaining({ id: "spot-b_copy_1", label: "spot-b_copy_1", roomId: "room-b", position: { x: 9, y: 9 } }),
      ]),
    );
    expect(pasted.draft.rooms.find((room) => room.id === "room-b")?.spotIds).toEqual([
      "spot-c",
      "spot-a_copy_1",
      "spot-b_copy_1",
    ]);
    expect(pasted.draft.links).toEqual([]);
  });

  it("assigns selected spots to a room and keeps room spot ids in sync", () => {
    const assigned = assignSelectedSpotsToRoom(draft, new Set(["spot-a", "spot-c"]), "room-b");

    expect(assigned.spots.find((spot) => spot.id === "spot-a")?.roomId).toBe("room-b");
    expect(assigned.spots.find((spot) => spot.id === "spot-b")?.roomId).toBe("room-a");
    expect(assigned.spots.find((spot) => spot.id === "spot-c")?.roomId).toBe("room-b");
    expect(assigned.rooms.find((room) => room.id === "room-a")?.spotIds).toEqual(["spot-b"]);
    expect(assigned.rooms.find((room) => room.id === "room-b")?.spotIds).toEqual(["spot-c", "spot-a"]);
  });

  it("moves a single spot between rooms without leaving it unassigned", () => {
    const unchanged = toggleSpotRoomAssignment(draft, "spot-a", "room-a");

    expect(unchanged.spots.find((spot) => spot.id === "spot-a")?.roomId).toBe("room-a");
    expect(unchanged.rooms.find((room) => room.id === "room-a")?.spotIds).toEqual(["spot-a", "spot-b"]);

    const reassigned = toggleSpotRoomAssignment(unchanged, "spot-a", "room-b");

    expect(reassigned.spots.find((spot) => spot.id === "spot-a")?.roomId).toBe("room-b");
    expect(reassigned.rooms.find((room) => room.id === "room-a")?.spotIds).toEqual(["spot-b"]);
    expect(reassigned.rooms.find((room) => room.id === "room-b")?.spotIds).toEqual(["spot-c", "spot-a"]);
  });
});
