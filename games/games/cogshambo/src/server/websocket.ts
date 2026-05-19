import type { Server } from "node:http";
import { WebSocket, WebSocketServer } from "ws";
import { clientMessageSchema, type ServerMessage } from "../shared/protocol.js";
import type { GameConfig } from "../shared/rules.js";
import type {
  Cog,
  CogAction,
  CogDecisionInput,
  CogActionMetadata,
  CogObservation,
  ControllerId,
  DebateTactic,
  Direction,
  ServerStatus,
  WorldSnapshot,
} from "../shared/types.js";
import { secondsToSimulationTicks } from "../shared/timing.js";
import type { ControllerRegistry } from "./controllers/cog-controller.js";
import { buildControllerDecisionPrompt } from "./controllers/decision-prompt.js";
import { fallbackTacticForCog } from "./controllers/fallback-tactic.js";
import { compactWorldSnapshot } from "./client-snapshot.js";
import { venueRoomSection, venueSectionForX, type VenueSection } from "../shared/venue.js";
import type { SimulationControls } from "./simulation/control.js";
import { isEligibleDebateTarget } from "./simulation/debate-target.js";
import { SeededRandom } from "./simulation/random.js";
import type { CogMoveOptions, GridWorld } from "./simulation/world.js";
import type { WorldStateStore } from "./world-state-store.js";

export type AttachWorldSocketServerOptions = {
  server: Server;
  world: GridWorld;
  controllers: ControllerRegistry;
  controls: SimulationControls;
  worldStateStore?: WorldStateStore;
  tickMs: number;
  scripted?: boolean;
};

export type AttachedWorldSocketServer = {
  clientCount: () => number;
  broadcast: (message: ServerMessage) => void;
  close: () => Promise<void>;
};

export type TickWorldOptions = {
  controllerDecisionStats?: ControllerDecisionStats;
  controllerDecisionTimeoutMs?: number;
  discoMode?: boolean;
  random?: SeededRandom;
  scripted?: boolean;
};

export type ControllerDecisionStats = {
  llmMoveDecisions: number;
  llmTimedOutMoves: number;
};

export const DEFAULT_CONTROLLER_DECISION_TIMEOUT_MS = 5_000;
export const MAX_WEBSOCKET_BUFFERED_BYTES = 4 * 1024 * 1024;
const MAX_MOVING_COGS = 4;
const DEBATE_START_SPACING_TICKS = secondsToSimulationTicks(3);
const MOVE_ASK_SPACING_TICKS = secondsToSimulationTicks(0.5);
const IDLE_PRIORITY_TICKS = secondsToSimulationTicks(30);
const NEW_COG_MOVE_PRIORITY_TICKS = secondsToSimulationTicks(5 * 60);
const LOW_DEBATE_PRIORITY_COUNT = 3;
const PLAYER_STEER_INTENT_PREFIX = "player steer:";
const MAP_SECTIONS: readonly VenueSection[] = ["west", "center", "east"];

export function attachWorldSocketServer({
  server,
  world,
  controllers,
  controls,
  worldStateStore,
  tickMs,
  scripted = true,
}: AttachWorldSocketServerOptions): AttachedWorldSocketServer {
  const socketServer = new WebSocketServer({ server, path: "/ws" });
  let closed = false;
  let tickInFlight = false;
  let closePromise: Promise<void> | undefined;
  let worldStatePersistenceFailed = false;
  const manualActions = new Map<string, CogAction>();
  const controllerDecisionStats: ControllerDecisionStats = { llmMoveDecisions: 0, llmTimedOutMoves: 0 };

  const clientCount = (): number =>
    Array.from(socketServer.clients).filter((client) => client.readyState === WebSocket.OPEN).length;

  const status = (snapshot = world.snapshot()): ServerStatus => {
    return {
      tick: snapshot.tick,
      cogCount: snapshot.cogs.length,
      clientCount: clientCount(),
      controllerMode: scripted ? controllerMode(snapshot) : "llm",
      ...controllerDecisionStatus(controllerDecisionStats),
      ...controls.statusPatch(),
    };
  };

  const broadcast = (message: ServerMessage): void => {
    if (closed) {
      return;
    }

    const encoded = JSON.stringify(message);
    socketServer.clients.forEach((client) => {
      sendEncoded(client, encoded);
    });
  };

  const send = (socket: WebSocket, message: ServerMessage): void => {
    if (!closed) {
      sendEncoded(socket, JSON.stringify(message));
    }
  };

  const broadcastSnapshotAndStatus = (snapshot: WorldSnapshot): void => {
    broadcast({ type: "snapshot", snapshot });
    broadcast({ type: "serverStatus", status: status(snapshot) });
  };

  const unsubscribeControls = controls.onChange(() => {
    broadcast({ type: "serverStatus", status: status() });
  });

  socketServer.on("connection", (socket) => {
    const snapshot = compactWorldSnapshot(world.snapshot());
    send(socket, { type: "snapshot", snapshot });
    send(socket, { type: "serverStatus", status: status(snapshot) });

    socket.on("message", (data) => {
      const message = parseClientMessage(data.toString());
      if (message?.type === "hello") {
        send(socket, { type: "serverStatus", status: status() });
        return;
      }

      if (message?.type === "manualMove") {
        manualActions.set(message.cogId, {
          type: "move",
          direction: message.direction,
          intent: "manual keyboard move",
        });
        if (!controls.isPlaying()) {
          controls.step();
        }
        void runTick();
        return;
      }

      if (message?.type === "manualAction") {
        manualActions.set(message.cogId, { intent: "manual roster choice", ...message.action } as CogAction);
        if (!controls.isPlaying()) {
          controls.step();
        }
        void runTick();
        return;
      }

    });
  });

  const runTick = async (): Promise<void> => {
    if (closed || tickInFlight || !controls.consumeStep()) {
      return;
    }

    tickInFlight = true;
    try {
      const snapshot = await tickWorld(world, controllers, manualActions, () => closed, {
        controllerDecisionStats,
        controllerDecisionTimeoutMs: DEFAULT_CONTROLLER_DECISION_TIMEOUT_MS,
        discoMode: controls.discoMode(),
        scripted,
      });
      if (!snapshot || closed) {
        return;
      }

      try {
        worldStateStore?.save(world);
        if (worldStatePersistenceFailed) {
          console.warn("World state persistence resumed.");
          worldStatePersistenceFailed = false;
        }
      } catch (error: unknown) {
        if (!worldStatePersistenceFailed) {
          console.error("World state persistence failed; simulation will continue without saving.", error);
          worldStatePersistenceFailed = true;
        }
      }
      broadcastSnapshotAndStatus(compactWorldSnapshot(snapshot));
    } catch (error: unknown) {
      console.error("Simulation tick failed", error);
      if (!scripted) {
        setTimeout(() => {
          throw error instanceof Error ? error : new Error("Simulation tick failed");
        }, 0);
      }
    } finally {
      tickInFlight = false;
    }
  };

  const interval = setInterval(() => {
    void runTick();
  }, tickMs);

  return {
    clientCount,
    broadcast,
    close: () => {
      if (closePromise) {
        return closePromise;
      }

      closed = true;
      clearInterval(interval);
      unsubscribeControls();

      closePromise = closeClients(socketServer).then(
        () =>
          new Promise<void>((resolve, reject) => {
            socketServer.close((error) => (error ? reject(error) : resolve()));
          }),
      );
      return closePromise;
    },
  };
}

export function sendEncoded(socket: WebSocket, encoded: string): boolean {
  if (socket.readyState !== WebSocket.OPEN) {
    return false;
  }

  if (socket.bufferedAmount > MAX_WEBSOCKET_BUFFERED_BYTES) {
    socket.terminate();
    return false;
  }

  socket.send(encoded, (error) => {
    if (error) {
      socket.terminate();
    }
  });
  return true;
}

function parseClientMessage(data: string) {
  try {
    return clientMessageSchema.safeParse(JSON.parse(data)).data;
  } catch {
    return undefined;
  }
}

export async function tickWorld(
  world: GridWorld,
  controllers: ControllerRegistry,
  manualActions: Map<string, CogAction>,
  isClosed: () => boolean,
  options: TickWorldOptions = {},
): Promise<WorldSnapshot | undefined> {
  const snapshot = world.snapshot();
  const gameConfig = world.gameConfig();
  const upcomingTick = snapshot.tick + 1;
  const discoMode = options.discoMode ?? false;
  const scripted = options.scripted ?? true;
  const random = options.random ?? new SeededRandom(0xc09_5a4b0 ^ upcomingTick);
  const controllerDecisionTimeoutMs = options.controllerDecisionTimeoutMs ?? DEFAULT_CONTROLLER_DECISION_TIMEOUT_MS;
  const controllerDecisionStats = options.controllerDecisionStats;
  const actions = new Map<string, CogAction>();
  const gameFlow: GameFlowEntry[] = [];
  const activeCogIds = new Set(snapshot.cogs.map((cog) => cog.id));
  const moveOptionsContext = { ignoreRoomMoveCooldown: discoMode };
  for (const cogId of manualActions.keys()) {
    if (!activeCogIds.has(cogId)) {
      manualActions.delete(cogId);
    }
  }

  const controllerDecisions: ScheduledControllerDecision[] = [];
  for (const cog of snapshot.cogs) {
    const manualAction = manualActions.get(cog.id);
    if (manualAction) {
      const observation = world.getObservation(cog.id);
      const moveOptions = world.moveOptionsFor(cog.id, moveOptionsContext);
      const allowedActions = allowedActionsFor(observation, upcomingTick, moveOptions);
      if (!manualActionCanRunNow(manualAction, observation, allowedActions, moveOptions)) {
        if (shouldQueueManualAction(manualAction, observation)) {
          actions.set(cog.id, { type: "wait", intent: "queued manual roster choice" });
          continue;
        }

        manualActions.delete(cog.id);
      } else {
        manualActions.delete(cog.id);
      }
      const action = manualAction.type === "move" && manualAction.direction
        ? sanitizeAction(manualAction, observation, allowedActions)
        : sanitizeAction(manualAction, observation, allowedActions, moveOptions);
      actions.set(cog.id, action);
      world.recordCogConversation(cog.id, [
        { role: "user", content: `Manual keyboard control selected ${cog.name}.` },
        { role: "assistant", content: actionResponse(action) },
      ]);
      continue;
    }
  }

  if (scripted) {
    const unavailableCogIds = discoMode
      ? new Set<string>(actions.keys())
      : scheduleAvailableDebates(world, snapshot, actions, random, gameFlow, upcomingTick);
    const moveCandidates: ScheduledControllerDecision[] = [];
    for (const cog of snapshot.cogs) {
      if (actions.has(cog.id)) {
        continue;
      }

      const observation = world.getObservation(cog.id);
      if (observation.cog.debate) {
        if (discoMode) {
          continue;
        }

        const allowedActions = viableControllerActionsFor(observation, false, upcomingTick);
        const scheduled = scheduleControllerDecision(cog, observation, allowedActions, controllers);
        if (scheduled) {
          controllerDecisions.push(scheduled);
        }
        continue;
      }

      if (unavailableCogIds.has(cog.id)) {
        continue;
      }

      const moveOptions = world.moveOptionsFor(cog.id, moveOptionsContext);
      if (!humanSteerAllowsMovement(cog, snapshot, moveOptions)) {
        continue;
      }

      const allowedActions = viableControllerActionsFor(observation, hasMoveOptions(moveOptions), upcomingTick);
      const scheduled = scheduleControllerDecision(cog, observation, allowedActions, controllers, moveOptions);
      if (scheduled) {
        moveCandidates.push(scheduled);
      }
    }

    const availableMoveSlots = Math.max(0, MAX_MOVING_COGS - movingCogCount(snapshot) - pendingMoveActionCount(actions));
    const moveAskCoolingDown = !discoMode && moveAskIsCoolingDown(snapshot, upcomingTick);
    const scheduledMoveDecisions = moveAskCoolingDown && !hasPriorityMoveCandidate(snapshot, moveCandidates, upcomingTick)
      ? []
      : chooseMoveCandidates(snapshot, moveCandidates, availableMoveSlots, discoMode ? availableMoveSlots : 1, upcomingTick);
    for (const decision of scheduledMoveDecisions) {
      gameFlow.push({
        actorId: decision.cog.id,
        message: `asking ${decision.cog.name} to move`,
      });
    }
    controllerDecisions.push(...scheduledMoveDecisions);
  } else {
    const unavailableCogIds = discoMode
      ? new Set<string>(actions.keys())
      : scheduleAvailableDebates(world, snapshot, actions, random, gameFlow, upcomingTick);
    for (const cog of snapshot.cogs) {
      if (actions.has(cog.id)) {
        continue;
      }

      const observation = world.getObservation(cog.id);
      if (observation.cog.debate) {
        if (discoMode) {
          continue;
        }

        const allowedActions = viableControllerActionsFor(observation, false, upcomingTick);
        const scheduled = scheduleControllerDecision(cog, observation, allowedActions, controllers);
        if (scheduled) {
          controllerDecisions.push(scheduled);
        }
        continue;
      }

      if (unavailableCogIds.has(cog.id)) {
        continue;
      }

      const moveOptions = world.moveOptionsFor(cog.id, moveOptionsContext);
      const allowedActions = meaningfulControllerActionsFor(allowedActionsFor(observation, upcomingTick, moveOptions));
      const scheduled = scheduleControllerDecision(cog, observation, allowedActions, controllers, moveOptions, "llm");
      if (scheduled) {
        controllerDecisions.push(scheduled);
      }
    }
  }

  await Promise.all(
    controllerDecisions.map(async ({ cog, observation, allowedActions, moveOptions, controller, controllerId }) => {
      if (!controller) {
        if (!scripted) {
          throw new Error(`missing LLM controller while deciding for ${cog.name}`);
        }
        const action: CogAction = { type: "wait", intent: `missing controller: ${cog.controllerId}` };
        actions.set(cog.id, action);
        world.recordCogConversation(cog.id, [
          { role: "user", content: decisionPrompt(snapshot.tick, observation, ["wait"], moveOptions, gameConfig) },
          { role: "assistant", content: actionResponse(action) },
        ]);
        return;
      }

      try {
        const tracksLlmMove = controllerId === "llm" && allowedActions.includes("move");
        if (tracksLlmMove && controllerDecisionStats) {
          controllerDecisionStats.llmMoveDecisions++;
        }

        const input: CogDecisionInput = {
          tick: snapshot.tick,
          observation,
          allowedActions,
          allowedRoomIds: moveOptions?.roomIds,
          allowedDirections: moveOptions?.directions,
          gameConfig,
        };
        const decision = await controllerDecisionWithTimeout(controller, input, {
          allowedActions,
          moveOptions,
          observation,
          random,
          timeoutMs: controllerDecisionTimeoutMs,
        });
        const sanitizedAction = sanitizeAction(
          decision.action,
          observation,
          allowedActions,
          moveOptions,
          { allowDebateTarget: false },
        );
        const action = decision.timedOut ? { ...sanitizedAction, timedOut: true } : sanitizedAction;
        if (tracksLlmMove && decision.timedOut && action.type === "move" && controllerDecisionStats) {
          controllerDecisionStats.llmTimedOutMoves++;
        }
        actions.set(cog.id, action);
        world.recordCogConversation(cog.id, [
          { role: "user", content: decisionPrompt(snapshot.tick, observation, allowedActions, moveOptions, gameConfig) },
          { role: "assistant", content: actionResponse(action) },
        ]);
      } catch (error) {
        if (!scripted) {
          throw error;
        }
        const action: CogAction = {
          type: "wait",
          intent: error instanceof Error ? `controller error: ${error.message}` : "controller error",
        };
        actions.set(cog.id, action);
        world.recordCogConversation(cog.id, [
          { role: "user", content: `Controller ${cog.controllerId} failed while deciding for ${cog.name}.` },
          { role: "assistant", content: actionResponse(action) },
        ]);
      }
    }),
  );

  if (isClosed()) {
    return undefined;
  }

  if (!discoMode) {
    enforceDebateStartSpacing(snapshot, upcomingTick, actions);
    resolveRequestedDebates(world, snapshot, actions, random, gameFlow);
  }
  await world.step(actions, { debatesEnabled: !discoMode, ignoreRoomMoveCooldown: discoMode });
  for (const entry of gameFlow) {
    world.recordGameFlow(entry.message, entry.actorId, entry.targetId);
  }
  return world.snapshot();
}

type ScheduledControllerDecision = {
  cog: Cog;
  observation: CogObservation;
  allowedActions: CogAction["type"][];
  moveOptions?: CogMoveOptions;
  controller: ControllerRegistry[ControllerId] | undefined;
  controllerId: ControllerId;
};

type GameFlowEntry = {
  actorId?: string;
  targetId?: string;
  message: string;
};

function scheduleControllerDecision(
  cog: Cog,
  observation: CogObservation,
  allowedActions: CogAction["type"][],
  controllers: ControllerRegistry,
  moveOptions?: CogMoveOptions,
  controllerId: ControllerId = cog.controllerId,
): ScheduledControllerDecision | undefined {
  if (allowedActions.length === 0) {
    return undefined;
  }

  return {
    cog,
    observation,
    allowedActions,
    moveOptions,
    controller: controllers[controllerId],
    controllerId,
  };
}

type ControllerDecisionResult = {
  action: CogAction;
  timedOut: boolean;
};

async function controllerDecisionWithTimeout(
  controller: NonNullable<ControllerRegistry[ControllerId]>,
  input: CogDecisionInput,
  context: {
    allowedActions: CogAction["type"][];
    moveOptions?: CogMoveOptions;
    observation: CogObservation;
    random: SeededRandom;
    timeoutMs: number;
  },
): Promise<ControllerDecisionResult> {
  const decisionPromise = Promise.resolve().then(() => controller.decide(input));
  decisionPromise.catch(() => undefined);

  let timeout: ReturnType<typeof setTimeout> | undefined;
  const timeoutPromise = new Promise<ControllerDecisionResult>((resolve) => {
    timeout = setTimeout(() => {
      resolve({
        action: controllerTimeoutFallbackAction(context),
        timedOut: true,
      });
    }, context.timeoutMs);
  });

  try {
    return await Promise.race([
      decisionPromise.then((action) =>
        controllerActionTimedOut(action, context.timeoutMs)
          ? { action: controllerTimeoutFallbackAction(context), timedOut: true }
          : { action, timedOut: false },
      ),
      timeoutPromise,
    ]);
  } finally {
    if (timeout) {
      clearTimeout(timeout);
    }
  }
}

function controllerActionTimedOut(action: CogAction, timeoutMs: number): boolean {
  return action.timedOut === true || Boolean(action.intent?.includes(`timed out after ${timeoutMs}ms`));
}

function controllerTimeoutFallbackAction({
  allowedActions,
  moveOptions,
  observation,
  random,
  timeoutMs,
}: {
  allowedActions: CogAction["type"][];
  moveOptions?: CogMoveOptions;
  observation: CogObservation;
  random: SeededRandom;
  timeoutMs: number;
}): CogAction {
  const intent = `controller timed out after ${timeoutMs}ms; randomly selected fallback`;
  const roomIds = moveOptions?.roomIds ?? [];
  const directions = moveOptions?.directions ?? [];

  if (allowedActions.includes("move") && roomIds.length > 0) {
    return { type: "move", roomId: random.choice(roomIds), intent, timedOut: true };
  }

  if (allowedActions.includes("move") && directions.length > 0) {
    return { type: "move", direction: random.choice(directions), intent, timedOut: true };
  }

  if (allowedActions.includes("chooseTactic") || observation.cog.debate) {
    return { type: "chooseTactic", tactic: random.choice(tactics), intent, timedOut: true };
  }

  if (allowedActions.includes("debate") && hasDebateTargets(observation)) {
    return { type: "debate", intent, timedOut: true };
  }

  return { type: "wait", intent, timedOut: true };
}

function controllerDecisionStatus(stats: ControllerDecisionStats): Pick<ServerStatus, "llmMoveDecisions" | "llmTimedOutMovePercent" | "llmTimedOutMoves"> {
  const llmTimedOutMovePercent = stats.llmMoveDecisions === 0
    ? 0
    : Math.round((stats.llmTimedOutMoves / stats.llmMoveDecisions) * 100);
  return {
    llmMoveDecisions: stats.llmMoveDecisions,
    llmTimedOutMovePercent,
    llmTimedOutMoves: stats.llmTimedOutMoves,
  };
}

function scheduleAvailableDebates(
  world: GridWorld,
  snapshot: WorldSnapshot,
  actions: Map<string, CogAction>,
  random: SeededRandom,
  gameFlow: GameFlowEntry[],
  upcomingTick: number,
): Set<string> {
  if (debateStartIsCoolingDown(snapshot, upcomingTick) || pendingDebateActionCount(actions) > 0) {
    return unavailableCogIdsForDebateScheduling(snapshot, actions);
  }

  scheduleHumanSteeredDebates(world, snapshot, actions, random, gameFlow);
  return scheduleDebateStarts(world, snapshot, actions, gameFlow);
}

function scheduleDebateStarts(
  world: GridWorld,
  snapshot: WorldSnapshot,
  actions: Map<string, CogAction>,
  gameFlow: GameFlowEntry[],
): Set<string> {
  const unavailableCogIds = new Set<string>(actions.keys());
  const unavailableDebateSections = new Set<VenueSection>();
  for (const cog of snapshot.cogs) {
    if (cog.moving) {
      unavailableCogIds.add(cog.id);
    }

    if (cog.debate) {
      unavailableCogIds.add(cog.id);
      markDebateSectionUnavailable(snapshot, cog, unavailableDebateSections);
    }
  }
  markPendingDebatesUnavailable(snapshot, actions, unavailableCogIds, unavailableDebateSections);

  const maxDebates = Math.max(1, Math.floor(world.gameConfig().maxDebatesPerTick));
  const availableDebateSlots = Math.max(0, maxDebates - pendingDebateActionCount(actions));
  if (availableDebateSlots === 0) {
    return unavailableCogIds;
  }

  const openSections = new Set(MAP_SECTIONS.filter((section) => !unavailableDebateSections.has(section)));
  if (openSections.size === 0) {
    return unavailableCogIds;
  }

  for (const cog of sortCogsByDebatePriority(snapshot, snapshot.cogs)) {
    const section = debateSectionForCog(snapshot, cog);
    if (
      !section ||
      !openSections.has(section) ||
      unavailableCogIds.has(cog.id) ||
      debateSectionIsUnavailable(snapshot, cog, unavailableDebateSections)
    ) {
      continue;
    }

    const target = sortCogsByDebatePriority(
      snapshot,
      world.debatePartnerIdsFor(cog.id).flatMap((candidateId) => {
        if (unavailableCogIds.has(candidateId)) {
          return [];
        }

        const target = snapshot.cogs.find((candidate) => candidate.id === candidateId);
        return target &&
          !debateSectionIsUnavailable(snapshot, target, unavailableDebateSections)
          ? [target]
          : [];
      }),
    )[0];
    if (!target) {
      continue;
    }

    markDebateSectionUnavailable(snapshot, cog, unavailableDebateSections);
    markDebateSectionUnavailable(snapshot, target, unavailableDebateSections);
    actions.set(cog.id, {
      type: "debate",
      targetId: target.id,
      intent: "game-selected debate",
    });
    gameFlow.push({
      actorId: cog.id,
      targetId: target.id,
      message: `starting debate between ${cog.name} and ${target.name}`,
    });
    unavailableCogIds.add(cog.id);
    unavailableCogIds.add(target.id);
    break;
  }

  return unavailableCogIds;
}

function scheduleHumanSteeredDebates(
  world: GridWorld,
  snapshot: WorldSnapshot,
  actions: Map<string, CogAction>,
  random: SeededRandom,
  gameFlow: GameFlowEntry[],
): void {
  const maxDebates = Math.max(1, Math.floor(world.gameConfig().maxDebatesPerTick));
  let availableDebateSlots = Math.min(
    1,
    Math.max(0, maxDebates - pendingDebateActionCount(actions)),
  );
  if (availableDebateSlots === 0) {
    return;
  }

  const unavailableCogIds = new Set<string>(actions.keys());
  const unavailableDebateSections = new Set<VenueSection>();
  for (const cog of snapshot.cogs) {
    if (cog.moving || cog.debate) {
      unavailableCogIds.add(cog.id);
    }
    if (cog.debate) {
      markDebateSectionUnavailable(snapshot, cog, unavailableDebateSections);
    }
  }
  markPendingDebatesUnavailable(snapshot, actions, unavailableCogIds, unavailableDebateSections);

  for (const cog of snapshot.cogs) {
    if (
      availableDebateSlots <= 0 ||
      unavailableCogIds.has(cog.id) ||
      debateSectionIsUnavailable(snapshot, cog, unavailableDebateSections)
    ) {
      continue;
    }

    const steer = humanSteerText(cog);
    if (!steer || !cueSuggestsConversation(steer)) {
      continue;
    }

    const targetId = humanSteeredDebateTargetId(world, snapshot, cog, steer, unavailableCogIds, unavailableDebateSections, random);
    const target = targetId ? snapshot.cogs.find((candidate) => candidate.id === targetId) : undefined;
    if (!targetId || !target) {
      continue;
    }

    actions.set(cog.id, {
      type: "debate",
      targetId,
      intent: cog.intent,
    });
    unavailableCogIds.add(cog.id);
    unavailableCogIds.add(targetId);
    markDebateSectionUnavailable(snapshot, cog, unavailableDebateSections);
    markDebateSectionUnavailable(snapshot, target, unavailableDebateSections);
    gameFlow.push({
      actorId: cog.id,
      targetId,
      message: `starting cued debate between ${cog.name} and ${target.name}`,
    });
    availableDebateSlots -= 1;
  }
}

function humanSteeredDebateTargetId(
  world: GridWorld,
  snapshot: WorldSnapshot,
  cog: Cog,
  steer: string,
  unavailableCogIds: ReadonlySet<string>,
  unavailableDebateSections: ReadonlySet<VenueSection>,
  random: SeededRandom,
): string | undefined {
  const partners = world.debatePartnerIdsFor(cog.id).filter((targetId) => {
    if (unavailableCogIds.has(targetId)) {
      return false;
    }

    const target = snapshot.cogs.find((candidate) => candidate.id === targetId);
    return Boolean(target && !debateSectionIsUnavailable(snapshot, target, unavailableDebateSections));
  });
  if (partners.length === 0) {
    return undefined;
  }

  const namedPartner = partners.find((targetId) => {
    const target = snapshot.cogs.find((candidate) => candidate.id === targetId);
    return Boolean(target && cueMentionsLabel(steer, target.name));
  });
  if (namedPartner) {
    return namedPartner;
  }

  if (partners.length === 1 || cueSuggestsGenericConversationTarget(steer)) {
    return shuffled(partners, random)[0];
  }

  return undefined;
}

function markPendingDebatesUnavailable(
  snapshot: WorldSnapshot,
  actions: ReadonlyMap<string, CogAction>,
  unavailableCogIds: Set<string>,
  unavailableDebateSections: Set<VenueSection>,
): void {
  for (const [actorId, action] of actions) {
    if (action.type !== "debate" || !action.targetId) {
      continue;
    }

    unavailableCogIds.add(actorId);
    const actor = snapshot.cogs.find((cog) => cog.id === actorId);
    if (actor) {
      markDebateSectionUnavailable(snapshot, actor, unavailableDebateSections);
    }

    unavailableCogIds.add(action.targetId);
    const target = snapshot.cogs.find((cog) => cog.id === action.targetId);
    if (target) {
      markDebateSectionUnavailable(snapshot, target, unavailableDebateSections);
    }
  }
}

function enforceDebateStartSpacing(
  snapshot: WorldSnapshot,
  upcomingTick: number,
  actions: Map<string, CogAction>,
): void {
  let remainingDebateStarts = debateStartIsCoolingDown(snapshot, upcomingTick) ? 0 : 1;
  for (const [cogId, action] of actions) {
    if (action.type !== "debate") {
      continue;
    }

    if (remainingDebateStarts > 0) {
      remainingDebateStarts -= 1;
      continue;
    }

    actions.set(cogId, debateStartSpacingFallback(action));
  }
}

function debateStartIsCoolingDown(snapshot: WorldSnapshot, upcomingTick: number): boolean {
  return snapshot.recentEvents.some(
    (event) =>
      event.type === "debateStart" &&
      upcomingTick - event.tick < DEBATE_START_SPACING_TICKS,
  );
}

function unavailableCogIdsForDebateScheduling(
  snapshot: WorldSnapshot,
  actions: ReadonlyMap<string, CogAction>,
): Set<string> {
  const unavailableCogIds = new Set<string>(actions.keys());
  const unavailableDebateSections = new Set<VenueSection>();
  for (const cog of snapshot.cogs) {
    if (cog.moving) {
      unavailableCogIds.add(cog.id);
    }

    if (cog.debate) {
      unavailableCogIds.add(cog.id);
      markDebateSectionUnavailable(snapshot, cog, unavailableDebateSections);
    }
  }
  markPendingDebatesUnavailable(snapshot, actions, unavailableCogIds, unavailableDebateSections);
  return unavailableCogIds;
}

function resolveRequestedDebates(
  world: GridWorld,
  snapshot: WorldSnapshot,
  actions: Map<string, CogAction>,
  random: SeededRandom,
  gameFlow: GameFlowEntry[],
): void {
  const unavailableCogIds = new Set<string>();
  const unavailableDebateSections = new Set<VenueSection>();
  for (const cog of snapshot.cogs) {
    if (cog.moving || cog.debate) {
      unavailableCogIds.add(cog.id);
    }
    if (cog.debate) {
      markDebateSectionUnavailable(snapshot, cog, unavailableDebateSections);
    }
  }
  markPendingDebatesUnavailable(snapshot, actions, unavailableCogIds, unavailableDebateSections);

  const requests = shuffled(
    Array.from(actions.entries()).filter((entry): entry is [string, Extract<CogAction, { type: "debate" }>] => {
      const [, action] = entry;
      return action.type === "debate" && !action.targetId;
    }),
    random,
  );

  for (const [cogId, action] of requests) {
    const cog = snapshot.cogs.find((candidate) => candidate.id === cogId);
    if (!cog || unavailableCogIds.has(cog.id) || debateSectionIsUnavailable(snapshot, cog, unavailableDebateSections)) {
      actions.set(cogId, debateRequestFallback(action));
      continue;
    }

    const targetId = shuffled(world.debatePartnerIdsFor(cog.id), random).find((candidateId) => {
      if (unavailableCogIds.has(candidateId)) {
        return false;
      }

      const target = snapshot.cogs.find((candidate) => candidate.id === candidateId);
      return Boolean(target && !debateSectionIsUnavailable(snapshot, target, unavailableDebateSections));
    });
    const target = targetId ? snapshot.cogs.find((candidate) => candidate.id === targetId) : undefined;
    if (!targetId || !target) {
      actions.set(cogId, debateRequestFallback(action));
      continue;
    }

    actions.set(cog.id, { ...action, targetId });
    actions.set(targetId, { type: "wait", intent: "game-selected debate participant" });
    unavailableCogIds.add(cog.id);
    unavailableCogIds.add(targetId);
    markDebateSectionUnavailable(snapshot, cog, unavailableDebateSections);
    markDebateSectionUnavailable(snapshot, target, unavailableDebateSections);
    gameFlow.push({
      actorId: cog.id,
      targetId,
      message: `starting debate between ${cog.name} and ${target.name}`,
    });
  }
}

function debateStartSpacingFallback(action: Extract<CogAction, { type: "debate" }>): CogAction {
  return {
    ...debateRequestFallback(action),
    intent: action.intent ? `${action.intent}; debate start cooldown` : "debate start cooldown",
  };
}

function debateRequestFallback(action: Extract<CogAction, { type: "debate" }>): CogAction {
  return {
    type: "wait",
    intent: action.intent ?? "no available debate opponent",
    ...(action.choiceNumber !== undefined ? { choiceNumber: action.choiceNumber } : {}),
    ...(action.thoughts !== undefined ? { thoughts: action.thoughts } : {}),
    ...(action.timedOut !== undefined ? { timedOut: action.timedOut } : {}),
  };
}

function debateSectionIsUnavailable(
  snapshot: WorldSnapshot,
  cog: Pick<Cog, "location" | "position">,
  unavailableSections: ReadonlySet<VenueSection>,
): boolean {
  const section = debateSectionForCog(snapshot, cog);
  return section !== undefined && unavailableSections.has(section);
}

function markDebateSectionUnavailable(
  snapshot: WorldSnapshot,
  cog: Pick<Cog, "location" | "position">,
  unavailableSections: Set<VenueSection>,
): void {
  const section = debateSectionForCog(snapshot, cog);
  if (section) {
    unavailableSections.add(section);
  }
}

function debateSectionForCog(snapshot: WorldSnapshot, cog: Pick<Cog, "location" | "position">): VenueSection | undefined {
  if (snapshot.venue && cog.location) {
    return venueRoomSection(cog.location.roomId, snapshot.dimensions, snapshot.venue);
  }

  return venueSectionForX(cog.position.x, snapshot.dimensions);
}

function pendingDebateActionCount(actions: ReadonlyMap<string, CogAction>): number {
  let count = 0;
  for (const action of actions.values()) {
    if (action.type === "debate") {
      count += 1;
    }
  }
  return count;
}

function humanSteerAllowsMovement(cog: Cog, snapshot: WorldSnapshot, moveOptions: CogMoveOptions): boolean {
  const steer = humanSteerText(cog);
  if (!steer) {
    return true;
  }

  if (!hasMoveOptions(moveOptions)) {
    return false;
  }

  if (cueSuggestsAvoidance(steer)) {
    return false;
  }

  if (cueMentionsTargetInCurrentRoom(steer, snapshot, cog)) {
    return false;
  }

  const suggestsMovement = cueSuggestsMovement(steer);
  if (cueMentionsAllowedRoom(steer, snapshot, moveOptions.roomIds)) {
    return true;
  }

  if (suggestsMovement && cueMentionsTargetInAllowedRoom(steer, snapshot, cog, moveOptions.roomIds)) {
    return true;
  }

  if (moveOptions.directions.length > 0) {
    return suggestsMovement;
  }

  return suggestsMovement && !cueSuggestsConversation(steer);
}

const HUMAN_STEER_PREFIX = "player steer:";

function humanSteerText(cog: Pick<Cog, "intent">): string | undefined {
  const intent = cog.intent?.trim();
  if (!intent?.startsWith(HUMAN_STEER_PREFIX)) {
    return undefined;
  }

  return intent.slice(HUMAN_STEER_PREFIX.length).trim();
}

function cueMentionsAllowedRoom(steer: string, snapshot: WorldSnapshot, allowedRoomIds: readonly string[]): boolean {
  if (!snapshot.venue || allowedRoomIds.length === 0) {
    return false;
  }

  return snapshot.venue.rooms.some(
    (room) => allowedRoomIds.includes(room.id) && (cueMentionsLabel(steer, room.id) || cueMentionsLabel(steer, room.label)),
  );
}

function cueMentionsTargetInAllowedRoom(
  steer: string,
  snapshot: WorldSnapshot,
  cog: Pick<Cog, "id">,
  allowedRoomIds: readonly string[],
): boolean {
  if (allowedRoomIds.length === 0) {
    return false;
  }

  return snapshot.cogs.some(
    (candidate) =>
      candidate.id !== cog.id &&
      Boolean(candidate.location && allowedRoomIds.includes(candidate.location.roomId)) &&
      cueMentionsLabel(steer, candidate.name),
  );
}

function cueMentionsTargetInCurrentRoom(steer: string, snapshot: WorldSnapshot, cog: Pick<Cog, "id" | "location">): boolean {
  const currentRoomId = cog.location?.roomId;
  if (!currentRoomId) {
    return false;
  }

  return snapshot.cogs.some(
    (candidate) =>
      candidate.id !== cog.id &&
      candidate.location?.roomId === currentRoomId &&
      cueMentionsLabel(steer, candidate.name),
  );
}

function cueMentionsLabel(steer: string, label: string): boolean {
  const normalizedSteer = normalizeCueText(steer);
  const normalizedLabel = normalizeCueText(label);
  return normalizedLabel.length > 1 && normalizedSteer.includes(normalizedLabel);
}

function cueSuggestsConversation(steer: string): boolean {
  const text = normalizeCueText(steer);
  return /\b(talk|speak|chat|communicat[a-z]*|debate|argue|convince|persuade|approach|engage|ask|tell)\b/.test(text);
}

function cueSuggestsGenericConversationTarget(steer: string): boolean {
  const text = normalizeCueText(steer);
  return /\b(someone|anyone|guest|person|people|opponent|rival|other team|nearest)\b/.test(text);
}

function cueSuggestsMovement(steer: string): boolean {
  const text = normalizeCueText(steer);
  return /\b(move|head|go|route|walk|travel|leave|enter|visit|find|seek|locate|follow|join|return|relocate|switch)\b/.test(text);
}

function cueSuggestsAvoidance(steer: string): boolean {
  const text = normalizeCueText(steer);
  return /\b(avoid|dodge|stay away|keep away|do not approach|dont approach|don't approach|do not go|dont go|don't go)\b/.test(text);
}

function normalizeCueText(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, " ").replace(/\s+/g, " ").trim();
}

function sortControllerDecisionsByIdle(
  snapshot: WorldSnapshot,
  candidates: ScheduledControllerDecision[],
): ScheduledControllerDecision[] {
  return [...candidates].sort((left, right) => compareCogsByIdle(snapshot, left.cog, right.cog));
}

function sortControllerDecisionsByMoveOrDebateIdle(
  snapshot: WorldSnapshot,
  candidates: ScheduledControllerDecision[],
): ScheduledControllerDecision[] {
  return [...candidates].sort((left, right) => compareCogsByMoveOrDebateIdle(snapshot, left.cog, right.cog));
}

function sortControllerDecisionsByMovePriority(
  snapshot: WorldSnapshot,
  candidates: ScheduledControllerDecision[],
): ScheduledControllerDecision[] {
  return [...candidates].sort((left, right) => compareCogsByMovePriority(snapshot, left.cog, right.cog));
}

function sortControllerDecisionsByIdleMovePriority(
  snapshot: WorldSnapshot,
  candidates: ScheduledControllerDecision[],
): ScheduledControllerDecision[] {
  return [...candidates].sort((left, right) => compareCogsByIdleMovePriority(snapshot, left.cog, right.cog));
}

function sortControllerDecisionsByNewMovePriority(
  snapshot: WorldSnapshot,
  candidates: ScheduledControllerDecision[],
): ScheduledControllerDecision[] {
  return [...candidates].sort((left, right) => compareCogsByNewMovePriority(snapshot, left.cog, right.cog));
}

function sortCogsByIdle(snapshot: WorldSnapshot, cogs: readonly Cog[]): Cog[] {
  return [...cogs].sort((left, right) => compareCogsByIdle(snapshot, left, right));
}

function sortCogsByDebatePriority(snapshot: WorldSnapshot, cogs: readonly Cog[]): Cog[] {
  return [...cogs].sort((left, right) => compareCogsByDebatePriority(snapshot, left, right));
}

function compareCogsByIdle(snapshot: WorldSnapshot, left: Cog, right: Cog): number {
  const tickDelta = latestCogActivityTick(snapshot, left) - latestCogActivityTick(snapshot, right);
  if (tickDelta !== 0) {
    return tickDelta;
  }

  return snapshotCogIndex(snapshot, left.id) - snapshotCogIndex(snapshot, right.id);
}

function compareCogsByMoveOrDebateIdle(snapshot: WorldSnapshot, left: Cog, right: Cog): number {
  const tickDelta = latestCogMoveOrDebateTick(snapshot, left) - latestCogMoveOrDebateTick(snapshot, right);
  if (tickDelta !== 0) {
    return tickDelta;
  }

  return snapshotCogIndex(snapshot, left.id) - snapshotCogIndex(snapshot, right.id);
}

function compareCogsByMovePriority(snapshot: WorldSnapshot, left: Cog, right: Cog): number {
  const tickDelta = latestCogMovePriorityTick(snapshot, left) - latestCogMovePriorityTick(snapshot, right);
  if (tickDelta !== 0) {
    return tickDelta;
  }

  return compareCogsByMoveOrDebateIdle(snapshot, left, right);
}

function compareCogsByIdleMovePriority(snapshot: WorldSnapshot, left: Cog, right: Cog): number {
  const leftNew = isNewMovePriorityCog(left);
  const rightNew = isNewMovePriorityCog(right);
  if (leftNew !== rightNew) {
    return leftNew ? -1 : 1;
  }

  return compareCogsByMoveOrDebateIdle(snapshot, left, right);
}

function compareCogsByNewMovePriority(snapshot: WorldSnapshot, left: Cog, right: Cog): number {
  const ageDelta = cogAgeTicks(left) - cogAgeTicks(right);
  if (ageDelta !== 0) {
    return ageDelta;
  }

  return compareCogsByIdle(snapshot, left, right);
}

function compareCogsByDebatePriority(snapshot: WorldSnapshot, left: Cog, right: Cog): number {
  const leftPoked = hasPendingPokePriority(snapshot, left);
  const rightPoked = hasPendingPokePriority(snapshot, right);
  if (leftPoked !== rightPoked) {
    return leftPoked ? -1 : 1;
  }
  if (leftPoked && rightPoked) {
    const tickDelta = latestCogPokePriorityTick(snapshot, left) - latestCogPokePriorityTick(snapshot, right);
    if (tickDelta !== 0) {
      return tickDelta;
    }
  }

  const leftDebateCount = debatePriorityCount(left);
  const rightDebateCount = debatePriorityCount(right);
  const leftLowDebateCount = leftDebateCount < LOW_DEBATE_PRIORITY_COUNT;
  const rightLowDebateCount = rightDebateCount < LOW_DEBATE_PRIORITY_COUNT;
  if (leftLowDebateCount !== rightLowDebateCount) {
    return leftLowDebateCount ? -1 : 1;
  }
  if (leftLowDebateCount && rightLowDebateCount && leftDebateCount !== rightDebateCount) {
    return leftDebateCount - rightDebateCount;
  }

  return compareCogsByIdle(snapshot, left, right);
}

function debatePriorityCount(cog: Cog): number {
  return Math.max(0, cog.stats.argumentsWon + cog.stats.argumentsLost);
}

function latestCogActivityTick(snapshot: WorldSnapshot, cog: Cog): number {
  let latestTick = Number.NEGATIVE_INFINITY;
  if (typeof cog.lastVenueMoveTick === "number") {
    latestTick = Math.max(latestTick, cog.lastVenueMoveTick);
  }
  for (const message of cog.conversationLog) {
    latestTick = Math.max(latestTick, message.tick);
  }
  for (const event of snapshot.recentEvents) {
    if (eventInvolvesCog(event, cog.id)) {
      latestTick = Math.max(latestTick, event.tick);
    }
  }
  return latestTick;
}

function latestCogPromptPriorityTick(snapshot: WorldSnapshot, cog: Cog): number {
  let latestTick = Number.NEGATIVE_INFINITY;
  for (const event of snapshot.recentEvents) {
    if (event.type === "inspect" && event.actorId === cog.id && event.message.endsWith(" prompt updated")) {
      latestTick = Math.max(latestTick, event.tick);
    }
  }
  for (const message of cog.conversationLog) {
    if (message.role === "assistant" && isPlayerSteerActionMessage(message.content)) {
      latestTick = Math.max(latestTick, message.tick);
    }
  }
  return latestTick;
}

function latestCogPokePriorityTick(snapshot: WorldSnapshot, cog: Cog): number {
  let latestTick = Number.NEGATIVE_INFINITY;
  for (const event of snapshot.recentEvents) {
    if (event.type === "poke" && event.actorId === cog.id) {
      latestTick = Math.max(latestTick, event.tick);
    }
  }
  return latestTick;
}

function latestCogMovePriorityTick(snapshot: WorldSnapshot, cog: Cog): number {
  return Math.max(latestCogPromptPriorityTick(snapshot, cog), latestCogPokePriorityTick(snapshot, cog));
}

function latestCogMoveOrDebateTick(snapshot: WorldSnapshot, cog: Cog): number {
  let latestTick = Number.NEGATIVE_INFINITY;
  if (typeof cog.lastVenueMoveTick === "number") {
    latestTick = Math.max(latestTick, cog.lastVenueMoveTick);
  }
  if (cog.debate) {
    latestTick = Math.max(latestTick, cog.debate.startedTick);
  }
  for (const event of snapshot.recentEvents) {
    if (event.type === "move" && event.actorId === cog.id) {
      latestTick = Math.max(latestTick, event.tick);
      continue;
    }
    if (
      (event.type === "debateStart" || event.type === "debateExchange") &&
      eventInvolvesCog(event, cog.id)
    ) {
      latestTick = Math.max(latestTick, event.tick);
    }
  }
  return latestTick;
}

function idleTicksSinceMoveOrDebate(snapshot: WorldSnapshot, cog: Cog, upcomingTick: number): number {
  const latestTick = latestCogMoveOrDebateTick(snapshot, cog);
  if (Number.isFinite(latestTick)) {
    return Math.max(0, upcomingTick - latestTick);
  }

  return Math.max(0, cog.ticksAlive);
}

function cogAgeTicks(cog: Pick<Cog, "ticksAlive">): number {
  return Math.max(0, cog.ticksAlive);
}

function isNewMovePriorityCog(cog: Cog): boolean {
  return cogAgeTicks(cog) < NEW_COG_MOVE_PRIORITY_TICKS;
}

function isIdlePriorityCog(snapshot: WorldSnapshot, cog: Cog, upcomingTick: number): boolean {
  return idleTicksSinceMoveOrDebate(snapshot, cog, upcomingTick) >= IDLE_PRIORITY_TICKS;
}

function hasIdlePriorityMoveCandidate(
  snapshot: WorldSnapshot,
  candidates: ScheduledControllerDecision[],
  upcomingTick: number,
): boolean {
  return candidates.some((candidate) => isIdlePriorityCog(snapshot, candidate.cog, upcomingTick));
}

function hasMovePriorityMoveCandidate(
  snapshot: WorldSnapshot,
  candidates: ScheduledControllerDecision[],
): boolean {
  return candidates.some((candidate) => hasPendingMovePriority(snapshot, candidate.cog));
}

function hasNewMovePriorityCandidate(candidates: ScheduledControllerDecision[]): boolean {
  return candidates.some((candidate) => isNewMovePriorityCog(candidate.cog));
}

function hasPriorityMoveCandidate(
  snapshot: WorldSnapshot,
  candidates: ScheduledControllerDecision[],
  upcomingTick: number,
): boolean {
  return hasMovePriorityMoveCandidate(snapshot, candidates) ||
    hasNewMovePriorityCandidate(candidates) ||
    hasIdlePriorityMoveCandidate(snapshot, candidates, upcomingTick);
}

function hasPendingMovePriority(snapshot: WorldSnapshot, cog: Cog): boolean {
  const priorityTick = latestCogMovePriorityTick(snapshot, cog);
  return Number.isFinite(priorityTick) && priorityTick >= latestCogMoveOrDebateTick(snapshot, cog);
}

function hasPendingPokePriority(snapshot: WorldSnapshot, cog: Cog): boolean {
  const pokeTick = latestCogPokePriorityTick(snapshot, cog);
  return Number.isFinite(pokeTick) && pokeTick >= latestCogMoveOrDebateTick(snapshot, cog);
}

function isPlayerSteerActionMessage(content: string): boolean {
  let value: unknown;
  try {
    value = JSON.parse(content);
  } catch {
    return false;
  }

  if (!value || typeof value !== "object") {
    return false;
  }

  const action = value as Partial<CogAction>;
  return action.type === "wait" &&
    typeof action.intent === "string" &&
    action.intent.trim().startsWith(PLAYER_STEER_INTENT_PREFIX);
}

function eventInvolvesCog(event: WorldSnapshot["recentEvents"][number], cogId: string): boolean {
  return event.actorId === cogId ||
    event.targetId === cogId ||
    Boolean(event.debate?.actions.some((action) => action.cogId === cogId));
}

function snapshotCogIndex(snapshot: WorldSnapshot, cogId: string): number {
  const index = snapshot.cogs.findIndex((cog) => cog.id === cogId);
  return index === -1 ? Number.MAX_SAFE_INTEGER : index;
}

function chooseMoveCandidates(
  snapshot: WorldSnapshot,
  candidates: ScheduledControllerDecision[],
  availableMoveSlots: number,
  maxDecisions = 1,
  upcomingTick?: number,
): ScheduledControllerDecision[] {
  if (candidates.length === 0 || availableMoveSlots <= 0) {
    return [];
  }

  const selected: ScheduledControllerDecision[] = [];
  const selectedCogIds = new Set<string>();
  const movePriorityCandidates = sortControllerDecisionsByMovePriority(
    snapshot,
    candidates.filter((candidate) => hasPendingMovePriority(snapshot, candidate.cog)),
  );
  for (const candidate of movePriorityCandidates) {
    if (selected.length >= availableMoveSlots) {
      break;
    }

    selected.push(candidate);
    selectedCogIds.add(candidate.cog.id);
  }
  if (selected.length > 0) {
    return selected;
  }

  const newMovePriorityCandidates = sortControllerDecisionsByNewMovePriority(
    snapshot,
    candidates.filter((candidate) => !selectedCogIds.has(candidate.cog.id) && isNewMovePriorityCog(candidate.cog)),
  );
  const hasNonIdleNewMovePriority = typeof upcomingTick !== "number" ||
    newMovePriorityCandidates.some((candidate) => !isIdlePriorityCog(snapshot, candidate.cog, upcomingTick));
  if (hasNonIdleNewMovePriority) {
    for (const candidate of newMovePriorityCandidates) {
      if (selected.length >= Math.min(maxDecisions, availableMoveSlots)) {
        break;
      }

      selected.push(candidate);
      selectedCogIds.add(candidate.cog.id);
    }

    if (selected.length > 0) {
      return selected;
    }
  }

  const idlePriorityCandidates = typeof upcomingTick === "number"
    ? sortControllerDecisionsByIdleMovePriority(
        snapshot,
        candidates.filter(
          (candidate) => !selectedCogIds.has(candidate.cog.id) && isIdlePriorityCog(snapshot, candidate.cog, upcomingTick),
        ),
      )
    : [];
  for (const candidate of idlePriorityCandidates) {
    if (selected.length >= availableMoveSlots) {
      break;
    }

    selected.push(candidate);
    selectedCogIds.add(candidate.cog.id);
  }

  if (selected.length > 0) {
    return selected;
  }

  return sortControllerDecisionsByIdle(snapshot, candidates).slice(0, Math.min(maxDecisions, availableMoveSlots, candidates.length));
}

function moveAskIsCoolingDown(snapshot: WorldSnapshot, upcomingTick: number): boolean {
  return snapshot.recentEvents.some(
    (event) =>
      event.type === "gameFlow" &&
      /^asking .+ to move$/.test(event.message) &&
      upcomingTick - event.tick < MOVE_ASK_SPACING_TICKS,
  );
}

function movingCogCount(snapshot: WorldSnapshot): number {
  return snapshot.cogs.filter((cog) => cog.moving).length;
}

function pendingMoveActionCount(actions: ReadonlyMap<string, CogAction>): number {
  let count = 0;
  for (const action of actions.values()) {
    if (action.type === "move") {
      count += 1;
    }
  }
  return count;
}

function hasMoveOptions(moveOptions: CogMoveOptions): boolean {
  return moveOptions.roomIds.length > 0 || moveOptions.directions.length > 0;
}

function shuffled<T>(values: readonly T[], random: SeededRandom): T[] {
  const result = [...values];
  for (let index = result.length - 1; index > 0; index -= 1) {
    const swapIndex = random.int(index + 1);
    [result[index], result[swapIndex]] = [result[swapIndex], result[index]];
  }
  return result;
}

function decisionPrompt(
  tick: number,
  observation: CogObservation,
  allowedActions: CogAction["type"][],
  moveOptions?: CogMoveOptions,
  gameConfig?: GameConfig,
): string {
  return buildControllerDecisionPrompt({
    tick,
    observation,
    allowedActions,
    allowedRoomIds: moveOptions?.roomIds,
    allowedDirections: moveOptions?.directions,
    gameConfig,
  });
}

export function viableControllerActionsFor(
  observation: CogObservation,
  canMove: boolean,
  upcomingTick = Number.POSITIVE_INFINITY,
): CogAction["type"][] {
  if (observation.cog.moving) {
    return [];
  }

  if (observation.cog.debate) {
    return canChooseDebateTactic(observation.cog, upcomingTick) ? ["chooseTactic"] : [];
  }

  const actions: CogAction["type"][] = [];
  if (canMove) {
    actions.push("move");
  }

  return actions;
}

function allowedActionsFor(
  observation: CogObservation,
  upcomingTick = Number.POSITIVE_INFINITY,
  moveOptions: CogMoveOptions = { roomIds: [], directions: [] },
): CogAction["type"][] {
  if (observation.cog.moving) {
    return ["wait"];
  }

  if (observation.cog.debate) {
    return canChooseDebateTactic(observation.cog, upcomingTick) ? ["chooseTactic"] : ["wait"];
  }

  const actions: CogAction["type"][] = ["wait"];
  if (hasMoveOptions(moveOptions)) {
    actions.push("move");
  }
  if (hasDebateTargets(observation)) {
    actions.push("debate");
  }

  return actions;
}

function meaningfulControllerActionsFor(allowedActions: CogAction["type"][]): CogAction["type"][] {
  if (allowedActions.includes("debate")) {
    return allowedActions.filter((action) => action !== "debate" && action !== "wait");
  }

  return allowedActions.length === 1 && allowedActions[0] === "wait" ? [] : allowedActions;
}

function manualActionCanRunNow(
  action: CogAction,
  observation: CogObservation,
  allowedActions: CogAction["type"][],
  moveOptions: CogMoveOptions,
): boolean {
  if (!allowedActions.includes(action.type)) {
    return false;
  }

  if (action.type === "move") {
    if (typeof action.roomId === "string") {
      return isValidVenueMove(observation, action.roomId, moveOptions.roomIds);
    }

    const hasRestrictedDirections = moveOptions.roomIds.length > 0 || moveOptions.directions.length > 0;
    const hasVenueRoomRoutes = moveOptions.roomIds.length > 0 && moveOptions.directions.length === 0;
    return Boolean(
      action.direction &&
      directions.includes(action.direction) &&
      (!hasRestrictedDirections || hasVenueRoomRoutes || moveOptions.directions.includes(action.direction)),
    );
  }

  if (action.type === "chooseTactic") {
    return tactics.includes(action.tactic);
  }

  return true;
}

function shouldQueueManualAction(action: CogAction, observation: CogObservation): boolean {
  if (
    action.type === "move" &&
    typeof action.roomId === "string" &&
    !observation.cog.moving &&
    !observation.cog.debate &&
    isVenueMoveRoute(observation, action.roomId)
  ) {
    return true;
  }

  return action.type === "chooseTactic" && Boolean(observation.cog.debate) && tactics.includes(action.tactic);
}

function hasDebateTargets(observation: CogObservation): boolean {
  return observation.visibleEntities.some(
    (entity) => entity.kind === "cog" && isEligibleDebateTarget(observation.cog, entity),
  );
}

function canChooseDebateTactic(cog: Cog, upcomingTick: number): boolean {
  return !cog.debate || upcomingTick >= cog.debate.nextRoundTick;
}

function actionResponse(action: CogAction): string {
  return JSON.stringify(action);
}

const directions: Direction[] = ["north", "south", "east", "west"];
const tactics: DebateTactic[] = ["reason", "spin", "passion"];

function sanitizeAction(
  action: unknown,
  observation: CogObservation,
  allowedActions: CogAction["type"][],
  moveOptions: CogMoveOptions = { roomIds: [], directions: [] },
  options: { allowDebateTarget?: boolean } = {},
): CogAction {
  if (!action || typeof action !== "object" || !("type" in action) || typeof action.type !== "string") {
    return fallbackAction(observation, {}, allowedActions);
  }

  const metadata = metadataFrom(action);
  if (!allowedActions.includes(action.type as CogAction["type"])) {
    return fallbackAction(observation, metadata, allowedActions);
  }

  const candidate = action as Record<string, unknown>;
  switch (action.type) {
    case "wait":
      return { type: "wait", ...metadata };
    case "move":
      if (typeof candidate.roomId === "string" && isValidVenueMove(observation, candidate.roomId, moveOptions.roomIds)) {
        return { type: "move", roomId: candidate.roomId, ...metadata };
      }
      const hasRestrictedDirections = moveOptions.roomIds.length > 0 || moveOptions.directions.length > 0;
      return directions.includes(candidate.direction as Direction) &&
        (!hasRestrictedDirections || moveOptions.directions.includes(candidate.direction as Direction))
        ? { type: "move", direction: candidate.direction as Direction, ...metadata }
        : fallbackAction(observation, metadata, allowedActions);
    case "debate":
      if (options.allowDebateTarget !== false && typeof candidate.targetId === "string" && isValidDebateTarget(observation, candidate.targetId)) {
        return { type: "debate", targetId: candidate.targetId, ...metadata };
      }

      return hasDebateTargets(observation)
        ? { type: "debate", ...metadata }
        : fallbackAction(observation, metadata, allowedActions);
    case "chooseTactic":
      return tactics.includes(candidate.tactic as DebateTactic)
        ? { type: "chooseTactic", tactic: candidate.tactic as DebateTactic, ...metadata }
        : fallbackAction(observation, metadata, allowedActions);
    default:
      return fallbackAction(observation, metadata, allowedActions);
  }
}

function isValidVenueMove(observation: CogObservation, roomId: string, allowedRoomIds: string[]): boolean {
  if (allowedRoomIds.length > 0 && !allowedRoomIds.includes(roomId)) {
    return false;
  }

  return isVenueMoveRoute(observation, roomId);
}

function isVenueMoveRoute(observation: CogObservation, roomId: string): boolean {
  const currentRoomId = observation.cog.location?.roomId;
  if (!currentRoomId || !observation.venue) {
    return false;
  }

  const currentRoom = observation.venue.rooms.find((room) => room.id === currentRoomId);
  return Boolean(currentRoom && (roomId === currentRoom.id || currentRoom.neighborIds.includes(roomId)));
}

function isValidDebateTarget(observation: CogObservation, targetId: string): boolean {
  return observation.visibleEntities.some(
    (entity) =>
      entity.kind === "cog" &&
      entity.id === targetId &&
      isEligibleDebateTarget(observation.cog, entity),
  );
}

function fallbackAction(
  observation: CogObservation,
  metadata: CogActionMetadata = {},
  allowedActions: CogAction["type"][] = [],
): CogAction {
  if (observation.cog.debate) {
    const tactic = fallbackDebateTactic(observation.cog);
    return {
      type: "chooseTactic",
      tactic,
      intent: metadata.intent ?? `invalid debate action; defaulting to ${tactic}`,
      ...(metadata.choiceNumber !== undefined ? { choiceNumber: metadata.choiceNumber } : {}),
      ...(metadata.thoughts !== undefined ? { thoughts: metadata.thoughts } : {}),
      ...(metadata.timedOut !== undefined ? { timedOut: metadata.timedOut } : {}),
    };
  }

  if (allowedActions.includes("debate") && hasDebateTargets(observation)) {
    return {
      type: "debate",
      intent: metadata.intent ?? "invalid action; defaulting to debate",
      ...(metadata.choiceNumber !== undefined ? { choiceNumber: metadata.choiceNumber } : {}),
      ...(metadata.thoughts !== undefined ? { thoughts: metadata.thoughts } : {}),
      ...(metadata.timedOut !== undefined ? { timedOut: metadata.timedOut } : {}),
    };
  }

  return {
    type: "wait",
    intent: metadata.intent ?? "invalid action; defaulting to wait",
    ...(metadata.choiceNumber !== undefined ? { choiceNumber: metadata.choiceNumber } : {}),
    ...(metadata.thoughts !== undefined ? { thoughts: metadata.thoughts } : {}),
    ...(metadata.timedOut !== undefined ? { timedOut: metadata.timedOut } : {}),
  };
}

function fallbackDebateTactic(cog: Cog): DebateTactic {
  return fallbackTacticForCog(cog);
}

function metadataFrom(action: object): CogActionMetadata {
  const choiceNumber = choiceNumberFrom(action);
  const intent = intentFrom(action);
  const thoughts = thoughtsFrom(action);
  const timedOut = timedOutFrom(action);
  return {
    ...(choiceNumber !== undefined ? { choiceNumber } : {}),
    ...(intent !== undefined ? { intent } : {}),
    ...(thoughts !== undefined ? { thoughts } : {}),
    ...(timedOut !== undefined ? { timedOut } : {}),
  };
}

function choiceNumberFrom(action: object): number | undefined {
  if (!("choiceNumber" in action) || typeof action.choiceNumber !== "number") {
    return undefined;
  }

  return Number.isInteger(action.choiceNumber) && action.choiceNumber > 0 ? action.choiceNumber : undefined;
}

function intentFrom(action: object): string | undefined {
  return "intent" in action && typeof action.intent === "string" ? action.intent : undefined;
}

function thoughtsFrom(action: object): string | undefined {
  return "thoughts" in action && typeof action.thoughts === "string" ? action.thoughts : undefined;
}

function timedOutFrom(action: object): boolean | undefined {
  return "timedOut" in action && typeof action.timedOut === "boolean" ? action.timedOut : undefined;
}

function controllerMode(snapshot: WorldSnapshot): ControllerId {
  return snapshot.cogs[0]?.controllerId ?? "stub";
}

async function closeClients(socketServer: WebSocketServer): Promise<void> {
  await Promise.all(
    Array.from(socketServer.clients).map(
      (client) =>
        new Promise<void>((resolve) => {
          if (client.readyState === WebSocket.CLOSED) {
            resolve();
            return;
          }

          const timeout = setTimeout(() => {
            client.terminate();
            resolve();
          }, 100);
          client.once("close", () => {
            clearTimeout(timeout);
            resolve();
          });
          client.close(1001, "server closing");
        }),
    ),
  );
}
