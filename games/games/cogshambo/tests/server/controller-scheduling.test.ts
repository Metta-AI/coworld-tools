import { describe, expect, it } from "vitest";
import { SeededRandom } from "../../src/server/simulation/random.js";
import { legacyHalfSecondTicksToSimulationTicks, secondsToSimulationTicks } from "../../src/shared/timing.js";
import type { Cog, CogAction, CogObservation, VenueLayout, WorldSnapshot } from "../../src/shared/types.js";
import { GridWorld } from "../../src/server/simulation/world.js";
import { tickWorld, viableControllerActionsFor } from "../../src/server/websocket.js";

const venue: VenueLayout = {
  rooms: [
    { id: "room-a", label: "Room A", kind: "lounge", spotIds: ["a1", "a2"], neighborIds: ["room-b"] },
    { id: "room-b", label: "Room B", kind: "lounge", spotIds: ["b1", "b2"], neighborIds: ["room-a"] },
  ],
  spots: [
    { id: "a1", roomId: "room-a", label: "A1", position: { x: 1, y: 1 } },
    { id: "a2", roomId: "room-a", label: "A2", position: { x: 2, y: 1 } },
    { id: "b1", roomId: "room-b", label: "B1", position: { x: 3, y: 1 } },
    { id: "b2", roomId: "room-b", label: "B2", position: { x: 4, y: 1 } },
  ],
  spotLinks: [
    { id: "a1__a2", fromSpotId: "a1", toSpotId: "a2" },
    { id: "b1__b2", fromSpotId: "b1", toSpotId: "b2" },
  ],
};

describe("controller scheduling", () => {
  it("skips cogs that cannot move", () => {
    const ada = cog({ id: "ada", color: "red", location: { roomId: "room-a", spotId: "a1" }, lastVenueMoveTick: 10 });
    const teammate = cog({ id: "teammate", color: "red", location: { roomId: "room-a", spotId: "a2" } });
    const snapshot = snapshotFor([ada, teammate], 20);

    expect(viableControllerActionsFor(observationFor(ada, snapshot), false)).toEqual([]);
  });

  it("does not ask cogs to choose debate targets", () => {
    const ada = cog({ id: "ada", color: "red", location: { roomId: "room-a", spotId: "a1" }, lastVenueMoveTick: 10 });
    const babbage = cog({ id: "babbage", color: "blue", location: { roomId: "room-a", spotId: "a2" } });
    const snapshot = snapshotFor([ada, babbage], 20);

    expect(viableControllerActionsFor(observationFor(ada, snapshot), false)).toEqual([]);
  });

  it("lets any same-room speaker spots debate without spot links and blocks audience spots", () => {
    const speakerVenue: VenueLayout = {
      rooms: [
        { id: "room-a", label: "Room A", kind: "lounge", spotIds: ["speaker-a", "speaker-b", "audience-a"], neighborIds: [] },
      ],
      spots: [
        { id: "speaker-a", roomId: "room-a", label: "Speaker A", position: { x: 1, y: 1 } },
        { id: "speaker-b", roomId: "room-a", label: "Speaker B", position: { x: 2, y: 1 }, role: "speaker" },
        { id: "audience-a", roomId: "room-a", label: "Audience A", position: { x: 3, y: 1 }, role: "audience" },
      ],
      spotLinks: [],
      roomPaths: [],
    };
    const world = new GridWorld({ width: 8, height: 8 }, {}, speakerVenue);
    const redSpeaker = world.addCog({ name: "Red Speaker", color: "red", location: { roomId: "room-a", spotId: "speaker-a" } });
    const blueSpeaker = world.addCog({ name: "Blue Speaker", color: "blue", location: { roomId: "room-a", spotId: "speaker-b" } });
    const blueAudience = world.addCog({ name: "Blue Audience", color: "blue", location: { roomId: "room-a", spotId: "audience-a" } });

    expect(world.canStartDebate(redSpeaker.id, blueSpeaker.id)).toBe(true);
    expect(world.canStartDebate(redSpeaker.id, blueAudience.id)).toBe(false);
  });

  it("runs cogs already in debate so they can choose tactics", () => {
    const ada = cog({
      id: "ada",
      color: "red",
      location: { roomId: "room-a", spotId: "a1" },
      debate: { opponentId: "babbage", startedTick: 1, nextRoundTick: 20, roundsResolved: 0 },
      lastVenueMoveTick: 10,
    });
    const snapshot = snapshotFor([ada], 20);

    expect(viableControllerActionsFor(observationFor(ada, snapshot), false, 20)).toEqual([
      "chooseTactic",
    ]);
  });

  it("skips cogs waiting for the next debate round", () => {
    const ada = cog({
      id: "ada",
      color: "red",
      location: { roomId: "room-a", spotId: "a1" },
      debate: { opponentId: "babbage", startedTick: 1, nextRoundTick: 40, roundsResolved: 1 },
      lastVenueMoveTick: 10,
    });
    const snapshot = snapshotFor([ada], 20);

    expect(viableControllerActionsFor(observationFor(ada, snapshot), false, 20)).toEqual([]);
  });

  it("runs cogs that can legally move", () => {
    const ada = cog({ id: "ada", color: "red", location: { roomId: "room-a", spotId: "a1" }, lastVenueMoveTick: 10 });
    const teammate = cog({ id: "teammate", color: "red", location: { roomId: "room-a", spotId: "a2" } });
    const snapshot = snapshotFor([ada, teammate], 140);

    expect(viableControllerActionsFor(observationFor(ada, snapshot), true)).toEqual(["move"]);
  });

  it("does not ask moving cogs to move again", () => {
    const ada = {
      ...cog({ id: "ada", color: "red", location: { roomId: "room-a", spotId: "a1" } }),
      moving: {
        from: { roomId: "room-a", spotId: "a1" },
        to: { roomId: "room-b", spotId: "b1" },
        fromPosition: { x: 1, y: 1 },
        toPosition: { x: 3, y: 1 },
        startedTick: 10,
        arriveTick: 12,
      },
    } as Cog;
    const snapshot = snapshotFor([ada], 11);

    expect(viableControllerActionsFor(observationFor(ada, snapshot), true, 12)).toEqual([]);
  });

  it("runs lone cogs on cooldown when the world says they can join an occupied conversation room", () => {
    const ada = cog({ id: "ada", color: "red", location: { roomId: "room-a", spotId: "a1" }, lastVenueMoveTick: 10 });
    const babbage = cog({ id: "babbage", color: "red", location: { roomId: "room-b", spotId: "b1" } });
    const snapshot = snapshotFor([ada, babbage], 20);

    expect(viableControllerActionsFor(observationFor(ada, snapshot), true)).toEqual(["move"]);
  });

  it("does not call a controller for a cog that can only wait", async () => {
    const world = new GridWorld({ width: 8, height: 8 });
    const ada = world.addCog({ name: "Ada", color: "red", controllerId: "llm", position: { x: 2, y: 2 } });
    world.setTerrain({ x: 3, y: 2 }, "sand");
    await world.step(new Map<string, CogAction>([[ada.id, { type: "move", direction: "east" }]]));

    let decisions = 0;
    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: {
          decide: async () => {
            decisions += 1;
            return { type: "wait" };
          },
        },
      },
      new Map(),
      () => false,
    );

    expect(decisions).toBe(0);
    expect(world.snapshot().cogs.find((cog) => cog.id === ada.id)?.conversationLog).toEqual([]);
  });

  it("keeps manual room choices queued until venue movement cooldown clears", async () => {
    const world = new GridWorld({ width: 10, height: 10 }, { roomMoveCooldownTicks: 4 }, venue);
    const ada = world.addCog({ name: "Ada", color: "red", controllerId: "stub", location: { roomId: "room-a", spotId: "a1" } });
    await world.step(new Map<string, CogAction>([[ada.id, { type: "move", roomId: "room-b" }]]));
    await stepUntilNotMoving(world, ada.id);
    world.addCog({ name: "Teammate", color: "red", controllerId: "stub", location: { roomId: "room-b", spotId: "b2" } });

    const controllers = {
      stub: { decide: async () => ({ type: "wait" }) },
      wander: { decide: async () => ({ type: "wait" }) },
      llm: { decide: async () => ({ type: "wait" }) },
    } as const;
    const manualActions = new Map<string, CogAction>([
      [ada.id, { type: "move", roomId: "room-a", intent: "manual roster choice" }],
    ]);

    await tickWorld(world, controllers, manualActions, () => false, { random: new SeededRandom(31) });

    expect(manualActions.has(ada.id)).toBe(true);
    expect(world.snapshot().cogs.find((cog) => cog.id === ada.id)?.location?.roomId).toBe("room-b");

    for (let tick = 0; tick < 6 && manualActions.has(ada.id); tick += 1) {
      await tickWorld(world, controllers, manualActions, () => false, { random: new SeededRandom(32 + tick) });
    }

    const queuedAda = world.snapshot().cogs.find((cog) => cog.id === ada.id);
    expect(manualActions.has(ada.id)).toBe(false);
    expect(queuedAda?.moving?.to.roomId).toBe("room-a");
  });

  it("keeps the current venue room and the previous five rooms on the cog", async () => {
    const world = new GridWorld({ width: 10, height: 10 }, { roomMoveCooldownTicks: 0 }, venue);
    const ada = world.addCog({ name: "Ada", color: "red", controllerId: "stub", location: { roomId: "room-a", spotId: "a1" } });

    for (const roomId of ["room-b", "room-a", "room-b", "room-a", "room-b", "room-a"]) {
      await world.step(new Map<string, CogAction>([[ada.id, { type: "move", roomId }]]), { ignoreRoomMoveCooldown: true });
      await stepUntilNotMoving(world, ada.id);
    }

    const roomHistory = world.snapshot().cogs.find((cog) => cog.id === ada.id)?.roomHistory;

    expect(roomHistory?.map((entry) => entry.roomId)).toEqual(["room-b", "room-a", "room-b", "room-a", "room-b", "room-a"]);
    expect(roomHistory?.at(-1)).toMatchObject({ roomId: "room-a", leftTick: undefined });
    expect(roomHistory?.slice(0, -1).every((entry) => entry.leftTick !== undefined)).toBe(true);
  });

  it("keeps manual tactic choices queued until the debate reveal window", async () => {
    const world = new GridWorld(
      { width: 6, height: 6 },
      { debatePrepTicks: 3, debateChoiceRevealTicks: 0, debateResultTicks: 0 },
    );
    const ada = world.addCog({ name: "Ada", color: "red", controllerId: "stub", position: { x: 2, y: 2 } });
    const babbage = world.addCog({ name: "Babbage", color: "blue", controllerId: "stub", position: { x: 3, y: 2 } });
    await world.step(new Map<string, CogAction>([[ada.id, { type: "debate", targetId: babbage.id }]]));

    const controllers = {
      stub: { decide: async () => ({ type: "chooseTactic", tactic: "spin" }) },
      wander: { decide: async () => ({ type: "wait" }) },
      llm: { decide: async () => ({ type: "wait" }) },
    } as const;
    const manualActions = new Map<string, CogAction>([
      [ada.id, { type: "chooseTactic", tactic: "passion", intent: "player steer: argue with passion" }],
    ]);

    await tickWorld(world, controllers, manualActions, () => false, { random: new SeededRandom(41) });
    expect(manualActions.has(ada.id)).toBe(true);
    expect(world.snapshot().recentEvents.some((event) => event.type === "debateExchange")).toBe(false);

    await tickWorld(world, controllers, manualActions, () => false, { random: new SeededRandom(42) });
    await tickWorld(world, controllers, manualActions, () => false, { random: new SeededRandom(43) });

    const exchange = world.snapshot().recentEvents.find((event) => event.type === "debateExchange");
    expect(manualActions.has(ada.id)).toBe(false);
    expect(exchange?.debate?.actions).toEqual([
      { cogId: ada.id, action: "passion" },
      { cogId: babbage.id, action: "spin" },
    ]);
  });

  it("records LLM decision thoughts and choice numbers in cog conversations", async () => {
    const world = new GridWorld({ width: 8, height: 8 }, {}, venue);
    const ada = world.addCog({
      name: "Ada",
      color: "red",
      controllerId: "llm",
      location: { roomId: "room-a", spotId: "a1" },
    });
    const thoughts = "Room B has a fresh opening, so I should head there before another cog takes it.";

    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: {
          decide: async (input) => ({
            type: "move",
            roomId: input.allowedRoomIds?.[0],
            choiceNumber: 1,
            thoughts,
          }),
        },
      },
      new Map(),
      () => false,
      { random: new SeededRandom(5) },
    );

    const assistantMessage = world
      .snapshot()
      .cogs.find((cog) => cog.id === ada.id)
      ?.conversationLog.find((message) => message.role === "assistant");
    expect(assistantMessage).toBeDefined();
    expect(JSON.parse(assistantMessage!.content)).toEqual(
      expect.objectContaining({
        type: "move",
        roomId: "room-b",
        choiceNumber: 1,
        thoughts,
      }),
    );
  });

  it("preserves LLM failure intent when a move-only decision falls back to wait", async () => {
    const world = new GridWorld({ width: 8, height: 8 }, {}, venue);
    const ada = world.addCog({
      name: "Ada",
      color: "red",
      controllerId: "llm",
      location: { roomId: "room-a", spotId: "a1" },
    });

    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: {
          decide: async () => ({ type: "wait", intent: "LLM request failed: timed out after 12000ms" }),
        },
      },
      new Map(),
      () => false,
      { random: new SeededRandom(5) },
    );

    const assistantMessage = world
      .snapshot()
      .cogs.find((cog) => cog.id === ada.id)
      ?.conversationLog.find((message) => message.role === "assistant");
    expect(assistantMessage).toBeDefined();
    expect(JSON.parse(assistantMessage!.content)).toEqual({
      type: "wait",
      intent: "LLM request failed: timed out after 12000ms",
    });
  });

  it("falls back to a random legal move when an LLM move decision times out", async () => {
    const world = new GridWorld({ width: 8, height: 8 }, {}, venue);
    const ada = world.addCog({
      name: "Ada",
      color: "red",
      controllerId: "llm",
      location: { roomId: "room-a", spotId: "a1" },
    });
    const decisionStats = { llmMoveDecisions: 0, llmTimedOutMoves: 0 };

    const result = await Promise.race([
      tickWorld(
        world,
        {
          stub: { decide: async () => ({ type: "wait" }) },
          wander: { decide: async () => ({ type: "wait" }) },
          llm: {
            decide: async () => new Promise<CogAction>(() => undefined),
          },
        },
        new Map(),
        () => false,
        {
          controllerDecisionStats: decisionStats,
          controllerDecisionTimeoutMs: 1,
          random: new SeededRandom(5),
          scripted: false,
        },
      ).then(() => "resolved"),
      delay(20).then(() => "pending"),
    ]);

    expect(result).toBe("resolved");
    const movingAda = world.snapshot().cogs.find((cog) => cog.id === ada.id);
    expect(movingAda?.moving?.to.roomId).toBe("room-b");
    expect(decisionStats).toEqual({ llmMoveDecisions: 1, llmTimedOutMoves: 1 });
    const assistantMessage = movingAda?.conversationLog.find((message) => message.role === "assistant");
    expect(JSON.parse(assistantMessage?.content ?? "{}")).toEqual(
      expect.objectContaining({
        type: "move",
        roomId: "room-b",
        timedOut: true,
      }),
    );
  });

  it("starts a debate itself without asking cogs to choose targets", async () => {
    const world = new GridWorld({ width: 6, height: 6 });
    const ada = world.addCog({ name: "Ada", color: "red", controllerId: "llm", position: { x: 2, y: 2 } });
    const babbage = world.addCog({ name: "Babbage", color: "blue", controllerId: "llm", position: { x: 3, y: 2 } });
    for (const position of [
      { x: 1, y: 2 },
      { x: 2, y: 1 },
      { x: 2, y: 3 },
      { x: 4, y: 2 },
      { x: 3, y: 1 },
      { x: 3, y: 3 },
    ]) {
      world.setTerrain(position, "wall");
    }

    let decisions = 0;
    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: {
          decide: async () => {
            decisions += 1;
            return { type: "wait" };
          },
        },
      },
      new Map(),
      () => false,
      { random: new SeededRandom(7) },
    );

    const snapshot = world.snapshot();
    expect(decisions).toBe(0);
    expect(snapshot.cogs.find((cog) => cog.id === ada.id)?.debate?.opponentId).toBe(babbage.id);
    expect(snapshot.cogs.find((cog) => cog.id === babbage.id)?.debate?.opponentId).toBe(ada.id);
    expect(snapshot.recentEvents).toContainEqual(
      expect.objectContaining({
        type: "gameFlow",
        actorId: ada.id,
        targetId: babbage.id,
        message: "starting debate between Ada and Babbage",
      }),
    );
  });

  it("starts same-room LLM debates before asking cogs for tactics", async () => {
    const debateVenue: VenueLayout = {
      rooms: [
        { id: "room-a", label: "Room A", kind: "lounge", spotIds: ["a1", "a2", "a3"], neighborIds: [] },
      ],
      spots: [
        { id: "a1", roomId: "room-a", label: "A1", position: { x: 1, y: 1 } },
        { id: "a2", roomId: "room-a", label: "A2", position: { x: 2, y: 1 } },
        { id: "a3", roomId: "room-a", label: "A3", position: { x: 3, y: 1 } },
      ],
      spotLinks: [],
      roomPaths: [],
    };
    const world = new GridWorld({ width: 8, height: 8 }, { debatePrepTicks: 0 }, debateVenue);
    const ada = world.addCog({ name: "Ada", color: "red", controllerId: "llm", location: { roomId: "room-a", spotId: "a1" } });
    const babbage = world.addCog({ name: "Babbage", color: "blue", controllerId: "llm", location: { roomId: "room-a", spotId: "a2" } });
    const curie = world.addCog({ name: "Curie", color: "blue", controllerId: "llm", location: { roomId: "room-a", spotId: "a3" } });

    const decisions: Array<{ cogId: string; allowedActions: CogAction["type"][] }> = [];
    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: {
          decide: async (decisionInput) => {
            decisions.push({
              cogId: decisionInput.observation.cog.id,
              allowedActions: decisionInput.allowedActions,
            });
            return { type: "chooseTactic", tactic: "reason" };
          },
        },
      },
      new Map(),
      () => false,
      { random: new SeededRandom(7), scripted: false },
    );

    const snapshot = world.snapshot();
    const selectedOpponentId = snapshot.cogs.find((cog) => cog.id === ada.id)?.debate?.opponentId;
    expect(decisions).toEqual([]);
    expect([babbage.id, curie.id]).toContain(selectedOpponentId);
    expect(snapshot.cogs.find((cog) => cog.id === selectedOpponentId)?.debate?.opponentId).toBe(ada.id);
    expect(snapshot.recentEvents).toContainEqual(
      expect.objectContaining({
        type: "gameFlow",
        actorId: ada.id,
        targetId: selectedOpponentId,
        message: expect.stringMatching(/^starting debate between Ada and (Babbage|Curie)$/),
      }),
    );

    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: {
          decide: async (decisionInput) => {
            decisions.push({
              cogId: decisionInput.observation.cog.id,
              allowedActions: decisionInput.allowedActions,
            });
            return { type: "chooseTactic", tactic: "reason" };
          },
        },
      },
      new Map(),
      () => false,
      { random: new SeededRandom(8), scripted: false },
    );

    expect(decisions).toHaveLength(2);
    expect(new Set(decisions.map((decision) => decision.cogId))).toEqual(new Set([ada.id, selectedOpponentId]));
    expect(decisions.map((decision) => decision.allowedActions)).toEqual([["chooseTactic"], ["chooseTactic"]]);
  });

  it("still asks live LLM cogs to move when debate is available but debate starts are cooling down", async () => {
    const moveVenue: VenueLayout = {
      rooms: [
        { id: "stage", label: "Stage", kind: "stage", spotIds: ["s1", "s2"], neighborIds: [] },
        { id: "lounge", label: "Lounge", kind: "lounge", spotIds: ["l1", "l2"], neighborIds: ["hall"] },
        { id: "hall", label: "Hall", kind: "hall", spotIds: ["h1", "h2"], neighborIds: ["lounge"] },
      ],
      spots: [
        { id: "s1", roomId: "stage", label: "S1", position: { x: 1, y: 1 } },
        { id: "s2", roomId: "stage", label: "S2", position: { x: 2, y: 1 } },
        { id: "l1", roomId: "lounge", label: "L1", position: { x: 5, y: 1 } },
        { id: "l2", roomId: "lounge", label: "L2", position: { x: 6, y: 1 } },
        { id: "h1", roomId: "hall", label: "H1", position: { x: 9, y: 1 } },
        { id: "h2", roomId: "hall", label: "H2", position: { x: 10, y: 1 } },
      ],
      spotLinks: [],
      roomPaths: [],
    };
    const world = new GridWorld({ width: 12, height: 8 }, {}, moveVenue);
    const stageRed = world.addCog({ name: "Stage Red", color: "red", controllerId: "llm", location: { roomId: "stage", spotId: "s1" } });
    const stageBlue = world.addCog({ name: "Stage Blue", color: "blue", controllerId: "llm", location: { roomId: "stage", spotId: "s2" } });
    const loungeRed = world.addCog({ name: "Lounge Red", color: "red", controllerId: "llm", location: { roomId: "lounge", spotId: "l1" } });
    const loungeBlue = world.addCog({ name: "Lounge Blue", color: "blue", controllerId: "llm", location: { roomId: "lounge", spotId: "l2" } });
    await world.step(new Map<string, CogAction>([[stageRed.id, { type: "debate", targetId: stageBlue.id }]]));

    const decisions: Array<{ cogId: string; allowedActions: CogAction["type"][]; allowedRoomIds: string[] }> = [];
    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: {
          decide: async (input) => {
            decisions.push({
              cogId: input.observation.cog.id,
              allowedActions: input.allowedActions,
              allowedRoomIds: input.allowedRoomIds ?? [],
            });
            return { type: "move", roomId: input.allowedRoomIds?.[0], intent: "test room choice" };
          },
        },
      },
      new Map(),
      () => false,
      { random: new SeededRandom(9), scripted: false },
    );

    expect(decisions).toEqual([
      { cogId: loungeRed.id, allowedActions: ["move"], allowedRoomIds: ["hall"] },
      { cogId: loungeBlue.id, allowedActions: ["move"], allowedRoomIds: ["hall"] },
    ]);
    expect(world.snapshot().cogs.find((cog) => cog.id === loungeRed.id)?.moving?.to.roomId).toBe("hall");
    expect(world.snapshot().cogs.find((cog) => cog.id === loungeBlue.id)?.moving?.to.roomId).toBe("hall");
  });

  it("starts a cued same-room debate instead of asking for a move", async () => {
    const world = new GridWorld({ width: 10, height: 10 }, { maxDebatesPerTick: 4 }, venue);
    const ada = world.addCog({
      name: "Ada",
      color: "red",
      controllerId: "llm",
      location: { roomId: "room-a", spotId: "a1" },
    });
    const babbage = world.addCog({
      name: "Babbage",
      color: "blue",
      controllerId: "llm",
      location: { roomId: "room-a", spotId: "a2" },
    });
    await world.step(new Map<string, CogAction>([
      [ada.id, { type: "wait", intent: "player steer: communicate with Babbage and hold the room" }],
    ]));

    let moveDecisions = 0;
    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: {
          decide: async () => {
            moveDecisions += 1;
            return { type: "move", roomId: "room-b", intent: "leave instead" };
          },
        },
      },
      new Map(),
      () => false,
      { random: new SeededRandom(52) },
    );

    const snapshot = world.snapshot();
    expect(moveDecisions).toBe(0);
    expect(snapshot.cogs.find((cog) => cog.id === ada.id)?.debate?.opponentId).toBe(babbage.id);
    expect(snapshot.cogs.find((cog) => cog.id === babbage.id)?.debate?.opponentId).toBe(ada.id);
    expect(snapshot.cogs.find((cog) => cog.id === ada.id)?.moving).toBeUndefined();
    expect(snapshot.recentEvents).toContainEqual(
      expect.objectContaining({
        type: "gameFlow",
        actorId: ada.id,
        targetId: babbage.id,
        message: "starting cued debate between Ada and Babbage",
      }),
    );
  });

  it("does not turn non-movement human cues into room moves", async () => {
    const world = new GridWorld({ width: 10, height: 10 }, {}, venue);
    const ada = world.addCog({
      name: "Ada",
      color: "red",
      controllerId: "llm",
      location: { roomId: "room-a", spotId: "a1" },
    });
    await world.step(new Map<string, CogAction>([
      [ada.id, { type: "wait", intent: "player steer: read the room and protect certainty" }],
    ]));

    let moveDecisions = 0;
    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: {
          decide: async () => {
            moveDecisions += 1;
            return { type: "move", roomId: "room-b", intent: "move anyway" };
          },
        },
      },
      new Map(),
      () => false,
      { random: new SeededRandom(53) },
    );

    const snapshot = world.snapshot();
    expect(moveDecisions).toBe(0);
    expect(snapshot.cogs.find((cog) => cog.id === ada.id)?.location?.roomId).toBe("room-a");
    expect(snapshot.cogs.find((cog) => cog.id === ada.id)?.moving).toBeUndefined();
  });

  it("does not move away when a human cue names someone already in the room", async () => {
    const world = new GridWorld({ width: 10, height: 10 }, {}, venue);
    const ada = world.addCog({
      name: "Ada",
      color: "red",
      controllerId: "llm",
      location: { roomId: "room-a", spotId: "a1" },
    });
    world.addCog({
      name: "Babbage",
      color: "red",
      controllerId: "stub",
      location: { roomId: "room-a", spotId: "a2" },
    });
    await world.step(new Map<string, CogAction>([
      [ada.id, { type: "wait", intent: "player steer: find Babbage and hold position" }],
    ]));

    let moveDecisions = 0;
    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: {
          decide: async () => {
            moveDecisions += 1;
            return { type: "move", roomId: "room-b", intent: "leave anyway" };
          },
        },
      },
      new Map(),
      () => false,
      { random: new SeededRandom(54) },
    );

    const snapshot = world.snapshot();
    expect(moveDecisions).toBe(0);
    expect(snapshot.cogs.find((cog) => cog.id === ada.id)?.location?.roomId).toBe("room-a");
    expect(snapshot.cogs.find((cog) => cog.id === ada.id)?.moving).toBeUndefined();
  });

  it("does not start or resolve debates in disco mode", async () => {
    const world = new GridWorld(
      { width: 6, height: 6 },
      { debatePrepTicks: 0, debateChoiceRevealTicks: 0, debateResultTicks: 0 },
    );
    const ada = world.addCog({ name: "Ada", color: "red", controllerId: "llm", position: { x: 2, y: 2 } });
    const babbage = world.addCog({ name: "Babbage", color: "blue", controllerId: "llm", position: { x: 3, y: 2 } });
    for (const position of [
      { x: 1, y: 2 },
      { x: 2, y: 1 },
      { x: 2, y: 3 },
      { x: 4, y: 2 },
      { x: 3, y: 1 },
      { x: 3, y: 3 },
    ]) {
      world.setTerrain(position, "wall");
    }
    const controllers = {
      stub: { decide: async () => ({ type: "wait" }) },
      wander: { decide: async () => ({ type: "wait" }) },
      llm: { decide: async () => ({ type: "chooseTactic", tactic: "reason" }) },
    } as const;

    await tickWorld(world, controllers, new Map(), () => false, {
      discoMode: true,
      random: new SeededRandom(7),
    });

    expect(world.snapshot().cogs.every((cog) => !cog.debate)).toBe(true);
    expect(world.snapshot().recentEvents.some((event) => event.type === "debateStart")).toBe(false);

    await world.step(new Map<string, CogAction>([[ada.id, { type: "debate", targetId: babbage.id }]]));
    expect(world.snapshot().cogs.some((cog) => cog.debate)).toBe(true);

    await tickWorld(world, controllers, new Map(), () => false, {
      discoMode: true,
      random: new SeededRandom(8),
    });

    expect(world.snapshot().cogs.every((cog) => !cog.debate)).toBe(true);
    expect(world.snapshot().recentEvents.some((event) => event.type === "debateExchange")).toBe(false);
  });

  it("caps game-started debates by settings", async () => {
    const world = new GridWorld({ width: 12, height: 8 }, { maxDebatesPerTick: 1 });
    for (let index = 0; index < 4; index += 1) {
      const x = 1 + index * 2;
      world.addCog({ name: `Red ${index}`, color: "red", controllerId: "stub", position: { x, y: 2 } });
      world.addCog({ name: `Blue ${index}`, color: "blue", controllerId: "stub", position: { x: x + 1, y: 2 } });
    }

    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: { decide: async () => ({ type: "wait" }) },
      },
      new Map(),
      () => false,
      { random: new SeededRandom(11) },
    );

    expect(world.snapshot().recentEvents.filter((event) => event.type === "debateStart")).toHaveLength(1);
  });

  it("starts the debate with the longest-idle eligible cog", async () => {
    const world = new GridWorld({ width: 12, height: 8 }, { maxDebatesPerTick: 1 });
    const recentRed = world.addCog({ name: "Recent Red", color: "red", controllerId: "stub", position: { x: 1, y: 2 } });
    const recentBlue = world.addCog({ name: "Recent Blue", color: "blue", controllerId: "stub", position: { x: 2, y: 2 } });
    const idleRed = world.addCog({ name: "Idle Red", color: "red", controllerId: "stub", position: { x: 5, y: 2 } });
    const idleBlue = world.addCog({ name: "Idle Blue", color: "blue", controllerId: "stub", position: { x: 6, y: 2 } });

    world.recordGameFlow("activity for Idle Red", idleRed.id);
    await world.step(new Map());
    world.recordGameFlow("activity for Idle Blue", idleBlue.id);
    await world.step(new Map());
    world.recordGameFlow("activity for Recent Blue", recentBlue.id);
    await world.step(new Map());
    world.recordGameFlow("activity for Recent Red", recentRed.id);
    await world.step(new Map());

    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: { decide: async () => ({ type: "wait" }) },
      },
      new Map(),
      () => false,
      { random: new SeededRandom(1) },
    );

    expect(world.snapshot().recentEvents).toContainEqual(
      expect.objectContaining({
        type: "gameFlow",
        actorId: idleRed.id,
        message: expect.stringMatching(/^starting debate between Idle Red and /),
      }),
    );
  });

  it("starts game debates with under-three-debate cogs before experienced eligible cogs", async () => {
    let world = new GridWorld({ width: 12, height: 8 }, { maxDebatesPerTick: 1 });
    const experiencedRed = world.addCog({ name: "Experienced Red", color: "red", controllerId: "stub", position: { x: 1, y: 2 } });
    const experiencedBlue = world.addCog({ name: "Experienced Blue", color: "blue", controllerId: "stub", position: { x: 2, y: 2 } });
    const freshRed = world.addCog({ name: "Fresh Red", color: "red", controllerId: "stub", position: { x: 5, y: 2 } });
    const freshBlue = world.addCog({ name: "Fresh Blue", color: "blue", controllerId: "stub", position: { x: 6, y: 2 } });
    world = worldWithCogPatches(world, {
      [experiencedRed.id]: { stats: { argumentsWon: 3, argumentsLost: 0, teamFlips: 0 } },
      [experiencedBlue.id]: { stats: { argumentsWon: 0, argumentsLost: 3, teamFlips: 0 } },
    });

    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: { decide: async () => ({ type: "wait" }) },
      },
      new Map(),
      () => false,
      { random: new SeededRandom(1) },
    );

    const snapshot = world.snapshot();
    expect(snapshot.cogs.find((cog) => cog.id === freshRed.id)?.debate?.opponentId).toBe(freshBlue.id);
    expect(snapshot.cogs.find((cog) => cog.id === freshBlue.id)?.debate?.opponentId).toBe(freshRed.id);
    expect(snapshot.cogs.find((cog) => cog.id === experiencedRed.id)?.debate).toBeUndefined();
    expect(snapshot.cogs.find((cog) => cog.id === experiencedBlue.id)?.debate).toBeUndefined();
  });

  it("spaces game-started debates by at least three seconds", async () => {
    const world = new GridWorld(
      { width: 14, height: 8 },
      {
        maxDebatesPerTick: 4,
        debatePrepTicks: 0,
        debateChoiceRevealTicks: 0,
        debateResultTicks: 0,
        maxDebateRounds: 1,
        debateCooldownTicks: 0,
      },
    );
    for (let index = 0; index < 3; index += 1) {
      const x = 1 + index * 4;
      world.addCog({ name: `Red ${index}`, color: "red", controllerId: "stub", position: { x, y: 2 } });
      world.addCog({ name: `Blue ${index}`, color: "blue", controllerId: "stub", position: { x: x + 1, y: 2 } });
    }

    const controllers = {
      stub: {
        decide: async (input) =>
          input.allowedActions.includes("chooseTactic")
            ? ({ type: "chooseTactic", tactic: "reason" } as CogAction)
            : ({ type: "wait" } as CogAction),
      },
      wander: { decide: async () => ({ type: "wait" }) },
      llm: { decide: async () => ({ type: "wait" }) },
    } as const;

    await tickWorld(world, controllers, new Map(), () => false, { random: new SeededRandom(37) });
    expect(world.snapshot().recentEvents.filter((event) => event.type === "debateStart")).toHaveLength(1);

    for (let tick = 0; tick < secondsToSimulationTicks(3) - 1; tick += 1) {
      await tickWorld(world, controllers, new Map(), () => false, { random: new SeededRandom(38 + tick) });
    }
    expect(world.snapshot().recentEvents.filter((event) => event.type === "debateStart")).toHaveLength(1);

    await tickWorld(world, controllers, new Map(), () => false, { random: new SeededRandom(50) });
    expect(world.snapshot().recentEvents.filter((event) => event.type === "debateStart")).toHaveLength(2);
  });

  it("caps total active game-started debates across ticks", async () => {
    const world = new GridWorld(
      { width: 5, height: 10 },
      { maxDebatesPerTick: 1, debatePrepTicks: 4, debateChoiceRevealTicks: 6, debateResultTicks: 6 },
    );
    for (let index = 0; index < 4; index += 1) {
      const y = 1 + index * 2;
      world.addCog({ name: `Red ${index}`, color: "red", controllerId: "stub", position: { x: 1, y } });
      world.addCog({ name: `Blue ${index}`, color: "blue", controllerId: "stub", position: { x: 2, y } });
    }

    const controllers = {
      stub: { decide: async () => ({ type: "wait" }) },
      wander: { decide: async () => ({ type: "wait" }) },
      llm: { decide: async () => ({ type: "wait" }) },
    } as const;

    await tickWorld(world, controllers, new Map(), () => false, { random: new SeededRandom(11) });
    expect(activeDebateCount(world.snapshot())).toBe(1);

    await tickWorld(world, controllers, new Map(), () => false, { random: new SeededRandom(12) });

    expect(activeDebateCount(world.snapshot())).toBe(1);
    expect(world.snapshot().recentEvents.filter((event) => event.type === "debateStart")).toHaveLength(1);
  });

  it("fills an empty map side with a debate when the start cooldown allows it", async () => {
    const sectionVenue: VenueLayout = {
      rooms: [
        { id: "left-room", label: "Left Room", kind: "lounge", spotIds: ["left-a", "left-b"], neighborIds: [] },
        { id: "center-room", label: "Center Room", kind: "lounge", spotIds: ["center-a", "center-b"], neighborIds: [] },
      ],
      spots: [
        { id: "left-a", roomId: "left-room", label: "Left A", position: { x: 2, y: 1 } },
        { id: "left-b", roomId: "left-room", label: "Left B", position: { x: 3, y: 1 } },
        { id: "center-a", roomId: "center-room", label: "Center A", position: { x: 12, y: 1 } },
        { id: "center-b", roomId: "center-room", label: "Center B", position: { x: 13, y: 1 } },
      ],
      spotLinks: [],
      roomPaths: [],
    };
    const world = new GridWorld(
      { width: 30, height: 6 },
      {
        maxDebatesPerTick: 1,
        debatePrepTicks: 100,
        debateChoiceRevealTicks: 100,
        debateResultTicks: 100,
      },
      sectionVenue,
    );
    const leftRed = world.addCog({ name: "Left Red", color: "red", controllerId: "stub", location: { roomId: "left-room", spotId: "left-a" } });
    const leftBlue = world.addCog({ name: "Left Blue", color: "blue", controllerId: "stub", location: { roomId: "left-room", spotId: "left-b" } });
    const centerRed = world.addCog({ name: "Center Red", color: "red", controllerId: "stub", location: { roomId: "center-room", spotId: "center-a" } });
    const centerBlue = world.addCog({ name: "Center Blue", color: "blue", controllerId: "stub", location: { roomId: "center-room", spotId: "center-b" } });
    const controllers = {
      stub: {
        decide: async (input) =>
          input.allowedActions.includes("chooseTactic")
            ? ({ type: "chooseTactic", tactic: "reason" } as CogAction)
            : ({ type: "wait" } as CogAction),
      },
      wander: { decide: async () => ({ type: "wait" }) },
      llm: { decide: async () => ({ type: "wait" }) },
    } as const;

    await world.step(new Map<string, CogAction>([[leftRed.id, { type: "debate", targetId: leftBlue.id }]]));
    expect(activeDebateCount(world.snapshot())).toBe(1);

    for (let tick = 0; tick < secondsToSimulationTicks(3) - 1; tick += 1) {
      await tickWorld(world, controllers, new Map(), () => false, { random: new SeededRandom(38 + tick) });
    }
    expect(activeDebateCount(world.snapshot())).toBe(1);

    await tickWorld(world, controllers, new Map(), () => false, { random: new SeededRandom(50) });
    expect(activeDebateCount(world.snapshot())).toBe(2);
    expect(world.snapshot().cogs.find((cog) => cog.id === centerRed.id)?.debate?.opponentId).toBe(centerBlue.id);
    expect(world.snapshot().cogs.find((cog) => cog.id === centerBlue.id)?.debate?.opponentId).toBe(centerRed.id);
  });

  it("asks active debate cogs for tactics before resolving ready rounds", async () => {
    const world = new GridWorld(
      { width: 6, height: 6 },
      { debatePrepTicks: 0, debateChoiceRevealTicks: 0, debateResultTicks: 0 },
    );
    const ada = world.addCog({
      name: "Ada",
      color: "red",
      controllerId: "llm",
      activeTrait: "passionate",
      position: { x: 2, y: 2 },
    });
    const babbage = world.addCog({
      name: "Babbage",
      color: "blue",
      controllerId: "llm",
      activeTrait: "spinner",
      position: { x: 3, y: 2 },
    });
    await world.step(new Map<string, CogAction>([[ada.id, { type: "debate", targetId: babbage.id }]]));

    const decisions: string[] = [];
    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: {
          decide: async (input) => {
            decisions.push(input.observation.cog.id);
            return {
              type: "chooseTactic",
              tactic: input.observation.cog.id === ada.id ? "passion" : "spin",
            };
          },
        },
      },
      new Map(),
      () => false,
      { random: new SeededRandom(7) },
    );

    const exchange = world.snapshot().recentEvents.find((event) => event.type === "debateExchange");
    expect(new Set(decisions)).toEqual(new Set([ada.id, babbage.id]));
    expect(exchange?.debate?.actions.map((action) => action.action).sort()).toEqual(["passion", "spin"]);
  });

  it("does not spend a room's move decisions on a second debate in the same venue room", async () => {
    const crowdedVenue: VenueLayout = {
      rooms: [
        { id: "room-a", label: "Room A", kind: "lounge", spotIds: ["a1", "a2", "a3", "a4"], neighborIds: ["room-b"] },
        { id: "room-b", label: "Room B", kind: "lounge", spotIds: ["b1", "b2"], neighborIds: ["room-a"] },
      ],
      spots: [
        { id: "a1", roomId: "room-a", label: "A1", position: { x: 1, y: 1 } },
        { id: "a2", roomId: "room-a", label: "A2", position: { x: 2, y: 1 } },
        { id: "a3", roomId: "room-a", label: "A3", position: { x: 3, y: 1 } },
        { id: "a4", roomId: "room-a", label: "A4", position: { x: 4, y: 1 } },
        { id: "b1", roomId: "room-b", label: "B1", position: { x: 1, y: 2 } },
        { id: "b2", roomId: "room-b", label: "B2", position: { x: 2, y: 2 } },
      ],
      spotLinks: [
        { id: "a1__a2", fromSpotId: "a1", toSpotId: "a2" },
        { id: "a3__a4", fromSpotId: "a3", toSpotId: "a4" },
      ],
    };
    const world = new GridWorld({ width: 8, height: 8 }, { maxDebatesPerTick: 4 }, crowdedVenue);
    world.addCog({ name: "Ada", color: "red", controllerId: "llm", location: { roomId: "room-a", spotId: "a1" } });
    world.addCog({ name: "Babbage", color: "blue", controllerId: "llm", location: { roomId: "room-a", spotId: "a2" } });
    world.addCog({ name: "Curie", color: "red", controllerId: "llm", location: { roomId: "room-a", spotId: "a3" } });
    world.addCog({ name: "Darwin", color: "blue", controllerId: "llm", location: { roomId: "room-a", spotId: "a4" } });

    let moveDecisions = 0;
    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: {
          decide: async (input) => {
            moveDecisions += 1;
            return { type: "move", roomId: input.allowedRoomIds?.[0], intent: "leave crowded room" };
          },
        },
      },
      new Map(),
      () => false,
      { random: new SeededRandom(36) },
    );

    expect(world.snapshot().recentEvents.filter((event) => event.type === "debateStart")).toHaveLength(1);
    expect(moveDecisions).toBeGreaterThan(0);
  });

  it("does not schedule debate attempts in an already occupied venue section", async () => {
    const sectionVenue: VenueLayout = {
      rooms: [
        { id: "west-a", label: "West A", kind: "lounge", spotIds: ["wa1", "wa2"], neighborIds: [] },
        { id: "west-b", label: "West B", kind: "lounge", spotIds: ["wb1", "wb2"], neighborIds: [] },
        { id: "center", label: "Center", kind: "lounge", spotIds: ["c1", "c2"], neighborIds: [] },
      ],
      spots: [
        { id: "wa1", roomId: "west-a", label: "WA1", position: { x: 2, y: 1 } },
        { id: "wa2", roomId: "west-a", label: "WA2", position: { x: 3, y: 1 } },
        { id: "wb1", roomId: "west-b", label: "WB1", position: { x: 4, y: 2 } },
        { id: "wb2", roomId: "west-b", label: "WB2", position: { x: 5, y: 2 } },
        { id: "c1", roomId: "center", label: "C1", position: { x: 11, y: 1 } },
        { id: "c2", roomId: "center", label: "C2", position: { x: 12, y: 1 } },
      ],
      spotLinks: [
        { id: "wa1__wa2", fromSpotId: "wa1", toSpotId: "wa2" },
        { id: "wb1__wb2", fromSpotId: "wb1", toSpotId: "wb2" },
        { id: "c1__c2", fromSpotId: "c1", toSpotId: "c2" },
      ],
      roomPaths: [],
    };
    const world = new GridWorld({ width: 30, height: 6 }, { maxDebatesPerTick: 4 }, sectionVenue);
    world.addCog({ name: "West Red A", color: "red", controllerId: "llm", location: { roomId: "west-a", spotId: "wa1" } });
    world.addCog({ name: "West Blue A", color: "blue", controllerId: "llm", location: { roomId: "west-a", spotId: "wa2" } });
    world.addCog({ name: "West Red B", color: "red", controllerId: "llm", location: { roomId: "west-b", spotId: "wb1" } });
    world.addCog({ name: "West Blue B", color: "blue", controllerId: "llm", location: { roomId: "west-b", spotId: "wb2" } });
    world.addCog({ name: "Center Red", color: "red", controllerId: "llm", location: { roomId: "center", spotId: "c1" } });
    world.addCog({ name: "Center Blue", color: "blue", controllerId: "llm", location: { roomId: "center", spotId: "c2" } });

    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: { decide: async () => ({ type: "wait" }) },
      },
      new Map(),
      () => false,
      { random: new SeededRandom(37) },
    );

    const snapshot = world.snapshot();
    const startedDebates = snapshot.recentEvents.filter((event) => event.type === "debateStart");
    const scheduledDebates = snapshot.recentEvents.filter(
      (event) => event.type === "gameFlow" && event.message.startsWith("starting debate"),
    );
    expect(scheduledDebates).toHaveLength(startedDebates.length);
  });

  it("runs a bounded random set of room move decisions with explicit room choices", async () => {
    const moveVenue: VenueLayout = {
      rooms: [
        { id: "room-a", label: "Room A", kind: "lounge", spotIds: ["a1", "a2", "a3"], neighborIds: ["room-b"] },
        { id: "room-b", label: "Room B", kind: "lounge", spotIds: ["b1", "b2", "b3"], neighborIds: ["room-a"] },
      ],
      spots: [
        { id: "a1", roomId: "room-a", label: "A1", position: { x: 1, y: 1 } },
        { id: "a2", roomId: "room-a", label: "A2", position: { x: 2, y: 1 } },
        { id: "a3", roomId: "room-a", label: "A3", position: { x: 3, y: 1 } },
        { id: "b1", roomId: "room-b", label: "B1", position: { x: 1, y: 2 } },
        { id: "b2", roomId: "room-b", label: "B2", position: { x: 2, y: 2 } },
        { id: "b3", roomId: "room-b", label: "B3", position: { x: 3, y: 2 } },
      ],
      spotLinks: [
        { id: "a1__a2", fromSpotId: "a1", toSpotId: "a2" },
        { id: "a1__a3", fromSpotId: "a1", toSpotId: "a3" },
        { id: "a2__a3", fromSpotId: "a2", toSpotId: "a3" },
        { id: "b1__b2", fromSpotId: "b1", toSpotId: "b2" },
        { id: "b1__b3", fromSpotId: "b1", toSpotId: "b3" },
        { id: "b2__b3", fromSpotId: "b2", toSpotId: "b3" },
      ],
    };
    const world = new GridWorld({ width: 8, height: 8 }, {}, moveVenue);
    const spots = ["a1", "a2", "b1", "b2"] as const;
    for (let index = 0; index < 4; index += 1) {
      world.addCog({
        name: `Mover ${index}`,
        color: "red",
        controllerId: "llm",
        location: {
          roomId: spots[index].startsWith("a") ? "room-a" : "room-b",
          spotId: spots[index],
        },
      });
    }

    let activeDecisions = 0;
    let maxActiveDecisions = 0;
    const allowedRoomIds: string[][] = [];
    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: {
          decide: async (input) => {
            allowedRoomIds.push(input.allowedRoomIds ?? []);
            activeDecisions += 1;
            maxActiveDecisions = Math.max(maxActiveDecisions, activeDecisions);
            await new Promise((resolve) => setTimeout(resolve, 20));
            activeDecisions -= 1;
            return { type: "move", roomId: input.allowedRoomIds?.[0], intent: "test room choice" };
          },
        },
      },
      new Map(),
      () => false,
      { random: new SeededRandom(19) },
    );

    expect(allowedRoomIds.length).toBeGreaterThanOrEqual(1);
    expect(allowedRoomIds.length).toBeLessThanOrEqual(4);
    expect(allowedRoomIds.every((roomIds) => roomIds.length > 0)).toBe(true);
    expect(maxActiveDecisions).toBe(allowedRoomIds.length);
    expect(
      world.snapshot().recentEvents.filter((event) => event.type === "gameFlow" && /^asking .+ to move$/.test(event.message)),
    ).toHaveLength(allowedRoomIds.length);
  });

  it("spaces move decisions by at least half a second", async () => {
    const moveVenue: VenueLayout = {
      rooms: [
        { id: "room-a", label: "Room A", kind: "lounge", spotIds: ["a1", "a2", "a3", "a4"], neighborIds: ["room-b"] },
        { id: "room-b", label: "Room B", kind: "lounge", spotIds: ["b1", "b2", "b3", "b4"], neighborIds: ["room-a"] },
      ],
      spots: [
        { id: "a1", roomId: "room-a", label: "A1", position: { x: 1, y: 1 } },
        { id: "a2", roomId: "room-a", label: "A2", position: { x: 2, y: 1 } },
        { id: "a3", roomId: "room-a", label: "A3", position: { x: 3, y: 1 } },
        { id: "a4", roomId: "room-a", label: "A4", position: { x: 4, y: 1 } },
        { id: "b1", roomId: "room-b", label: "B1", position: { x: 1, y: 2 } },
        { id: "b2", roomId: "room-b", label: "B2", position: { x: 2, y: 2 } },
        { id: "b3", roomId: "room-b", label: "B3", position: { x: 3, y: 2 } },
        { id: "b4", roomId: "room-b", label: "B4", position: { x: 4, y: 2 } },
      ],
      spotLinks: [],
      roomPaths: [],
    };
    const world = new GridWorld({ width: 8, height: 8 }, {}, moveVenue);
    for (let index = 0; index < 4; index += 1) {
      world.addCog({
        name: `Mover ${index}`,
        color: "red",
        controllerId: "llm",
        location: { roomId: "room-a", spotId: `a${index + 1}` },
      });
    }

    const controllers = {
      stub: { decide: async () => ({ type: "wait" }) },
      wander: { decide: async () => ({ type: "wait" }) },
      llm: {
        decide: async (input) => ({ type: "move", roomId: input.allowedRoomIds?.[0], intent: "test room choice" }),
      },
    } as const;

    await tickWorld(world, controllers, new Map(), () => false, { random: new SeededRandom(37) });
    expect(moveAskEvents(world.snapshot())).toHaveLength(1);

    await tickWorld(world, controllers, new Map(), () => false, { random: new SeededRandom(50) });
    expect(moveAskEvents(world.snapshot())).toHaveLength(2);
  });

  it("gives thirty-second idle cogs move chances even when move asks are cooling down", async () => {
    const world = new GridWorld({ width: 8, height: 8 }, {}, venue);
    const ada = world.addCog({
      name: "Ada",
      color: "red",
      controllerId: "llm",
      location: { roomId: "room-a", spotId: "a1" },
    });
    const babbage = world.addCog({
      name: "Babbage",
      color: "red",
      controllerId: "llm",
      location: { roomId: "room-a", spotId: "a2" },
    });
    for (let tick = 0; tick < secondsToSimulationTicks(30); tick += 1) {
      await world.step(new Map());
    }
    world.recordGameFlow("asking Ada to move", ada.id);

    const decisions: string[] = [];
    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: {
          decide: async (input) => {
            decisions.push(input.observation.cog.name);
            return { type: "move", roomId: input.allowedRoomIds?.[0], intent: "idle priority" };
          },
        },
      },
      new Map(),
      () => false,
      { random: new SeededRandom(52) },
    );

    expect(decisions).toEqual(["Ada", "Babbage"]);
    expect(world.snapshot().cogs.find((cog) => cog.id === ada.id)?.moving?.to.roomId).toBe("room-b");
    expect(world.snapshot().cogs.find((cog) => cog.id === babbage.id)?.moving?.to.roomId).toBe("room-b");
  });

  it("prioritizes a cog with a fresh profile prompt change for the next move", async () => {
    const world = new GridWorld({ width: 8, height: 8 }, {}, venue);
    const ada = world.addCog({
      name: "Ada",
      behaviorPrompt: "Stay put.",
      color: "red",
      controllerId: "llm",
      location: { roomId: "room-a", spotId: "a1" },
    });
    world.addCog({
      name: "Babbage",
      color: "red",
      controllerId: "llm",
      location: { roomId: "room-a", spotId: "a2" },
    });
    await world.step(new Map());
    world.updateCogProfile(ada.id, {
      behaviorPrompt: "Find a better room.",
      attributes: ada.attributes,
      defensiveTrait: ada.defensiveTrait,
      activeTrait: ada.activeTrait,
      personalGoal: ada.personalGoal,
    });

    const decisions: string[] = [];
    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: {
          decide: async (input) => {
            decisions.push(input.observation.cog.name);
            return { type: "move", roomId: input.allowedRoomIds?.[0], intent: "prompt changed" };
          },
        },
      },
      new Map(),
      () => false,
      { random: new SeededRandom(53) },
    );

    expect(decisions).toEqual(["Ada"]);
    expect(world.snapshot().cogs.find((cog) => cog.id === ada.id)?.moving?.to.roomId).toBe("room-b");
  });

  it("prioritizes a cog with a fresh player prompt message for the next move", async () => {
    const world = new GridWorld({ width: 8, height: 8 }, {}, venue);
    const ada = world.addCog({
      name: "Ada",
      color: "red",
      controllerId: "llm",
      location: { roomId: "room-a", spotId: "a1" },
    });
    world.addCog({
      name: "Babbage",
      color: "red",
      controllerId: "llm",
      location: { roomId: "room-a", spotId: "a2" },
    });
    await world.step(new Map());
    world.recordCogConversation(ada.id, [
      { role: "user", content: "Manual keyboard control selected Ada." },
      { role: "assistant", content: JSON.stringify({ type: "wait", intent: "player steer: find a better room" }) },
    ]);

    const decisions: string[] = [];
    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: {
          decide: async (input) => {
            decisions.push(input.observation.cog.name);
            return { type: "move", roomId: input.allowedRoomIds?.[0], intent: "player prompt" };
          },
        },
      },
      new Map(),
      () => false,
      { random: new SeededRandom(54) },
    );

    expect(decisions).toEqual(["Ada"]);
    expect(world.snapshot().cogs.find((cog) => cog.id === ada.id)?.moving?.to.roomId).toBe("room-b");
  });

  it("prioritizes a poked cog for the next debate", async () => {
    const world = new GridWorld({ width: 8, height: 8 }, {}, venue);
    const ada = world.addCog({
      name: "Ada",
      color: "red",
      controllerId: "stub",
      location: { roomId: "room-a", spotId: "a1" },
    });
    const babbage = world.addCog({
      name: "Babbage",
      color: "blue",
      controllerId: "stub",
      location: { roomId: "room-a", spotId: "a2" },
    });
    world.pokeCog(babbage.id);

    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: { decide: async () => ({ type: "wait" }) },
      },
      new Map(),
      () => false,
      { random: new SeededRandom(55) },
    );

    expect(world.snapshot().recentEvents.findLast((event) => event.type === "debateStart")).toMatchObject({
      actorId: babbage.id,
      targetId: ada.id,
    });
  });

  it("prioritizes a poked cog for the next move when no debate is available", async () => {
    const world = new GridWorld({ width: 8, height: 8 }, {}, venue);
    const ada = world.addCog({
      name: "Ada",
      color: "red",
      controllerId: "llm",
      location: { roomId: "room-a", spotId: "a1" },
    });
    world.addCog({
      name: "Babbage",
      color: "red",
      controllerId: "llm",
      location: { roomId: "room-a", spotId: "a2" },
    });
    await world.step(new Map());
    world.pokeCog(ada.id);

    const decisions: string[] = [];
    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: {
          decide: async (input) => {
            decisions.push(input.observation.cog.name);
            return { type: "move", roomId: input.allowedRoomIds?.[0], intent: "poked" };
          },
        },
      },
      new Map(),
      () => false,
      { random: new SeededRandom(56) },
    );

    expect(decisions).toEqual(["Ada"]);
    expect(world.snapshot().cogs.find((cog) => cog.id === ada.id)?.moving?.to.roomId).toBe("room-b");
  });

  it("asks several cooldown-limited cogs to move in disco mode", async () => {
    const moveVenue: VenueLayout = {
      rooms: [
        { id: "room-a", label: "Room A", kind: "lounge", spotIds: ["a1", "a2", "a3", "a4"], neighborIds: ["room-b"] },
        { id: "room-b", label: "Room B", kind: "lounge", spotIds: ["b1", "b2", "b3", "b4"], neighborIds: ["room-a"] },
      ],
      spots: [
        { id: "a1", roomId: "room-a", label: "A1", position: { x: 1, y: 1 } },
        { id: "a2", roomId: "room-a", label: "A2", position: { x: 2, y: 1 } },
        { id: "a3", roomId: "room-a", label: "A3", position: { x: 3, y: 1 } },
        { id: "a4", roomId: "room-a", label: "A4", position: { x: 4, y: 1 } },
        { id: "b1", roomId: "room-b", label: "B1", position: { x: 1, y: 2 } },
        { id: "b2", roomId: "room-b", label: "B2", position: { x: 2, y: 2 } },
        { id: "b3", roomId: "room-b", label: "B3", position: { x: 3, y: 2 } },
        { id: "b4", roomId: "room-b", label: "B4", position: { x: 4, y: 2 } },
      ],
      spotLinks: [],
      roomPaths: [],
    };
    const world = new GridWorld({ width: 8, height: 8 }, { roomMoveCooldownTicks: secondsToSimulationTicks(60) }, moveVenue);
    const cogs = Array.from({ length: 4 }, (_, index) =>
      world.addCog({
        name: `Dancer ${index}`,
        color: "red",
        controllerId: "llm",
        location: { roomId: "room-a", spotId: `a${index + 1}` },
      })
    );
    await world.step(new Map<string, CogAction>(cogs.map((cog) => [cog.id, { type: "move", roomId: "room-b" }])));
    await stepUntilNotMoving(world, cogs[0].id);
    expect(world.snapshot().cogs.every((cog) => cog.location?.roomId === "room-b")).toBe(true);

    let moveDecisions = 0;
    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: {
          decide: async (input) => {
            moveDecisions += 1;
            return { type: "move", roomId: input.allowedRoomIds?.[0], intent: "disco dancing" };
          },
        },
      },
      new Map(),
      () => false,
      { discoMode: true, random: new SeededRandom(51) },
    );

    expect(moveDecisions).toBe(4);
    expect(moveAskEvents(world.snapshot())).toHaveLength(4);
    expect(world.snapshot().cogs.filter((cog) => cog.moving)).toHaveLength(4);
  });

  it("asks the longest-idle eligible cog to move", async () => {
    const moveVenue: VenueLayout = {
      rooms: [
        { id: "room-a", label: "Room A", kind: "lounge", spotIds: ["a1", "a2"], neighborIds: ["room-b"] },
        { id: "room-b", label: "Room B", kind: "lounge", spotIds: ["b1", "b2"], neighborIds: ["room-a"] },
      ],
      spots: [
        { id: "a1", roomId: "room-a", label: "A1", position: { x: 1, y: 1 } },
        { id: "a2", roomId: "room-a", label: "A2", position: { x: 2, y: 1 } },
        { id: "b1", roomId: "room-b", label: "B1", position: { x: 1, y: 2 } },
        { id: "b2", roomId: "room-b", label: "B2", position: { x: 2, y: 2 } },
      ],
      spotLinks: [],
      roomPaths: [],
    };
    const world = new GridWorld({ width: 8, height: 8 }, {}, moveVenue);
    const recentMover = world.addCog({
      name: "Recent Mover",
      color: "red",
      controllerId: "llm",
      location: { roomId: "room-a", spotId: "a1" },
    });
    const idleMover = world.addCog({
      name: "Idle Mover",
      color: "red",
      controllerId: "llm",
      location: { roomId: "room-a", spotId: "a2" },
    });

    world.recordGameFlow("activity for Idle Mover", idleMover.id);
    await world.step(new Map());
    world.recordGameFlow("activity for Recent Mover", recentMover.id);
    await world.step(new Map());

    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: {
          decide: async (input) => ({ type: "move", roomId: input.allowedRoomIds?.[0], intent: "test room choice" }),
        },
      },
      new Map(),
      () => false,
      { random: new SeededRandom(1) },
    );

    const ask = moveAskEvents(world.snapshot()).at(-1);
    expect(ask?.actorId).toBe(idleMover.id);
    expect(world.snapshot().cogs.find((cog) => cog.id === idleMover.id)?.moving?.to.roomId).toBe("room-b");
  });

  it("asks under-five-minute cogs to move before older eligible cogs", async () => {
    const moveVenue: VenueLayout = {
      rooms: [
        { id: "room-a", label: "Room A", kind: "lounge", spotIds: ["a1", "a2"], neighborIds: ["room-b"] },
        { id: "room-b", label: "Room B", kind: "lounge", spotIds: ["b1", "b2"], neighborIds: ["room-a"] },
      ],
      spots: [
        { id: "a1", roomId: "room-a", label: "A1", position: { x: 1, y: 1 } },
        { id: "a2", roomId: "room-a", label: "A2", position: { x: 2, y: 1 } },
        { id: "b1", roomId: "room-b", label: "B1", position: { x: 1, y: 2 } },
        { id: "b2", roomId: "room-b", label: "B2", position: { x: 2, y: 2 } },
      ],
      spotLinks: [],
      roomPaths: [],
    };
    let world = new GridWorld({ width: 8, height: 8 }, {}, moveVenue);
    const olderMover = world.addCog({
      name: "Older Mover",
      color: "red",
      controllerId: "llm",
      location: { roomId: "room-a", spotId: "a1" },
    });
    const newMover = world.addCog({
      name: "New Mover",
      color: "red",
      controllerId: "llm",
      location: { roomId: "room-a", spotId: "a2" },
    });
    world = worldWithCogPatches(world, {
      [olderMover.id]: { ticksAlive: secondsToSimulationTicks(5 * 60) },
      [newMover.id]: { ticksAlive: secondsToSimulationTicks(10) },
    });

    await tickWorld(
      world,
      {
        stub: { decide: async () => ({ type: "wait" }) },
        wander: { decide: async () => ({ type: "wait" }) },
        llm: {
          decide: async (input) => ({ type: "move", roomId: input.allowedRoomIds?.[0], intent: "test room choice" }),
        },
      },
      new Map(),
      () => false,
      { random: new SeededRandom(1) },
    );

    const ask = moveAskEvents(world.snapshot()).at(-1);
    expect(ask?.actorId).toBe(newMover.id);
    expect(world.snapshot().cogs.find((cog) => cog.id === newMover.id)?.moving?.to.roomId).toBe("room-b");
    expect(world.snapshot().cogs.find((cog) => cog.id === olderMover.id)?.moving).toBeUndefined();
  });

  it("does not ask another cog to move when four cogs are already moving", async () => {
    const moveVenue: VenueLayout = {
      rooms: [
        { id: "room-a", label: "Room A", kind: "lounge", spotIds: ["a1", "a2", "a3", "a4", "a5"], neighborIds: ["room-b"] },
        { id: "room-b", label: "Room B", kind: "lounge", spotIds: ["b1", "b2", "b3", "b4", "b5"], neighborIds: ["room-a"] },
      ],
      spots: [
        { id: "a1", roomId: "room-a", label: "A1", position: { x: 1, y: 1 } },
        { id: "a2", roomId: "room-a", label: "A2", position: { x: 2, y: 1 } },
        { id: "a3", roomId: "room-a", label: "A3", position: { x: 3, y: 1 } },
        { id: "a4", roomId: "room-a", label: "A4", position: { x: 4, y: 1 } },
        { id: "a5", roomId: "room-a", label: "A5", position: { x: 5, y: 1 } },
        { id: "b1", roomId: "room-b", label: "B1", position: { x: 1, y: 2 } },
        { id: "b2", roomId: "room-b", label: "B2", position: { x: 2, y: 2 } },
        { id: "b3", roomId: "room-b", label: "B3", position: { x: 3, y: 2 } },
        { id: "b4", roomId: "room-b", label: "B4", position: { x: 4, y: 2 } },
        { id: "b5", roomId: "room-b", label: "B5", position: { x: 5, y: 2 } },
      ],
      spotLinks: [],
      roomPaths: [],
    };
    const world = new GridWorld({ width: 8, height: 8 }, {}, moveVenue);
    const cogs = Array.from({ length: 5 }, (_, index) =>
      world.addCog({
        name: `Mover ${index}`,
        color: "red",
        controllerId: "llm",
        location: { roomId: "room-a", spotId: `a${index + 1}` },
      })
    );
    const controllers = {
      stub: { decide: async () => ({ type: "wait" }) },
      wander: { decide: async () => ({ type: "wait" }) },
      llm: {
        decide: async (input) => ({ type: "move", roomId: input.allowedRoomIds?.[0], intent: "test room choice" }),
      },
    } as const;

    await world.step(new Map<string, CogAction>(
      cogs.slice(0, 4).map((cog) => [cog.id, { type: "move", roomId: "room-b" }]),
    ));
    expect(world.snapshot().cogs.filter((cog) => cog.moving)).toHaveLength(4);

    await tickWorld(world, controllers, new Map(), () => false, { random: new SeededRandom(37) });

    expect(world.snapshot().cogs.filter((cog) => cog.moving)).toHaveLength(4);
    expect(world.snapshot().cogs.find((cog) => cog.id === cogs[4].id)?.moving).toBeUndefined();
    expect(moveAskEvents(world.snapshot())).toHaveLength(0);
  });
});

function observationFor(cog: Cog, snapshot: WorldSnapshot): CogObservation {
  return {
    cog,
    dimensions: snapshot.dimensions,
    venue: snapshot.venue,
    visibleEntities: snapshot.cogs
      .filter((candidate) => candidate.id !== cog.id)
      .map((candidate) => ({
        kind: "cog" as const,
        id: candidate.id,
        name: candidate.name,
        position: candidate.position,
        location: candidate.location,
        color: candidate.color,
        debate: candidate.debate,
        spriteSheetKey: candidate.spriteSheetKey,
        spriteUrl: candidate.spriteUrl,
        spriteUrls: candidate.spriteUrls,
      })),
    visibleTerrain: [],
    visibleCells: [],
    recentEvents: [],
  };
}

function snapshotFor(cogs: Cog[], tick: number): WorldSnapshot {
  return {
    tick,
    dimensions: { width: 10, height: 10 },
    venue,
    cogs,
    objects: [],
    terrain: [],
    recentEvents: [],
  };
}

async function stepUntilNotMoving(
  world: GridWorld,
  cogId: string,
  maxSteps = legacyHalfSecondTicksToSimulationTicks(80),
): Promise<WorldSnapshot> {
  let snapshot = world.snapshot();
  for (let step = 0; step <= maxSteps; step += 1) {
    const cog = snapshot.cogs.find((candidate) => candidate.id === cogId);
    if (!cog?.moving) {
      return snapshot;
    }
    snapshot = await world.step(new Map());
  }
  throw new Error(`Cog ${cogId} stayed moving after ${maxSteps} ticks`);
}

function activeDebateCount(snapshot: WorldSnapshot): number {
  const pairKeys = new Set<string>();
  for (const cog of snapshot.cogs) {
    if (!cog.debate) {
      continue;
    }

    pairKeys.add([cog.id, cog.debate.opponentId].sort().join(":"));
  }
  return pairKeys.size;
}

function moveAskEvents(snapshot: WorldSnapshot): WorldSnapshot["recentEvents"] {
  return snapshot.recentEvents.filter((event) => event.type === "gameFlow" && /^asking .+ to move$/.test(event.message));
}

function worldWithCogPatches(world: GridWorld, patches: Record<string, Partial<Cog>>): GridWorld {
  const state = world.exportState();
  return GridWorld.fromState({
    ...state,
    cogs: state.cogs.map((cog) => ({ ...cog, ...(patches[cog.id] ?? {}) })),
  });
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function cog(input: Partial<Cog> & Pick<Cog, "id" | "color">): Cog {
  return {
    id: input.id,
    name: input.name ?? input.id,
    behaviorPrompt: "",
    position: input.position ?? { x: 1, y: 1 },
    location: input.location,
    spriteSheetKey: "cog-default",
    attributes: {},
    color: input.color,
    defensiveTrait: "stubborn",
    activeTrait: "passionate",
    personalGoal: "underdog",
    personalScore: 0,
    goalScores: [],
    stats: { argumentsWon: 0, argumentsLost: 0, teamFlips: 0 },
    certainty: 100,
    debate: input.debate,
    controllerId: "llm",
    movementCooldown: input.movementCooldown ?? 0,
    lastVenueMoveTick: input.lastVenueMoveTick,
    conversationLog: [],
  };
}
