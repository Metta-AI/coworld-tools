import { describe, expect, it } from "vitest";

import { debateBubbleBoardPosition, settledDebateEventsForOverlay } from "../../src/client/ui/debate-overlay";
import type { WorldEvent, WorldSnapshot } from "../../src/shared/types";

const debateExchange: WorldEvent = {
  id: "debate-1",
  tick: 12,
  type: "debateExchange",
  actorId: "red-cog",
  targetId: "blue-cog",
  message: "Ada's reason shook Babbage's certainty",
  position: { x: 2, y: 2 },
  debate: {
    actions: [
      { cogId: "red-cog", action: "reason" },
      { cogId: "blue-cog", action: "spin" },
    ],
    choicesRevealedAtTick: 12,
    resultRevealedAtTick: 13,
    expiresAtTick: 18,
    outcome: "win",
    round: 1,
    winnerCogId: "red-cog",
    winnerColor: "red",
  },
};

function snapshotWithEvents(recentEvents: WorldEvent[]): WorldSnapshot {
  return {
    tick: 14,
    dimensions: { width: 10, height: 10 },
    cogs: [
      {
        id: "red-cog",
        name: "Ada",
        color: "red",
        position: { x: 2, y: 2 },
        location: { roomId: "bar", spotId: "bar-left" },
      },
      {
        id: "blue-cog",
        name: "Babbage",
        color: "blue",
        position: { x: 3, y: 2 },
        location: { roomId: "bar", spotId: "bar-right" },
      },
    ] as WorldSnapshot["cogs"],
    objects: [],
    terrain: [],
    recentEvents,
  };
}

describe("debate overlay", () => {
  it("keeps showing recent settled debate exchanges before they expire", () => {
    expect(settledDebateEventsForOverlay(snapshotWithEvents([debateExchange]), new Set())).toEqual([debateExchange]);
  });

  it("hides a settled debate bubble once either participant converts", () => {
    const conversion: WorldEvent = {
      id: "conversion-1",
      tick: 12,
      type: "colorChange",
      actorId: "blue-cog",
      message: "Babbage changed to red",
      position: { x: 3, y: 2 },
    };

    expect(settledDebateEventsForOverlay(snapshotWithEvents([conversion, debateExchange]), new Set())).toEqual([]);
  });

  it("hides settled debate bubbles when the participants now share a team", () => {
    const snapshot = snapshotWithEvents([debateExchange]);
    snapshot.cogs = [
      { id: "red-cog", name: "Ada", color: "red" },
      { id: "blue-cog", name: "Babbage", color: "red" },
    ] as WorldSnapshot["cogs"];

    expect(settledDebateEventsForOverlay(snapshot, new Set())).toEqual([]);
  });

  it("hides settled debate bubbles once either participant starts a different debate", () => {
    const snapshot = snapshotWithEvents([debateExchange]);
    snapshot.cogs = [
      {
        id: "red-cog",
        name: "Ada",
        color: "red",
        position: { x: 2, y: 2 },
        location: { roomId: "bar", spotId: "bar-left" },
      },
      {
        id: "blue-cog",
        name: "Babbage",
        color: "blue",
        position: { x: 3, y: 2 },
        location: { roomId: "bar", spotId: "bar-right" },
        debate: {
          opponentId: "third-cog",
          startedTick: 13,
          nextRoundTick: 20,
          roundsResolved: 0,
        },
      },
      {
        id: "third-cog",
        name: "Carol",
        color: "red",
        position: { x: 4, y: 2 },
        location: { roomId: "bar", spotId: "bar-third" },
        debate: {
          opponentId: "blue-cog",
          startedTick: 13,
          nextRoundTick: 20,
          roundsResolved: 0,
        },
      },
    ] as WorldSnapshot["cogs"];

    expect(settledDebateEventsForOverlay(snapshot, new Set())).toEqual([]);
  });

  it("hides settled debate bubbles once venue participants are no longer in the same room", () => {
    const snapshot = snapshotWithEvents([debateExchange]);
    snapshot.cogs = [
      {
        id: "red-cog",
        name: "Ada",
        color: "red",
        position: { x: 2, y: 2 },
        location: { roomId: "bar", spotId: "bar-left" },
      },
      {
        id: "blue-cog",
        name: "Babbage",
        color: "blue",
        position: { x: 8, y: 2 },
        location: { roomId: "stage", spotId: "stage-right" },
      },
    ] as WorldSnapshot["cogs"];

    expect(settledDebateEventsForOverlay(snapshot, new Set())).toEqual([]);
  });

  it("hides settled debate bubbles while either participant is moving", () => {
    const snapshot = snapshotWithEvents([debateExchange]);
    snapshot.cogs = [
      {
        id: "red-cog",
        name: "Ada",
        color: "red",
        moving: {
          from: { roomId: "bar", spotId: "bar-a" },
          to: { roomId: "stage", spotId: "stage-a" },
          fromPosition: { x: 2, y: 2 },
          toPosition: { x: 8, y: 2 },
          path: [{ x: 2, y: 2 }, { x: 8, y: 2 }],
          startedTick: 14,
          arriveTick: 17,
        },
      },
      { id: "blue-cog", name: "Babbage", color: "blue" },
    ] as WorldSnapshot["cogs"];

    expect(settledDebateEventsForOverlay(snapshot, new Set())).toEqual([]);
  });

  it("anchors settled debate bubbles to the current participant midpoint", () => {
    expect(
      debateBubbleBoardPosition(
        { id: "red-cog", position: { x: 4, y: 6 } } as WorldSnapshot["cogs"][number],
        { id: "blue-cog", position: { x: 10, y: 8 } } as WorldSnapshot["cogs"][number],
      ),
    ).toEqual({ x: 7.5, y: 7.5 });
  });
});
