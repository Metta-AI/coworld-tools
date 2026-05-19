import { nanoid } from "nanoid";
import { oppositeTeamColor, TEAM_COLORS, WORLD_OBJECT_TYPES } from "../../shared/types.js";
import type {
  AchievementCount,
  AchievementAssignment,
  AchievementParameters,
  Cog,
  CogAction,
  CogConversationMessage,
  CogObservation,
  CogRoomHistoryEntry,
  Color,
  CompletedAchievement,
  ControllerId,
  DebateChoice,
  DebateEventDetail,
  DebateLogEntry,
  DebateTactic,
  Direction,
  FailedAchievement,
  GoalScoreTrack,
  PersonalGoal,
  Position,
  SpriteColorUrls,
  Terrain,
  TerrainCell,
  Trait,
  VenueLayout,
  VenueLocation,
  VenueRoom,
  VenueSpot,
  WorldDimensions,
  WorldEvent,
  WorldObject,
  WorldSnapshot,
} from "../../shared/types.js";
import {
  ACHIEVEMENT_RULES,
  achievementDisplayName,
  achievementKey,
  achievementDefinitionById,
  cloneGameConfig,
  normalizeGameConfig,
  type AchievementRule,
  type GameConfig,
  type GameConfigInput,
  type TraitConfig,
  type TraitConfigInput,
} from "../../shared/rules.js";
import { ACHIEVEMENT_TACTICS, ACHIEVEMENT_TRAITS } from "../../shared/achievements/helpers.js";
import { isValidCogRoomHistoryEntry } from "../../shared/room-history.js";
import { normalizeTraitId, traitDefinitionFor, type TraitCode, type TraitConversionEffect } from "../../shared/traits/index.js";
import { venueRoomSection, venueSpotIsSpeaker, type VenueSection } from "../../shared/venue.js";
import {
  legacyHalfSecondTicksToSimulationTicks,
  venueMoveDurationTicksForDistance,
} from "../../shared/timing.js";
import { nextPosition } from "./movement.js";
import { createObservation } from "./observation.js";
import { SeededRandom } from "./random.js";
import { isEligibleDebateTarget } from "./debate-target.js";

export type AddCogInput = {
  name: string;
  behaviorPrompt?: string;
  spriteSheetKey?: string;
  spriteUrl?: string;
  spriteUrls?: SpriteColorUrls;
  controllerId?: ControllerId;
  attributes?: Record<string, number>;
  color?: Color;
  defensiveTrait?: Trait;
  activeTrait?: Trait;
  personalGoal?: PersonalGoal;
  position?: Position;
  location?: VenueLocation;
};

export type UpdateCogProfileInput = {
  name?: string;
  behaviorPrompt: string;
  attributes: Record<string, number>;
  defensiveTrait?: Trait;
  activeTrait?: Trait;
  personalGoal?: PersonalGoal;
};

export type CogMoveOptions = {
  roomIds: string[];
  directions: Direction[];
};

export type CogMoveOptionsContext = {
  ignoreRoomMoveCooldown?: boolean;
};

export type WorldStepOptions = {
  debatesEnabled?: boolean;
  ignoreRoomMoveCooldown?: boolean;
};

export type GridWorldState = WorldSnapshot & {
  version: 1;
  config: GameConfig;
  debateCooldowns: Array<[string, number]>;
  randomState: number;
};

type AchievementCounter = Omit<AchievementCount, "current">;
type AchievementCandidate = {
  rule: AchievementRule;
  parameters?: AchievementAssignment["parameters"];
};
type DebateLogCogState = {
  name: string;
  color: Color;
  certainty: number;
};

const ACTIVE_ACHIEVEMENT_COUNT = 3;
const MAX_CONVERSATION_MESSAGES = 80;
const MAX_COG_ROOM_HISTORY = 6;
const MAX_RECENT_EVENTS = 240;
const DRAW_RESULT_TICKS = legacyHalfSecondTicksToSimulationTicks(2);

export class GridWorld {
  private tick = 0;
  private readonly dimensions: WorldDimensions;
  private venue: VenueLayout | undefined;
  private readonly cogs = new Map<string, Cog>();
  private readonly homeCogs = new Map<string, Cog>();
  private readonly objects = new Map<string, WorldObject>();
  private readonly terrain = new Map<string, Exclude<Terrain, "floor">>();
  private readonly recentEvents: WorldEvent[] = [];
  private readonly debateLog: DebateLogEntry[] = [];
  private readonly achievementCounts = new Map<string, AchievementCounter>();
  private readonly debateCooldowns = new Map<string, number>();
  private readonly convertedCogIdsThisTick = new Set<string>();
  private readonly martyrProtectedCogIdsThisTick = new Set<string>();
  private readonly avengerTargets = new Map<string, Color>();
  private readonly random = new SeededRandom(0xc09_5a4b0);
  private config: GameConfig;

  constructor(
    dimensions: WorldDimensions,
    config: GameConfigInput = {},
    venue?: VenueLayout,
  ) {
    this.dimensions = cloneDimensions(dimensions);
    this.venue = venue ? cloneVenue(venue) : undefined;
    this.config = normalizeGameConfig(config);
  }

  static fromState(state: GridWorldState): GridWorld {
    const world = new GridWorld(state.dimensions, state.config, state.venue);
    world.tick = state.tick;
    world.cogs.clear();
    world.homeCogs.clear();
    world.objects.clear();
    world.terrain.clear();
    world.recentEvents.length = 0;
    world.debateLog.length = 0;
    world.achievementCounts.clear();
    world.debateCooldowns.clear();
    world.convertedCogIdsThisTick.clear();
    world.martyrProtectedCogIdsThisTick.clear();
    world.avengerTargets.clear();
    world.random.setState(state.randomState);

    const spawnTicksByCogId = new Map<string, number>();
    for (const event of state.recentEvents) {
      if (event.type === "spawn" && event.actorId) {
        spawnTicksByCogId.set(event.actorId, event.tick);
      }
    }

    for (const cog of state.cogs) {
      const legacyCog = cog as Cog & { ticksAlive?: number };
      const ticksAlive =
        typeof legacyCog.ticksAlive === "number"
          ? legacyCog.ticksAlive
          : Math.max(0, state.tick - (spawnTicksByCogId.get(cog.id) ?? 0));
      const storedCog = cloneCog({ ...legacyCog, ticksAlive });
      if (cogStatus(storedCog) === "home") {
        world.homeCogs.set(storedCog.id, storedCog);
      } else {
        world.cogs.set(storedCog.id, { ...storedCog, status: undefined });
      }
    }
    world.reconcileVenueCogPlacements();
    world.reconcileCogRoomHistories();
    for (const object of state.objects) {
      if (!isKnownWorldObject(object)) {
        continue;
      }
      world.objects.set(object.id, cloneObject(object));
    }
    for (const cell of state.terrain) {
      world.terrain.set(positionKey(cell.position), cell.terrain);
    }
    for (const event of state.recentEvents) {
      if (isLegacySpeechEvent(event)) {
        continue;
      }
      world.recentEvents.push(cloneEvent(event));
    }
    for (const entry of state.debateLog ?? []) {
      world.debateLog.push(cloneDebateLogEntry(entry));
    }
    for (const count of state.achievementCounts ?? inferAchievementCountersFromCogs(state.cogs)) {
      if (!isKnownAchievementId(count.achievementId)) {
        continue;
      }
      world.achievementCounts.set(achievementKey(count), cloneAchievementCounter(count));
    }
    for (const [key, cooldownTick] of state.debateCooldowns) {
      world.debateCooldowns.set(key, cooldownTick);
    }
    world.repairInvalidDebates();

    return world;
  }

  gameConfig(): GameConfig {
    return cloneGameConfig(this.config);
  }

  exportState(): GridWorldState {
    const snapshot = this.snapshot();
    return {
      version: 1,
      ...snapshot,
      cogs: [
        ...snapshot.cogs,
        ...Array.from(this.homeCogs.values()).map((cog) => cloneCog({ ...cog, status: "home" })),
      ],
      config: this.gameConfig(),
      debateCooldowns: Array.from(this.debateCooldowns.entries()),
      randomState: this.random.stateValue(),
    };
  }

  updateGameConfig(input: GameConfigInput): GameConfig {
    this.config = normalizeGameConfig({
      ...this.config,
      ...input,
      traitConfig: mergeTraitConfigInput(this.config.traitConfig, input.traitConfig),
    });
    return this.gameConfig();
  }

  updateVenueLayout(venue: VenueLayout): VenueLayout {
    this.venue = cloneVenue(venue);
    this.reconcileVenueCogPlacements();
    return cloneVenue(this.venue);
  }

  canCogMove(cogId: string): boolean {
    const options = this.moveOptionsFor(cogId);
    return options.roomIds.length > 0 || options.directions.length > 0;
  }

  moveOptionsFor(cogId: string, context: CogMoveOptionsContext = {}): CogMoveOptions {
    const cog = this.cogs.get(cogId);
    if (!cog || cog.debate || cog.moving || cog.movementCooldown > 0) {
      return { roomIds: [], directions: [] };
    }

    if (!this.venue || !cog.location) {
      const directions: Direction[] = ["north", "south", "east", "west"];
      return {
        roomIds: [],
        directions: directions.filter((direction) => this.canMoveInDirection(cog, direction)),
      };
    }

    const currentRoom = this.roomForId(cog.location.roomId);
    if (!currentRoom) {
      return { roomIds: [], directions: [] };
    }

    const canLeaveCurrentRoom =
      context.ignoreRoomMoveCooldown || !this.isVenueMoveOnCooldown(cog) || this.isAloneInVenueRoom(cog, currentRoom.id);
    return {
      roomIds: canLeaveCurrentRoom
        ? currentRoom.neighborIds.filter((roomId) => Boolean(this.roomForId(roomId) && this.emptySpotInRoom(roomId)))
        : [],
      directions: [],
    };
  }

  canStartDebate(cogId: string, targetId: string): boolean {
    const cog = this.cogs.get(cogId);
    const target = this.cogs.get(targetId);
    return Boolean(cog && target && this.canStartDebateBetween(cog, target));
  }

  debatePartnerIdsFor(cogId: string): string[] {
    return Array.from(this.cogs.values()).flatMap((candidate) =>
      this.canStartDebate(cogId, candidate.id) ? [candidate.id] : [],
    );
  }

  private canMoveInDirection(cog: Cog, direction: Direction): boolean {
    const destination = nextPosition(cog.position, direction);
    if (!this.isInsideBounds(destination) || this.terrainAt(destination) === "wall") {
      return false;
    }

    const target = this.entityAt(destination);
    if (!target) {
      return true;
    }

    return false;
  }

  addCog(input: AddCogInput): Cog {
    const venueLocation = input.location ? cloneVenueLocation(input.location) : undefined;
    const requestedVenueSpot = venueLocation ? this.spotForLocation(venueLocation) : undefined;
    if (venueLocation && !requestedVenueSpot) {
      throw new Error(`Unknown venue spot: ${venueLocation.roomId}/${venueLocation.spotId}`);
    }
    if (input.position && requestedVenueSpot && !samePosition(input.position, requestedVenueSpot.position)) {
      throw new Error(`Cog position does not match venue spot: ${requestedVenueSpot.id}`);
    }
    const fallbackVenueSpot = input.position ? undefined : this.findEmptyVenueSpot();
    const venueSpot = requestedVenueSpot ?? fallbackVenueSpot;
    const position = input.position
      ? clonePosition(input.position)
      : venueSpot?.position
        ? clonePosition(venueSpot.position)
        : this.findEmptyEdgeCell();
    if (!this.isInsideBounds(position)) {
      throw new Error(`Cog position is outside bounds: ${position.x},${position.y}`);
    }
    if (this.terrainAt(position) === "wall") {
      throw new Error(`Cog position is blocked by wall terrain: ${position.x},${position.y}`);
    }
    if (this.entityAt(position)) {
      throw new Error(`Cog position is occupied: ${position.x},${position.y}`);
    }
    const spriteSheetKey = input.spriteSheetKey ?? "cog-default";

    const cog: Cog = {
      id: `cog_${nanoid(8)}`,
      name: this.uniqueCogName(input.name),
      behaviorPrompt: input.behaviorPrompt?.trim() ?? "",
      position,
      location: venueSpot?.roomId ? { roomId: venueSpot.roomId, spotId: venueSpot.id } : undefined,
      spriteSheetKey,
      spriteUrl: input.spriteUrl?.trim() || defaultSpriteUrl(spriteSheetKey),
      spriteUrls: cloneSpriteUrls(input.spriteUrls),
      attributes: cloneAttributes(input.attributes ?? { energy: 5, focus: 5 }),
      color: input.color ?? "red",
      defensiveTrait: input.defensiveTrait ?? "stubborn",
      activeTrait: input.activeTrait ?? "forceful",
      personalGoal: input.personalGoal ?? "majority",
      activity: "idle",
      ticksAlive: 0,
      personalScore: 0,
      achievements: [],
      completedAchievements: [],
      failedAchievements: [],
      goalScores: createGoalScoreTracks(this.tick),
      stats: createCogStats(),
      certainty: this.config.conversionThreshold,
      controllerId: input.controllerId ?? "llm",
      movementCooldown: 0,
      roomHistory: venueSpot?.roomId
        ? [cogRoomHistoryEntry({ roomId: venueSpot.roomId, spotId: venueSpot.id }, this.tick)]
        : [],
      conversationLog: [],
    };
    this.fillActiveAchievements(cog);

    this.cogs.set(cog.id, cog);
    this.recordEvent({
      type: "spawn",
      actorId: cog.id,
      message: `${cog.name} arrived!`,
      position: cog.position,
    });
    return cloneCog(cog);
  }

  updateCogProfile(cogId: string, input: UpdateCogProfileInput): Cog {
    const cog = this.cogs.get(cogId);
    if (!cog) {
      throw new Error(`Unknown cog: ${cogId}`);
    }

    if (input.name) {
      cog.name = this.uniqueCogName(input.name, cog.id);
    }
    const nextBehaviorPrompt = input.behaviorPrompt.trim();
    const promptChanged = nextBehaviorPrompt !== cog.behaviorPrompt;
    cog.behaviorPrompt = nextBehaviorPrompt;
    cog.attributes = cloneAttributes(input.attributes);
    const nextDefensiveTrait = input.defensiveTrait ?? cog.defensiveTrait;
    const nextActiveTrait = input.activeTrait ?? cog.activeTrait;
    if (zealotSlotKey(nextDefensiveTrait, nextActiveTrait) !== zealotSlotKey(cog.defensiveTrait, cog.activeTrait)) {
      throw new Error("Zealot is a seed-only trait and cannot be assigned or removed from profiles");
    }
    if (input.defensiveTrait) {
      cog.defensiveTrait = input.defensiveTrait;
    }
    if (input.activeTrait) {
      cog.activeTrait = input.activeTrait;
    }
    if (input.personalGoal) {
      cog.personalGoal = input.personalGoal;
    }
    this.recordEvent({
      type: "inspect",
      actorId: cog.id,
      message: promptChanged ? `${cog.name} prompt updated` : `${cog.name} profile updated`,
      position: cog.position,
    });
    return cloneCog(cog);
  }

  abandonCog(cogId: string): Cog {
    const cog = this.cogs.get(cogId);
    if (!cog) {
      throw new Error(`Unknown cog: ${cogId}`);
    }

    return cloneCog(cog);
  }

  kickCogHome(cogId: string): Cog {
    return this.sendCogHome(cogId);
  }

  private sendCogHome(cogId: string): Cog {
    const cog = this.cogs.get(cogId);
    if (!cog) {
      throw new Error(`Unknown cog: ${cogId}`);
    }

    const homeCog = cloneCog({
      ...cog,
      activity: "idle",
      debate: undefined,
      intent: "home",
      moving: undefined,
      status: "home",
    });
    this.cogs.delete(cogId);
    this.homeCogs.set(cogId, homeCog);
    this.convertedCogIdsThisTick.delete(cogId);
    this.martyrProtectedCogIdsThisTick.delete(cogId);
    this.avengerTargets.delete(cogId);
    for (const other of this.cogs.values()) {
      if (other.debate?.opponentId === cogId) {
        delete other.debate;
      }
    }
    this.recordEvent({
      type: "kick",
      actorId: cog.id,
      message: `${cog.name} was kicked home`,
      position: cog.position,
    });
    this.repairInvalidDebates();
    return cloneCog(homeCog);
  }

  pokeCog(cogId: string): Cog {
    const cog = this.cogs.get(cogId);
    if (!cog) {
      throw new Error(`Unknown cog: ${cogId}`);
    }

    this.recordEvent({
      type: "poke",
      actorId: cog.id,
      message: `${cog.name} was poked`,
      position: cog.position,
    });
    return cloneCog(cog);
  }

  shuffleCogTeams(): WorldSnapshot {
    const cogs = Array.from(this.cogs.values());
    const nextColors = shuffledBalancedColors(cogs.length, this.random);
    avoidNoopShuffle(cogs, nextColors);
    const previousMajority = this.uniquePopulationColor("highest");

    for (const [index, cog] of cogs.entries()) {
      const previousColor = cog.color;
      const nextColor = nextColors[index] ?? previousColor;
      if (nextColor === previousColor) {
        continue;
      }

      cog.color = nextColor;
      cog.stats.teamFlips += 1;
      cog.certainty = this.config.conversionThreshold;
      this.recordEvent({
        type: "colorChange",
        actorId: cog.id,
        message: `${cog.name} shuffled from ${previousColor} to ${nextColor}`,
        position: cog.position,
      });
    }

    this.repairInvalidDebates();
    this.recordMajorityChange(previousMajority);
    return this.snapshot();
  }

  addObject(object: WorldObject): WorldObject {
    if (!this.isInsideBounds(object.position)) {
      throw new Error(`Object position is outside bounds: ${object.position.x},${object.position.y}`);
    }
    if (this.terrainAt(object.position) === "wall") {
      throw new Error(`Object position is blocked by wall terrain: ${object.position.x},${object.position.y}`);
    }
    if (this.objects.has(object.id)) {
      throw new Error(`Object ID already exists: ${object.id}`);
    }
    if (this.entityAt(object.position)) {
      throw new Error(`Object position is occupied: ${object.position.x},${object.position.y}`);
    }

    const storedObject = cloneObject(object);
    this.objects.set(storedObject.id, storedObject);
    return cloneObject(storedObject);
  }

  setTerrain(position: Position, terrain: Terrain): void {
    if (!this.isInsideBounds(position)) {
      throw new Error(`Terrain position is outside bounds: ${position.x},${position.y}`);
    }

    if (terrain === "floor") {
      this.terrain.delete(positionKey(position));
      return;
    }

    if (terrain === "wall" && this.entityAt(position)) {
      throw new Error(`Wall terrain cannot be placed on occupied position: ${position.x},${position.y}`);
    }

    this.terrain.set(positionKey(position), terrain);
  }

  getObservation(cogId: string): CogObservation {
    const snapshot = this.snapshot();
    const cog = snapshot.cogs.find((candidate) => candidate.id === cogId);
    if (!cog) {
      throw new Error(`Unknown cog: ${cogId}`);
    }

    return createObservation(cog, snapshot);
  }

  async step(actions: Map<string, CogAction>, options: WorldStepOptions = {}): Promise<WorldSnapshot> {
    const debatesEnabled = options.debatesEnabled ?? true;

    this.tick += 1;
    this.convertedCogIdsThisTick.clear();
    this.martyrProtectedCogIdsThisTick.clear();
    this.advanceCogLifetimes();

    this.advanceMovingCogs();
    if (debatesEnabled) {
      this.repairInvalidDebates();
      this.resolveActiveDebates(actions);
    } else {
      this.clearActiveDebates();
    }
    this.applyPassiveTraitCertaintyChanges();

    for (const [cogId, action] of actions) {
      const cog = this.cogs.get(cogId);
      if (!cog) {
        continue;
      }

      if (cog.debate) {
        continue;
      }

      if (action.type === "debate") {
        if (!debatesEnabled || !action.targetId) {
          continue;
        }

        cog.intent = action.intent;
        this.tryStartDebate(cog, action.targetId);
        continue;
      }

      this.applyAction(cog, action, options);
    }

    this.updateAchievements();
    return this.snapshot();
  }

  recordCogConversation(cogId: string, messages: Array<Omit<CogConversationMessage, "id" | "tick">>): void {
    const cog = this.cogs.get(cogId);
    if (!cog) {
      return;
    }

    for (const message of messages) {
      cog.conversationLog.push({
        ...message,
        id: `msg_${nanoid(8)}`,
        tick: this.tick,
      });
    }

    while (cog.conversationLog.length > MAX_CONVERSATION_MESSAGES) {
      cog.conversationLog.shift();
    }
  }

  recordGameFlow(message: string, actorId?: string, targetId?: string): void {
    const actor = actorId ? this.cogs.get(actorId) : undefined;
    this.recordEvent({
      type: "gameFlow",
      actorId,
      targetId,
      message,
      position: actor?.position,
    });
  }

  snapshot(): WorldSnapshot {
    return {
      tick: this.tick,
      dimensions: cloneDimensions(this.dimensions),
      venue: this.venue ? cloneVenue(this.venue) : undefined,
      cogs: Array.from(this.cogs.values()).map((cog) => cloneCog(cog)),
      objects: Array.from(this.objects.values()).map((object) => cloneObject(object)),
      terrain: this.snapshotTerrain(),
      recentEvents: this.recentEvents.map((event) => cloneEvent(event)),
      achievementCounts: this.snapshotAchievementCounts(),
      debateLog: this.debateLog.map(cloneDebateLogEntry),
    };
  }

  private applyAction(cog: Cog, action: CogAction, options: WorldStepOptions): void {
    cog.intent = action.intent;

    if (cog.moving) {
      if (action.type === "move") {
        this.recordEvent({
          type: "moveBlocked",
          actorId: cog.id,
          message: `${cog.name} is already moving`,
          position: cog.position,
        });
      }
      return;
    }

    if (action.type === "wait") {
      return;
    }

    if (action.type === "chooseTactic" || action.type === "debate") {
      return;
    }

    if (action.type === "move") {
      if (this.tryMoveVenue(cog, action, { ignoreRoomMoveCooldown: options.ignoreRoomMoveCooldown ?? false })) {
        return;
      }
      if (action.direction) {
        this.tryMove(cog, action.direction);
      }
    }
  }

  private clearActiveDebates(): void {
    for (const cog of this.cogs.values()) {
      delete cog.debate;
    }
  }

  private tryMoveVenue(
    cog: Cog,
    action: Extract<CogAction, { type: "move" }>,
    context: CogMoveOptionsContext = {},
  ): boolean {
    if (!this.venue || !cog.location) {
      return false;
    }

    if (cog.moving) {
      this.recordEvent({
        type: "moveBlocked",
        actorId: cog.id,
        message: `${cog.name} is already moving`,
        position: cog.position,
      });
      return true;
    }

    if (cog.movementCooldown > 0) {
      cog.movementCooldown -= 1;
      this.recordEvent({
        type: "moveBlocked",
        actorId: cog.id,
        message: `${cog.name} is waiting before moving rooms again`,
        position: cog.position,
      });
      return true;
    }

    const currentSpot = this.spotForLocation(cog.location);
    if (!currentSpot) {
      delete cog.location;
      return false;
    }
    if (!currentSpot.roomId) {
      delete cog.location;
      return false;
    }
    const currentRoom = this.roomForId(currentSpot.roomId);
    if (!currentRoom) {
      delete cog.location;
      return false;
    }
    const destinationRoom = action.roomId ? this.roomForId(action.roomId) : action.direction ? this.roomForDirection(currentRoom, action.direction) : undefined;
    if (!destinationRoom) {
      this.recordEvent({
        type: "moveBlocked",
        actorId: cog.id,
        message: `${cog.name} could not leave ${currentRoom.label}`,
        position: cog.position,
      });
      return true;
    }

    const isLeavingCurrentRoom = destinationRoom.id !== currentRoom.id;
    if (!isLeavingCurrentRoom) {
      this.recordEvent({
        type: "moveBlocked",
        actorId: cog.id,
        message: `${cog.name} is already in ${currentRoom.label}`,
        position: cog.position,
      });
      return true;
    }

    if (!currentRoom.neighborIds.includes(destinationRoom.id)) {
      this.recordEvent({
        type: "moveBlocked",
        actorId: cog.id,
        message: `${cog.name} could not move from ${currentRoom.label} to ${destinationRoom.label}`,
        position: cog.position,
      });
      return true;
    }

    if (!context.ignoreRoomMoveCooldown && this.isVenueMoveOnCooldown(cog) && !this.isAloneInVenueRoom(cog, currentRoom.id)) {
      const remainingTicks = this.remainingVenueMoveCooldownTicks(cog);
      this.recordEvent({
        type: "moveBlocked",
        actorId: cog.id,
        message: `${cog.name} must wait ${remainingTicks} more tick${remainingTicks === 1 ? "" : "s"} before moving from ${currentRoom.label}`,
        position: cog.position,
      });
      return true;
    }

    const destination = this.preferredEntrySpotInRoom(destinationRoom.id);
    if (!destination) {
      this.recordEvent({
        type: "moveBlocked",
        actorId: cog.id,
        message: `${cog.name} could not enter ${destinationRoom.label} because it is full`,
        position: cog.position,
      });
      return true;
    }

    if (!destination.roomId) {
      this.recordEvent({
        type: "moveBlocked",
        actorId: cog.id,
        message: `${cog.name} could not enter ${destinationRoom.label}`,
        position: cog.position,
      });
      return true;
    }

    const from = { roomId: currentSpot.roomId, spotId: currentSpot.id };
    const to = { roomId: destination.roomId, spotId: destination.id };
    const path = this.venueMovePath(currentSpot, destination);
    cog.moving = {
      from,
      to,
      fromPosition: clonePosition(currentSpot.position),
      toPosition: clonePosition(destination.position),
      path,
      startedTick: this.tick,
      arriveTick: this.tick + venueMoveDurationTicks(path, this.dimensions),
    };
    this.closeCogRoomHistory(cog, this.tick);
    delete cog.location;
    cog.position = clonePosition(currentSpot.position);
    this.recordEvent({
      type: "move",
      actorId: cog.id,
      message: `${cog.name} started moving to ${this.spotLabel(destination)}`,
      position: cog.position,
    });
    return true;
  }

  private venueMovePath(from: VenueSpot, to: VenueSpot): Position[] {
    const path = [clonePosition(from.position)];
    if (from.roomId !== to.roomId) {
      const roomPath = this.roomPathBetween(from.roomId, to.roomId);
      const points = roomPath
        ? roomPath.fromRoomId === from.roomId
          ? roomPath.points
          : [...roomPath.points].reverse()
        : [];
      for (const point of points) {
        appendPathPoint(path, point);
      }
    }
    appendPathPoint(path, to.position);
    return path;
  }

  private roomPathBetween(fromRoomId: string, toRoomId: string): VenueLayout["roomPaths"][number] | undefined {
    return this.venue?.roomPaths.find(
      (path) =>
        (path.fromRoomId === fromRoomId && path.toRoomId === toRoomId) ||
        (path.fromRoomId === toRoomId && path.toRoomId === fromRoomId),
    );
  }

  private tryMove(cog: Cog, direction: Direction): void {
    if (cog.movementCooldown > 0) {
      cog.movementCooldown -= 1;
      this.recordEvent({
        type: "moveBlocked",
        actorId: cog.id,
        message: `${cog.name} is slowed by sand`,
        position: cog.position,
      });
      return;
    }

    const destination = nextPosition(cog.position, direction);
    if (!this.isInsideBounds(destination)) {
      this.recordEvent({
        type: "moveBlocked",
        actorId: cog.id,
        message: `${cog.name} could not move beyond the board`,
        position: cog.position,
      });
      return;
    }

    if (this.terrainAt(destination) === "wall") {
      this.recordEvent({
        type: "moveBlocked",
        actorId: cog.id,
        message: `${cog.name} could not move through a wall`,
        position: destination,
      });
      return;
    }

    const target = this.entityAt(destination);
    if (!target) {
      cog.position = destination;
      if (this.terrainAt(destination) === "sand") {
        cog.movementCooldown = this.sandMovementCooldown();
      }
      this.recordEvent({
        type: "move",
        actorId: cog.id,
        message: `${cog.name} moved ${direction}`,
        position: cog.position,
      });
      return;
    }

    if ("name" in target) {
      this.recordEvent({
        type: "moveBlocked",
        actorId: cog.id,
        targetId: target.id,
        message: `${cog.name} could not move through ${target.name}`,
        position: destination,
      });
      return;
    }

    this.recordEvent({
      type: "moveBlocked",
      actorId: cog.id,
      targetId: target.id,
      message: `${cog.name} could not move through ${target.type}`,
      position: destination,
    });
  }

  private sandMovementCooldown(): number {
    return 1;
  }

  private tryStartDebate(cog: Cog, targetId: string): void {
    const target = this.cogs.get(targetId);
    if (!target || !this.canStartDebateBetween(cog, target)) {
      return;
    }

    cog.debate = {
      opponentId: target.id,
      startedTick: this.tick,
      nextRoundTick: this.tick + this.config.debatePrepTicks,
      roundsResolved: 0,
    };
    target.debate = {
      opponentId: cog.id,
      startedTick: this.tick,
      nextRoundTick: this.tick + this.config.debatePrepTicks,
      roundsResolved: 0,
    };
    this.recordEvent({
      type: "debateStart",
      actorId: cog.id,
      targetId: target.id,
      message: `${cog.name} started debating ${target.name}`,
      position: cog.position,
    });
  }

  private canStartDebateBetween(cog: Cog, target: Cog): boolean {
    if (
      cog.id === target.id ||
      cog.debate ||
      cog.moving ||
      target.debate ||
      target.moving ||
      cog.color === target.color ||
      this.isDebatePairCoolingDown(cog.id, target.id)
    ) {
      return false;
    }

    if (this.venue && cog.location && target.location) {
      return this.areConnectedVenueDebatePartners(cog, target);
    }

    return isEligibleDebateTarget(cog, target);
  }

  private areConnectedVenueDebatePartners(cog: Cog, target: Cog): boolean {
    if (!cog.location || !target.location || cog.location.roomId !== target.location.roomId) {
      return false;
    }

    const section = this.venueSectionForRoom(cog.location.roomId);
    if (section && this.venueSectionHasActiveDebate(section)) {
      return false;
    }

    return venueSpotIsSpeaker(this.spotForLocation(cog.location)) && venueSpotIsSpeaker(this.spotForLocation(target.location));
  }

  private resolveActiveDebates(actions: Map<string, CogAction>): void {
    const handled = new Set<string>();

    for (const cog of this.cogs.values()) {
      const opponentId = cog.debate?.opponentId;
      if (!opponentId || handled.has(cog.id)) {
        continue;
      }

      const opponent = this.cogs.get(opponentId);
      if (!opponent || opponent.debate?.opponentId !== cog.id) {
        delete cog.debate;
        continue;
      }

      handled.add(cog.id);
      handled.add(opponent.id);
      if (cog.color === opponent.color || cog.moving || opponent.moving) {
        this.endDebate(cog, opponent);
        continue;
      }

      if (!this.isDebateRoundReady(cog, opponent)) {
        continue;
      }

      this.resolveDebateExchange(
        cog,
        opponent,
        debateChoice(actions.get(cog.id)),
        debateChoice(actions.get(opponent.id)),
      );
    }
  }

  private repairInvalidDebates(): void {
    const handled = new Set<string>();

    for (const cog of this.cogs.values()) {
      const opponentId = cog.debate?.opponentId;
      if (!opponentId || handled.has(cog.id)) {
        continue;
      }

      const opponent = this.cogs.get(opponentId);
      if (!opponent || opponent.debate?.opponentId !== cog.id) {
        delete cog.debate;
        continue;
      }

      handled.add(cog.id);
      handled.add(opponent.id);
      if (cog.color === opponent.color || cog.moving || opponent.moving) {
        this.endDebate(cog, opponent);
      }
    }
  }

  private resolveDebateExchange(first: Cog, second: Cog, firstChoice: DebateChoice, secondChoice: DebateChoice): void {
    const round = Math.max(first.debate?.roundsResolved ?? 0, second.debate?.roundsResolved ?? 0) + 1;
    const choicesRevealedAtTick = this.tick;
    const resultRevealedAtTick = this.tick + this.config.debateChoiceRevealTicks;
    const resultTicks = firstChoice === secondChoice ? Math.min(this.config.debateResultTicks, DRAW_RESULT_TICKS) : this.config.debateResultTicks;
    const expiresAtTick = resultRevealedAtTick + resultTicks;
    const nextRoundTick = expiresAtTick + this.config.debatePrepTicks;
    const beforeStates = this.captureDebateLogCogStates();
    this.markRoundResolved(first, second, nextRoundTick);

    if (firstChoice === secondChoice) {
      this.applyDrawTraitCertaintyLoss(first);
      this.applyDrawTraitCertaintyLoss(second);
      if (this.shouldEndDebateAfterRound(first, second)) {
        this.endDebate(first, second);
      }
      const detail = debateEventDetail(
        first,
        firstChoice,
        second,
        secondChoice,
        "draw",
        round,
        choicesRevealedAtTick,
        resultRevealedAtTick,
        expiresAtTick,
        undefined,
        [],
        this.debateRoomKind(first, second),
      );
      this.recordEvent({
        type: "debateExchange",
        actorId: first.id,
        targetId: second.id,
        message: `${first.name} and ${second.name} both chose ${firstChoice}`,
        position: first.position,
        debate: detail,
      });
      this.recordDebateLogEntry(first, firstChoice, second, secondChoice, detail, beforeStates);
      return;
    }

    const firstWins = tacticBeats(firstChoice, secondChoice);
    const winner = firstWins ? first : second;
    const loser = firstWins ? second : first;
    const winningTactic = firstWins ? firstChoice : secondChoice;
    winner.stats.argumentsWon += 1;
    loser.stats.argumentsLost += 1;
    this.reinforceColor(winner, winner.color, this.config.debateWinCertaintyGain);
    this.applyCertaintyLoss(loser, winner.color, this.config.debateDoubt, { source: winner, tactic: winningTactic, direct: true });
    const witnessCogIds = this.applyWitnessCertaintyChange(winner, loser, winningTactic);
    if (first.debate && second.debate && this.shouldEndDebateAfterRound(first, second)) {
      this.endDebate(first, second);
    }
    const detail = debateEventDetail(
      first,
      firstChoice,
      second,
      secondChoice,
      winner.id === first.id ? "win" : "lose",
      round,
      choicesRevealedAtTick,
      resultRevealedAtTick,
      expiresAtTick,
      winner,
      witnessCogIds,
      this.debateRoomKind(first, second),
    );
    this.recordEvent({
      type: "debateExchange",
      actorId: winner.id,
      targetId: loser.id,
      message: `${winner.name}'s ${winningTactic} shook ${loser.name}'s certainty`,
      position: winner.position,
      debate: detail,
    });
    this.recordDebateLogEntry(first, firstChoice, second, secondChoice, detail, beforeStates, witnessCogIds);
  }

  private captureDebateLogCogStates(): Map<string, DebateLogCogState> {
    return new Map(
      Array.from(this.cogs.values()).map((cog) => [
        cog.id,
        {
          name: cog.name,
          color: cog.color,
          certainty: cog.certainty,
        },
      ]),
    );
  }

  private recordDebateLogEntry(
    first: Cog,
    firstChoice: DebateChoice,
    second: Cog,
    secondChoice: DebateChoice,
    detail: DebateEventDetail,
    beforeStates: Map<string, DebateLogCogState>,
    witnessCogIds: string[] = [],
  ): void {
    const participantIds = [first.id, second.id];
    const changeIds = [...participantIds, ...witnessCogIds];
    const changes = changeIds.flatMap((cogId) => {
      const before = beforeStates.get(cogId);
      const after = this.cogs.get(cogId);
      if (!before || !after) {
        return [];
      }

      const role: DebateLogEntry["changes"][number]["role"] = participantIds.includes(cogId) ? "participant" : "witness";
      const certaintyDelta = after.certainty - before.certainty;
      if (role === "witness" && certaintyDelta === 0 && before.color === after.color) {
        return [];
      }

      return [{
        cogId,
        cogName: after.name,
        role,
        colorBefore: before.color,
        colorAfter: after.color,
        certaintyBefore: before.certainty,
        certaintyAfter: after.certainty,
        certaintyDelta,
      }];
    });

    this.debateLog.push({
      id: `debate_log_${nanoid(8)}`,
      tick: this.tick,
      round: detail.round,
      outcome: detail.outcome,
      winnerCogId: detail.winnerCogId,
      winnerColor: detail.winnerColor,
      actions: [
        debateLogAction(first, firstChoice, beforeStates),
        debateLogAction(second, secondChoice, beforeStates),
      ],
      changes,
      conversions: changes.flatMap((change) =>
        change.colorBefore === change.colorAfter
          ? []
          : [{
              cogId: change.cogId,
              cogName: change.cogName,
              fromColor: change.colorBefore,
              toColor: change.colorAfter,
              certaintyBefore: change.certaintyBefore,
              certaintyAfter: change.certaintyAfter,
            }],
      ),
    });
  }

  private endDebate(first: Cog, second: Cog): void {
    delete first.debate;
    delete second.debate;
    const cooldownTicks = Math.round(this.config.debateCooldownTicks * this.debateCooldownMultiplier(first, second));
    this.debateCooldowns.set(debatePairKey(first.id, second.id), this.tick + cooldownTicks);
  }

  private markRoundResolved(first: Cog, second: Cog, nextRoundTick: number): void {
    if (first.debate) {
      first.debate.roundsResolved += 1;
      first.debate.nextRoundTick = nextRoundTick;
    }
    if (second.debate) {
      second.debate.roundsResolved += 1;
      second.debate.nextRoundTick = nextRoundTick;
    }
  }

  private isDebateRoundReady(first: Cog, second: Cog): boolean {
    const firstReadyTick = first.debate?.nextRoundTick ?? first.debate?.startedTick ?? this.tick;
    const secondReadyTick = second.debate?.nextRoundTick ?? second.debate?.startedTick ?? this.tick;
    return this.tick >= Math.max(firstReadyTick, secondReadyTick);
  }

  private shouldEndDebateAfterRound(first: Cog, second: Cog): boolean {
    const rounds = Math.max(first.debate?.roundsResolved ?? 0, second.debate?.roundsResolved ?? 0);
    return rounds >= this.config.maxDebateRounds;
  }

  private isDebatePairCoolingDown(firstId: string, secondId: string): boolean {
    return (this.debateCooldowns.get(debatePairKey(firstId, secondId)) ?? 0) > this.tick;
  }

  private debateCooldownMultiplier(first: Cog, second: Cog): number {
    const multipliers = [first, second].flatMap((cog) => {
      return traitCodesFor(cog).flatMap((code) => {
        const multiplier = code.debateCooldownMultiplier?.({ cog, config: this.config });
        return typeof multiplier === "number" ? [multiplier] : [];
      });
    });
    return multipliers.length > 0 ? Math.min(...multipliers) : 1;
  }

  private reinforceColor(cog: Cog, color: Color, amount: number): void {
    if (cog.color === color) {
      cog.certainty = Math.min(this.config.conversionThreshold, cog.certainty + amount);
    }
  }

  private applyPassiveTraitCertaintyChanges(): void {
    let counts = this.populationCounts();
    const total = Array.from(counts.values()).reduce((sum, count) => sum + count, 0);
    if (total <= 0) {
      return;
    }

    for (const cog of this.cogs.values()) {
      if (cog.debate || cog.moving || this.convertedCogIdsThisTick.has(cog.id)) {
        continue;
      }

      const teamShare = (counts.get(cog.color) ?? 0) / total;
      const codes = traitCodesFor(cog);
      if (codes.some((code) => code.passiveColorFlip?.({ cog, teamShare, config: this.config }))) {
        if (this.flipCogColor(cog, undefined, "flipped")) {
          counts = this.populationCounts();
          continue;
        }
      }

      for (const code of codes) {
        const previousColor = cog.color;
        const change = code.passiveCertaintyChange?.({
          cog,
          teamShare,
          config: this.config,
        }) ?? 0;
        if (change > 0) {
          this.reinforceColor(cog, cog.color, change);
        } else if (change < 0) {
          this.applySelfDoubt(cog, -change);
          if (cog.color !== previousColor) {
            counts = this.populationCounts();
          }
          if (this.convertedCogIdsThisTick.has(cog.id)) {
            break;
          }
        }
      }
    }
  }

  private applyDrawTraitCertaintyLoss(cog: Cog): void {
    for (const code of traitCodesFor(cog)) {
      this.applySelfDoubt(cog, code.drawCertaintyLoss?.({ cog, config: this.config }) ?? 0);
    }
  }

  private applyRoomEntryTraitEffects(cog: Cog): void {
    const sameRoomCogs = this.sameRoomCogs(cog);
    const amount = traitCodesFor(cog).reduce(
      (sum, code) => sum + (code.roomEntryCertaintyLoss?.({ cog, sameRoomCogs, config: this.config }) ?? 0),
      0,
    );

    this.applySelfDoubt(cog, amount);
  }

  private applyPreConversionTraitEffects(cog: Cog, previousColor: Color, winningColor: Color): void {
    const sameRoomCogs = this.sameRoomCogs(cog).filter((candidate) => candidate.id !== cog.id);
    for (const code of traitCodesFor(cog)) {
      const effect = code.ownConversion?.({
        convertedCog: cog,
        sameRoomCogs,
        previousColor,
        winningColor,
        config: this.config,
      });
      this.applyConversionTraitEffect(effect);
    }

    for (const teammate of sameRoomCogs) {
      for (const code of traitCodesFor(teammate)) {
        const effect = code.teammateConverted?.({
          teammate,
          convertedCog: cog,
          previousColor,
          winningColor,
          config: this.config,
        });
        this.applyConversionTraitEffect(effect);
      }
    }
  }

  private applyConversionTraitEffect(effect: TraitConversionEffect | undefined): void {
    for (const recovery of effect?.recoveries ?? []) {
      const teammate = this.cogs.get(recovery.cogId);
      if (!teammate) {
        continue;
      }
      this.reinforceColor(teammate, recovery.color, recovery.amount);
      this.martyrProtectedCogIdsThisTick.add(teammate.id);
    }
    for (const target of effect?.avengerTargets ?? []) {
      this.avengerTargets.set(target.cogId, target.color);
    }
  }

  private applySelfDoubt(cog: Cog, amount: number, source?: Cog): void {
    if (amount <= 0 || this.convertedCogIdsThisTick.has(cog.id)) {
      return;
    }

    cog.certainty = Math.max(0, cog.certainty - amount);
    this.tryConvertColor(cog, source);
  }

  private applyCertaintyLoss(
    target: Cog,
    color: Color,
    baseAmount: number,
    options: { source: Cog; tactic?: DebateTactic; direct: boolean },
  ): void {
    if (target.color === color) {
      this.reinforceColor(target, color, baseAmount);
      return;
    }

    let amount = baseAmount;
    if (options.direct) {
      const avengerTargetColor = this.avengerTargets.get(options.source.id);
      for (const code of traitCodesFor(options.source)) {
        amount *= code.directSourceMultiplier?.({
          source: options.source,
          target,
          tactic: options.tactic,
          avengerTargetColor,
          config: this.config,
        }) ?? 1;
      }
      if (avengerTargetColor === target.color) {
        this.avengerTargets.delete(options.source.id);
      }
    }

    for (const code of traitCodesFor(target)) {
      amount *= options.direct
        ? code.directTargetMultiplier?.({ source: options.source, target, tactic: options.tactic, config: this.config }) ?? 1
        : code.indirectTargetMultiplier?.({ source: options.source, target, tactic: options.tactic, config: this.config }) ?? 1;
      amount *= code.pressureTargetMultiplier?.({
        source: options.source,
        target,
        pressureColor: color,
        pressureTeamShare: this.populationShare(color),
        uniquePopulationColor: (kind) => this.uniquePopulationColor(kind),
        config: this.config,
      }) ?? 1;
    }

    target.certainty = Math.max(0, target.certainty - amount);
    this.tryConvertColor(target, options.source);
  }

  private applyWitnessCertaintyChange(winner: Cog, loser: Cog, tactic: DebateTactic): string[] {
    const witnessCogIds: string[] = [];
    let amount = this.config.witnessDoubt;
    for (const code of traitCodesFor(winner)) {
      amount = code.witnessBaseAmount?.({ winner, loser, config: this.config }) ?? amount;
    }
    for (const code of traitCodesFor(winner)) {
      amount *= code.witnessAmountMultiplier?.({
        winner,
        loser,
        uniquePopulationColor: (kind) => this.uniquePopulationColor(kind),
        config: this.config,
      }) ?? 1;
    }
    const venueDebateRoomId = winner.location?.roomId === loser.location?.roomId ? winner.location?.roomId : undefined;
    if (amount <= 0 || !venueDebateRoomId) {
      return witnessCogIds;
    }

    for (const witness of this.cogs.values()) {
      if (
        witness.id === winner.id ||
        witness.id === loser.id ||
        witness.location?.roomId !== venueDebateRoomId
      ) {
        continue;
      }

      witnessCogIds.push(witness.id);
      if (witness.color === winner.color) {
        const effect = [...traitCodesFor(winner), ...traitCodesFor(witness)]
          .map((code) =>
            code.sameTeamWitnessEffect?.({
              winner,
              loser,
              witness,
              uniquePopulationColor: (kind) => this.uniquePopulationColor(kind),
              config: this.config,
            }),
          )
          .find(Boolean);
        if (effect?.type === "selfDoubt") {
          this.applySelfDoubt(witness, effect.amount, winner);
          continue;
        }

        this.reinforceColor(witness, winner.color, amount);
        continue;
      }

      if (this.martyrProtectedCogIdsThisTick.has(witness.id)) {
        continue;
      }

      this.applyCertaintyLoss(witness, winner.color, amount, {
        source: winner,
        tactic,
        direct: false,
      });
    }

    return witnessCogIds;
  }

  private tryConvertColor(cog: Cog, source?: Cog): boolean {
    if (cog.certainty > 0) {
      return false;
    }

    return this.flipCogColor(cog, source, "converted");
  }

  private flipCogColor(cog: Cog, source: Cog | undefined, verb: "converted" | "flipped"): boolean {
    for (const code of traitCodesFor(cog)) {
      const minimumCertainty = code.blocksConversion?.({ cog, config: this.config });
      if (typeof minimumCertainty === "number") {
        cog.certainty = Math.max(0, minimumCertainty);
        return false;
      }
    }

    const previousMajority = this.uniquePopulationColor("highest");
    const previousColor = cog.color;
    const winningColor = oppositeTeamColor(previousColor);
    this.applyPreConversionTraitEffects(cog, previousColor, winningColor);
    cog.color = winningColor;
    cog.stats.teamFlips += 1;
    cog.certainty = this.config.conversionThreshold * (1 - this.config.conversionDoubtPercent / 100);
    this.convertedCogIdsThisTick.add(cog.id);
    const opponent = cog.debate ? this.cogs.get(cog.debate.opponentId) : undefined;
    if (opponent) {
      this.endDebate(cog, opponent);
    } else {
      delete cog.debate;
    }
    this.recordEvent({
      type: "colorChange",
      actorId: cog.id,
      message: `${cog.name} ${verb} from ${previousColor} to ${winningColor}`,
      position: cog.position,
    });
    this.recordMajorityChange(previousMajority);
    return true;
  }

  private recordMajorityChange(previousMajority: Color | undefined): void {
    const majorityColor = this.uniquePopulationColor("highest");
    if (!majorityColor || majorityColor === previousMajority) {
      return;
    }

    this.recordEvent({
      type: "gameFlow",
      message: `${titleCase(majorityColor)} reaches majority`,
    });
  }

  private uniquePopulationColor(kind: "highest" | "lowest"): Color | undefined {
    const counts = this.populationCounts();
    const sorted = [...counts.entries()].sort((a, b) => (kind === "highest" ? b[1] - a[1] : a[1] - b[1]));
    if (sorted.length < 2 || sorted[0][1] === sorted[1][1]) {
      return undefined;
    }
    return sorted[0][0];
  }

  private populationCounts(): Map<Color, number> {
    const counts = new Map<Color, number>(TEAM_COLORS.map((color) => [color, 0]));
    for (const cog of this.cogs.values()) {
      counts.set(cog.color, (counts.get(cog.color) ?? 0) + 1);
    }
    return counts;
  }

  private populationShare(color: Color): number {
    const counts = this.populationCounts();
    const total = Array.from(counts.values()).reduce((sum, count) => sum + count, 0);
    if (total <= 0) {
      return 0;
    }

    return (counts.get(color) ?? 0) / total;
  }

  private sameRoomCogs(cog: Cog): Cog[] {
    const roomId = cog.location?.roomId;
    if (!roomId) {
      return [];
    }

    return Array.from(this.cogs.values()).filter((candidate) => candidate.location?.roomId === roomId);
  }

  private debateRoomKind(first: Cog, second: Cog): VenueRoom["kind"] | undefined {
    const roomId = first.location?.roomId === second.location?.roomId ? first.location?.roomId : undefined;
    return roomId ? this.roomForId(roomId)?.kind : undefined;
  }

  private updateAchievements(): void {
    const achievementEvents = this.recentEvents.map((event) => cloneEvent(event));
    const snapshot = this.snapshot();
    for (const cog of this.cogs.values()) {
      this.updateCogAchievements(cog, achievementEvents, snapshot);
    }
  }

  private updateCogAchievements(cog: Cog, events: WorldEvent[], snapshot: WorldSnapshot): void {
    ensureAchievementCollections(cog);
    const activeAchievements: AchievementAssignment[] = [];

    for (const achievement of cog.achievements) {
      let rule;
      try {
        rule = achievementDefinitionById(achievement.achievementId);
      } catch {
        continue;
      }

      if (rule.isAchieved({ assignment: achievement, cog, events, snapshot, tick: this.tick })) {
        const completed = {
          ...achievement,
          completedTick: this.tick,
          points: rule.points,
        };
        cog.completedAchievements.push(completed);
        this.incrementAchievementCount(achievement, "completed");
        this.awardScore(
          cog,
          rule.points,
          `${cog.name} completed ${achievementDisplayName(achievement)} for ${rule.points} points`,
        );
        continue;
      }

      if (this.tick >= achievement.timeoutTick) {
        cog.failedAchievements.push({
          ...achievement,
          failedTick: this.tick,
        });
        this.incrementAchievementCount(achievement, "expired");
        continue;
      }

      activeAchievements.push(achievement);
    }

    cog.achievements = activeAchievements;
    this.fillActiveAchievements(cog);
  }

  private fillActiveAchievements(cog: Cog): void {
    ensureAchievementCollections(cog);
    while (cog.achievements.length < ACTIVE_ACHIEVEMENT_COUNT) {
      const candidate = this.nextAchievementCandidate(cog);
      if (!candidate) {
        return;
      }

      const assignment = {
        assignmentId: `achievement_${nanoid(8)}`,
        achievementId: candidate.rule.id,
        parameters: cloneAchievementParameters(candidate.parameters),
        assignedTick: this.tick,
        timeoutTick: this.tick + candidate.rule.timeoutTicks,
      };
      cog.achievements.push(assignment);
      this.incrementAchievementCount(assignment, "assigned");
    }
  }

  private nextAchievementCandidate(cog: Cog): AchievementCandidate | undefined {
    const activeIds = new Set(cog.achievements.map((achievement) => achievement.achievementId));
    const completedIds = new Set(cog.completedAchievements.map(achievementKey));
    const uncompletedCandidates = ACHIEVEMENT_RULES.flatMap((rule): AchievementCandidate[] => {
      if (activeIds.has(rule.id)) {
        return [];
      }
      return this.instantiateAchievementParameterCandidates(rule, cog)
        .filter((parameters) => !completedIds.has(achievementKey({ achievementId: rule.id, parameters })))
        .map((parameters) => ({ rule, parameters }));
    });

    return uncompletedCandidates.length > 0 ? this.random.choice(uncompletedCandidates) : undefined;
  }

  private instantiateAchievementParameterCandidates(rule: AchievementRule, cog: Cog): Array<AchievementAssignment["parameters"]> {
    let candidates: AchievementParameters[] = [cloneAchievementParameters(rule.parameters) ?? {}];

    if (rule.templateVariables.includes("trait") && !rule.parameters?.trait) {
      candidates = expandAchievementParameters(candidates, ACHIEVEMENT_TRAITS, (parameters, trait) => ({ ...parameters, trait }));
    }
    if (rule.templateVariables.includes("team") && !rule.parameters?.team) {
      candidates = expandAchievementParameters(candidates, TEAM_COLORS, (parameters, team) => ({ ...parameters, team }));
    }
    if (rule.templateVariables.includes("rounds") && !rule.parameters?.rounds) {
      candidates = candidates.map((parameters) => ({ ...parameters, rounds: 3 }));
    }
    if (rule.templateVariables.includes("room") && !rule.parameters?.roomKind) {
      const roomKinds = this.achievementRoomKinds();
      if (!roomKinds.length) {
        return [];
      }
      candidates = expandAchievementParameters(candidates, roomKinds, (parameters, roomKind) => ({ ...parameters, roomKind }));
    }
    if (rule.templateVariables.includes("tactic") && !rule.parameters?.tactic) {
      candidates = expandAchievementParameters(candidates, ACHIEVEMENT_TACTICS, (parameters, tactic) => ({ ...parameters, tactic }));
    }
    if (rule.templateVariables.includes("cog") && !rule.parameters?.cogId) {
      const targetCogs = [...this.cogs.values()].filter((candidate) => candidate.id !== cog.id);
      if (!targetCogs.length) {
        return [];
      }
      candidates = expandAchievementParameters(candidates, targetCogs, (parameters, target) => ({
        ...parameters,
        cogId: target.id,
        cogName: target.name,
      }));
    }

    return candidates.map((parameters) => (Object.keys(parameters).length > 0 ? parameters : undefined));
  }

  private achievementRoomKinds(): VenueRoom["kind"][] {
    return [...new Set(this.venue?.rooms.map((room) => room.kind) ?? [])].sort();
  }

  private incrementAchievementCount(
    achievement: Pick<AchievementCount, "achievementId" | "parameters">,
    field: "assigned" | "completed" | "expired",
  ): void {
    const key = achievementKey(achievement);
    const current = this.achievementCounts.get(key) ?? {
      achievementId: achievement.achievementId,
      parameters: cloneAchievementParameters(achievement.parameters),
      assigned: 0,
      completed: 0,
      expired: 0,
    };
    current[field] += 1;
    this.achievementCounts.set(key, current);
  }

  private snapshotAchievementCounts(): AchievementCount[] {
    const activeCounts = new Map<string, number>();
    for (const cog of this.cogs.values()) {
      for (const achievement of cog.achievements) {
        const key = achievementKey(achievement);
        activeCounts.set(key, (activeCounts.get(key) ?? 0) + 1);
      }
    }

    const counters = new Map(this.achievementCounts);
    for (const cog of this.cogs.values()) {
      for (const achievement of [...cog.achievements, ...cog.completedAchievements, ...(cog.failedAchievements ?? [])]) {
        const key = achievementKey(achievement);
        if (!counters.has(key)) {
          counters.set(key, {
            achievementId: achievement.achievementId,
            parameters: cloneAchievementParameters(achievement.parameters),
            assigned: 0,
            completed: 0,
            expired: 0,
          });
        }
      }
    }

    return Array.from(counters.values()).map((count) => ({
      ...cloneAchievementCounter(count),
      current: activeCounts.get(achievementKey(count)) ?? 0,
    }));
  }

  private awardScore(
    cog: Cog,
    points: number,
    message?: string,
  ): void {
    if (points <= 0) {
      return;
    }

    const normalizedPoints = points / scoreLifetimeTicks(cog);
    if (normalizedPoints <= 0 || !Number.isFinite(normalizedPoints)) {
      return;
    }

    cog.personalScore += normalizedPoints;
    if (message) {
      this.recordEvent({
        type: "score",
        actorId: cog.id,
        message,
        position: cog.position,
      });
    }
  }

  private uniqueCogName(requestedName: string, exceptCogId?: string): string {
    const baseName = requestedName.trim() || "Cog";
    const usedNames = new Set(
      Array.from(this.cogs.values())
        .filter((cog) => cog.id !== exceptCogId)
        .map((cog) => normalizeCogName(cog.name)),
    );

    const firstName = truncateCogName(baseName);
    if (!usedNames.has(normalizeCogName(firstName))) {
      return firstName;
    }

    for (let suffix = 2; suffix < 10_000; suffix += 1) {
      const suffixText = ` ${suffix}`;
      const candidate = `${truncateCogName(baseName, suffixText.length)}${suffixText}`;
      if (!usedNames.has(normalizeCogName(candidate))) {
        return candidate;
      }
    }

    throw new Error(`Unable to assign a unique cog name for ${baseName}`);
  }

  private entityAt(position: Position): Cog | WorldObject | undefined {
    return (
      Array.from(this.cogs.values()).find((cog) => samePosition(cog.position, position)) ??
      Array.from(this.objects.values()).find((object) => samePosition(object.position, position))
    );
  }

  private advanceCogLifetimes(): void {
    for (const cog of this.cogs.values()) {
      cog.ticksAlive = sanitizeCogTicksAlive(cog.ticksAlive) + 1;
    }
  }

  private advanceMovingCogs(): void {
    for (const cog of this.cogs.values()) {
      if (!cog.moving) {
        continue;
      }

      if (this.tick >= cog.moving.arriveTick) {
        const destination = this.spotForLocation(cog.moving.to);
        const destinationPosition = destination?.position ?? cog.moving.toPosition;
        const changedRooms = cog.moving.from.roomId !== cog.moving.to.roomId;
        const destinationLocation = cloneVenueLocation(cog.moving.to);
        cog.location = destinationLocation;
        cog.position = clonePosition(destinationPosition);
        if (changedRooms) {
          cog.lastVenueMoveTick = this.tick;
          this.addCogRoomHistoryEntry(cog, destinationLocation, this.tick);
        }
        delete cog.moving;
        this.recordEvent({
          type: "move",
          actorId: cog.id,
          message: `${cog.name} arrived at ${destination ? this.spotLabel(destination) : cog.location.roomId}`,
          position: cog.position,
        });
        if (changedRooms) {
          this.applyRoomEntryTraitEffects(cog);
        }
        continue;
      }

      cog.position = positionAlongPath(venueMovementPath(cog.moving), venueMovementDistanceAtTick(cog.moving, this.tick));
    }
  }

  private closeCogRoomHistory(cog: Cog, tick: number): void {
    const history = cog.roomHistory ?? [];
    const current = history[history.length - 1];
    if (current && current.leftTick === undefined) {
      current.leftTick = tick;
    }
    cog.roomHistory = history;
  }

  private addCogRoomHistoryEntry(cog: Cog, location: VenueLocation, tick: number): void {
    const history = cog.roomHistory ?? [];
    const last = history[history.length - 1];
    if (last && last.roomId === location.roomId && last.leftTick === undefined) {
      last.spotId = location.spotId;
      this.trimCogRoomHistory(cog);
      return;
    }

    history.push(cogRoomHistoryEntry(location, tick));
    cog.roomHistory = history;
    this.trimCogRoomHistory(cog);
  }

  private trimCogRoomHistory(cog: Cog): void {
    if (!cog.roomHistory || cog.roomHistory.length <= MAX_COG_ROOM_HISTORY) {
      return;
    }

    cog.roomHistory = cog.roomHistory.slice(-MAX_COG_ROOM_HISTORY);
  }

  private reconcileCogRoomHistories(): void {
    for (const cog of this.cogs.values()) {
      cog.roomHistory = cloneCogRoomHistory(cog.roomHistory);
      const latest = cog.roomHistory[cog.roomHistory.length - 1];
      if (cog.location && (!latest || latest.roomId !== cog.location.roomId || latest.leftTick !== undefined)) {
        this.addCogRoomHistoryEntry(
          cog,
          cog.location,
          typeof cog.lastVenueMoveTick === "number" ? cog.lastVenueMoveTick : this.tick,
        );
      } else {
        this.trimCogRoomHistory(cog);
      }
    }
  }

  private reconcileVenueCogPlacements(): void {
    if (!this.venue) {
      return;
    }

    for (const cog of this.cogs.values()) {
      if (cog.moving) {
        const from = this.spotForLocation(cog.moving.from);
        const to = this.spotForLocation(cog.moving.to);
        if (from && to) {
          cog.moving.fromPosition = clonePosition(from.position);
          cog.moving.toPosition = clonePosition(to.position);
          cog.moving.path = this.venueMovePath(from, to);
          cog.moving.arriveTick = cog.moving.startedTick + venueMoveDurationTicks(cog.moving.path, this.dimensions);
          cog.position = positionAlongPath(venueMovementPath(cog.moving), venueMovementDistanceAtTick(cog.moving, this.tick));
          continue;
        }

        const fallbackSpot = to ?? from;
        delete cog.moving;
        if (fallbackSpot?.roomId) {
          cog.location = { roomId: fallbackSpot.roomId, spotId: fallbackSpot.id };
          cog.position = clonePosition(fallbackSpot.position);
        } else {
          delete cog.location;
        }
        continue;
      }

      if (!cog.location) {
        continue;
      }

      const spot = this.spotForLocation(cog.location) ?? this.replacementSpotForMissingLocation(cog.location);
      if (spot?.roomId) {
        cog.location = { roomId: spot.roomId, spotId: spot.id };
        cog.position = clonePosition(spot.position);
      } else {
        delete cog.location;
      }
    }
  }

  private spotForLocation(location: VenueLocation): VenueSpot | undefined {
    return this.venue?.spots.find((spot) => spot.id === location.spotId && spot.roomId === location.roomId);
  }

  private roomForId(roomId: string): VenueRoom | undefined {
    return this.venue?.rooms.find((room) => room.id === roomId);
  }

  private replacementSpotForMissingLocation(location: VenueLocation): VenueSpot | undefined {
    const roomSpots = this.spotsForRoom(location.roomId);
    return roomSpots.find((spot) => !this.isVenueSpotOccupied(spot)) ?? roomSpots[0];
  }

  private roomForDirection(origin: VenueRoom, direction: Direction): VenueRoom | undefined {
    const originCenter = this.roomCenter(origin);
    const candidates = origin.neighborIds.flatMap((roomId) => {
      const room = this.roomForId(roomId);
      return room ? [room] : [];
    });
    const directionalCandidates = candidates.filter((room) => isInDirection(originCenter, this.roomCenter(room), direction));
    directionalCandidates.sort((left, right) => squaredDistance(originCenter, this.roomCenter(left)) - squaredDistance(originCenter, this.roomCenter(right)));
    return directionalCandidates[0];
  }

  private roomCenter(room: VenueRoom): Position {
    const spots = this.spotsForRoom(room.id);
    if (spots.length === 0) {
      return { x: 0, y: 0 };
    }

    return {
      x: spots.reduce((sum, spot) => sum + spot.position.x, 0) / spots.length,
      y: spots.reduce((sum, spot) => sum + spot.position.y, 0) / spots.length,
    };
  }

  private spotsForRoom(roomId: string): VenueSpot[] {
    return this.venue?.spots.filter((spot) => spot.roomId === roomId) ?? [];
  }

  private venueSectionForRoom(roomId: string): VenueSection | undefined {
    return this.venue ? venueRoomSection(roomId, this.dimensions, this.venue) : undefined;
  }

  private venueSectionHasActiveDebate(section: VenueSection): boolean {
    return Array.from(this.cogs.values()).some((cog) => {
      if (!cog.debate || !cog.location) {
        return false;
      }

      return this.venueSectionForRoom(cog.location.roomId) === section;
    });
  }

  private emptySpotInRoom(roomId: string): VenueSpot | undefined {
    return this.spotsForRoom(roomId).find((spot) => !this.isVenueSpotOccupied(spot));
  }

  private preferredEntrySpotInRoom(roomId: string): VenueSpot | undefined {
    const occupiedSpotIds = this.occupiedVenueSpotIdsInRoom(roomId);
    const emptySpots = this.spotsForRoom(roomId)
      .map((spot, index) => ({ spot, index }))
      .filter(({ spot }) => !this.isVenueSpotOccupied(spot));
    if (emptySpots.length === 0) {
      return undefined;
    }
    if (occupiedSpotIds.size === 0) {
      return emptySpots[0]?.spot;
    }

    emptySpots.sort((left, right) => {
      const linkedRank = Number(!this.spotLinksAnyOccupiedSpot(left.spot, occupiedSpotIds)) - Number(!this.spotLinksAnyOccupiedSpot(right.spot, occupiedSpotIds));
      return linkedRank || this.nearestOccupiedSpotDistance(left.spot, occupiedSpotIds) - this.nearestOccupiedSpotDistance(right.spot, occupiedSpotIds) || left.index - right.index;
    });
    return emptySpots[0]?.spot;
  }

  private occupiedVenueSpotIdsInRoom(roomId: string): Set<string> {
    const occupiedSpotIds = new Set<string>();
    for (const cog of this.cogs.values()) {
      const location = cog.location?.roomId === roomId ? cog.location : cog.moving?.to.roomId === roomId ? cog.moving.to : undefined;
      if (location) {
        occupiedSpotIds.add(location.spotId);
      }
    }
    return occupiedSpotIds;
  }

  private spotLinksAnyOccupiedSpot(spot: VenueSpot, occupiedSpotIds: Set<string>): boolean {
    return Boolean(
      this.venue?.spotLinks.some(
        (link) =>
          (link.fromSpotId === spot.id && occupiedSpotIds.has(link.toSpotId)) ||
          (link.toSpotId === spot.id && occupiedSpotIds.has(link.fromSpotId)),
      ),
    );
  }

  private nearestOccupiedSpotDistance(spot: VenueSpot, occupiedSpotIds: Set<string>): number {
    const occupiedSpots = this.spotsForRoom(spot.roomId).filter((candidate) => occupiedSpotIds.has(candidate.id));
    if (occupiedSpots.length === 0) {
      return 0;
    }

    return Math.min(...occupiedSpots.map((candidate) => squaredDistance(spot.position, candidate.position)));
  }

  private isVenueSpotOccupied(spot: VenueSpot): boolean {
    return Array.from(this.cogs.values()).some(
      (cog) => cog.location?.spotId === spot.id || cog.moving?.from.spotId === spot.id || cog.moving?.to.spotId === spot.id,
    );
  }

  private isAloneInVenueRoom(cog: Cog, roomId: string): boolean {
    let cogsInRoom = 0;
    for (const candidate of this.cogs.values()) {
      if (candidate.location?.roomId === roomId) {
        cogsInRoom += 1;
      }
      if (cogsInRoom > 1) {
        return false;
      }
    }
    return cogsInRoom === 1 && cog.location?.roomId === roomId;
  }

  private roomHasOtherCogs(roomId: string, cogId: string): boolean {
    for (const candidate of this.cogs.values()) {
      if (candidate.id !== cogId && candidate.location?.roomId === roomId) {
        return true;
      }
    }
    return false;
  }

  private isVenueMoveOnCooldown(cog: Cog): boolean {
    return this.remainingVenueMoveCooldownTicks(cog) > 0;
  }

  private remainingVenueMoveCooldownTicks(cog: Cog): number {
    if (typeof cog.lastVenueMoveTick !== "number" || this.config.roomMoveCooldownTicks <= 0) {
      return 0;
    }
    const cooldownTicks = this.config.roomMoveCooldownTicks;
    if (cooldownTicks <= 0) {
      return 0;
    }
    const elapsedTicks = this.tick - cog.lastVenueMoveTick;
    return Math.max(0, cooldownTicks - elapsedTicks);
  }

  private spotLabel(spot: VenueSpot): string {
    const room = this.venue?.rooms.find((candidate) => candidate.id === spot.roomId);
    return `${room?.label ?? spot.roomId} - ${spot.label}`;
  }

  private findEmptyVenueSpot(): VenueSpot | undefined {
    return this.venue?.spots.find((spot) => !this.isVenueSpotOccupied(spot) && !this.entityAt(spot.position));
  }

  private findEmptyEdgeCell(): Position {
    const candidates: Position[] = [];
    for (let y = 0; y < this.dimensions.height; y += 1) {
      for (let x = 0; x < this.dimensions.width; x += 1) {
        const position = { x, y };
        if (!isEdgePosition(position, this.dimensions) || this.entityAt(position) || this.terrainAt(position) === "wall") {
          continue;
        }

        candidates.push(position);
      }
    }

    if (candidates.length === 0) {
      throw new Error("No empty edge tile is available for cog spawn");
    }

    return clonePosition(this.random.choice(candidates));
  }

  private terrainAt(position: Position): Terrain {
    return this.terrain.get(positionKey(position)) ?? "floor";
  }

  private snapshotTerrain(): TerrainCell[] {
    return Array.from(this.terrain.entries()).map(([key, terrain]) => ({
      position: positionFromKey(key),
      terrain,
    }));
  }

  private isInsideBounds(position: Position): boolean {
    return position.x >= 0 && position.y >= 0 && position.x < this.dimensions.width && position.y < this.dimensions.height;
  }

  private recordEvent(event: Omit<WorldEvent, "id" | "tick">): void {
    this.recentEvents.push({
      ...event,
      position: event.position ? clonePosition(event.position) : undefined,
      id: `event_${nanoid(8)}`,
      tick: this.tick,
    });

    while (this.recentEvents.length > MAX_RECENT_EVENTS) {
      this.recentEvents.shift();
    }
  }
}

function samePosition(a: Position, b: Position): boolean {
  return a.x === b.x && a.y === b.y;
}

function positionKey(position: Position): string {
  return `${position.x},${position.y}`;
}

function positionFromKey(key: string): Position {
  const [x, y] = key.split(",").map((value) => Number.parseInt(value, 10));
  return { x, y };
}

function isEdgePosition(position: Position, dimensions: WorldDimensions): boolean {
  return position.x === 0 || position.y === 0 || position.x === dimensions.width - 1 || position.y === dimensions.height - 1;
}

function isInDirection(origin: Position, target: Position, direction: Direction): boolean {
  const dx = target.x - origin.x;
  const dy = target.y - origin.y;
  switch (direction) {
    case "north":
      return dy < 0 && Math.abs(dy) >= Math.abs(dx);
    case "south":
      return dy > 0 && Math.abs(dy) >= Math.abs(dx);
    case "east":
      return dx > 0 && Math.abs(dx) >= Math.abs(dy);
    case "west":
      return dx < 0 && Math.abs(dx) >= Math.abs(dy);
  }
}

function areAdjacent(a: Position, b: Position): boolean {
  return Math.abs(a.x - b.x) + Math.abs(a.y - b.y) === 1;
}

function squaredDistance(a: Position, b: Position): number {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  return dx * dx + dy * dy;
}

function shuffledBalancedColors(count: number, random: SeededRandom): Color[] {
  const deck = Array.from({ length: count }, (_value, index) => TEAM_COLORS[index % TEAM_COLORS.length]);
  for (let index = deck.length - 1; index > 0; index -= 1) {
    const swapIndex = random.int(index + 1);
    [deck[index], deck[swapIndex]] = [deck[swapIndex], deck[index]];
  }
  return deck;
}

function avoidNoopShuffle(cogs: readonly Cog[], nextColors: Color[]): void {
  if (nextColors.length <= 1 || cogs.some((cog, index) => cog.color !== nextColors[index])) {
    return;
  }

  const firstColor = nextColors.shift();
  if (firstColor) {
    nextColors.push(firstColor);
  }
}

function debateChoice(action: CogAction | undefined): DebateChoice {
  if (action?.type === "chooseTactic") {
    return action.tactic;
  }

  return "reason";
}

function debateEventDetail(
  first: Cog,
  firstChoice: DebateChoice,
  second: Cog,
  secondChoice: DebateChoice,
  outcome: DebateEventDetail["outcome"],
  round: number,
  choicesRevealedAtTick: number,
  resultRevealedAtTick: number,
  expiresAtTick: number,
  winner?: Cog,
  witnessCogIds: string[] = [],
  roomKind?: VenueRoom["kind"],
): DebateEventDetail {
  return {
    actions: [
      { cogId: first.id, action: firstChoice },
      { cogId: second.id, action: secondChoice },
    ],
    choicesRevealedAtTick,
    resultRevealedAtTick,
    expiresAtTick,
    outcome,
    round,
    roomKind,
    winnerCogId: winner?.id,
    winnerColor: winner?.color,
    ...(witnessCogIds.length > 0 ? { witnessCogIds: [...witnessCogIds] } : {}),
  };
}

function debateLogAction(cog: Cog, tactic: DebateChoice, beforeStates: Map<string, DebateLogCogState>): DebateLogEntry["actions"][number] {
  return {
    cogId: cog.id,
    cogName: beforeStates.get(cog.id)?.name ?? cog.name,
    color: beforeStates.get(cog.id)?.color ?? cog.color,
    tactic,
  };
}

function debatePairKey(firstId: string, secondId: string): string {
  return [firstId, secondId].sort().join(":");
}

function tacticBeats(a: DebateTactic, b: DebateTactic): boolean {
  return (
    (a === "reason" && b === "spin") ||
    (a === "spin" && b === "passion") ||
    (a === "passion" && b === "reason")
  );
}

function traitCodeFor(trait: Trait): TraitCode {
  return traitDefinitionFor(trait).code;
}

function traitCodesFor(cog: Cog): TraitCode[] {
  return Array.from(new Set([cog.defensiveTrait, cog.activeTrait])).map(traitCodeFor);
}

function zealotSlotKey(defensiveTrait: Trait, activeTrait: Trait): string {
  return [
    defensiveTrait === "zealot" ? "defensiveTrait" : "",
    activeTrait === "zealot" ? "activeTrait" : "",
  ].join("|");
}

function mergeTraitConfigInput(base: TraitConfig, input: TraitConfigInput | undefined): TraitConfig {
  return Object.fromEntries(
    Object.entries(base).map(([traitId, traitConfig]) => [
      traitId,
      {
        ...traitConfig,
        ...(input?.[traitId as keyof TraitConfig] ?? {}),
      },
    ]),
  ) as TraitConfig;
}

function createCogStats(): Cog["stats"] {
  return {
    argumentsWon: 0,
    argumentsLost: 0,
    teamFlips: 0,
  };
}

function createGoalScoreTracks(_tick: number): GoalScoreTrack[] {
  return [];
}

function ensureAchievementCollections(cog: Cog): void {
  cog.achievements ??= [];
  cog.completedAchievements ??= [];
  cog.failedAchievements ??= [];
}

function cloneGoalScoreTracks(_goalScores: GoalScoreTrack[] | undefined): GoalScoreTrack[] {
  return [];
}

function cloneAchievementAssignments(achievements: AchievementAssignment[] | undefined): AchievementAssignment[] {
  return (achievements ?? [])
    .filter((achievement) => isKnownAchievementId(achievement.achievementId))
    .map((achievement) => ({
      ...achievement,
      parameters: cloneAchievementParameters(achievement.parameters),
    }));
}

function cloneCompletedAchievements(achievements: CompletedAchievement[] | undefined): CompletedAchievement[] {
  return (achievements ?? [])
    .filter((achievement) => isKnownAchievementId(achievement.achievementId))
    .map((achievement) => ({
      ...achievement,
      parameters: cloneAchievementParameters(achievement.parameters),
    }));
}

function cloneFailedAchievements(achievements: FailedAchievement[] | undefined): FailedAchievement[] {
  return (achievements ?? [])
    .filter((achievement) => isKnownAchievementId(achievement.achievementId))
    .map((achievement) => ({
      ...achievement,
      parameters: cloneAchievementParameters(achievement.parameters),
    }));
}

function isKnownAchievementId(id: string): id is AchievementAssignment["achievementId"] {
  try {
    achievementDefinitionById(id as AchievementAssignment["achievementId"]);
    return true;
  } catch {
    return false;
  }
}

function cloneAchievementCounter(count: AchievementCounter): AchievementCounter {
  return {
    achievementId: count.achievementId,
    parameters: cloneAchievementParameters(count.parameters),
    assigned: count.assigned,
    completed: count.completed,
    expired: count.expired,
  };
}

function inferAchievementCountersFromCogs(cogs: Cog[]): AchievementCounter[] {
  const counts = new Map<string, AchievementCounter>();
  for (const cog of cogs) {
    for (const achievement of cog.achievements) {
      if (!isKnownAchievementId(achievement.achievementId)) {
        continue;
      }
      const key = achievementKey(achievement);
      const count = counts.get(key) ?? {
        achievementId: achievement.achievementId,
        parameters: cloneAchievementParameters(achievement.parameters),
        assigned: 0,
        completed: 0,
        expired: 0,
      };
      count.assigned += 1;
      counts.set(key, count);
    }
    for (const achievement of cog.completedAchievements) {
      if (!isKnownAchievementId(achievement.achievementId)) {
        continue;
      }
      const key = achievementKey(achievement);
      const count = counts.get(key) ?? {
        achievementId: achievement.achievementId,
        parameters: cloneAchievementParameters(achievement.parameters),
        assigned: 0,
        completed: 0,
        expired: 0,
      };
      count.assigned += 1;
      count.completed += 1;
      counts.set(key, count);
    }
    for (const achievement of cog.failedAchievements ?? []) {
      if (!isKnownAchievementId(achievement.achievementId)) {
        continue;
      }
      const key = achievementKey(achievement);
      const count = counts.get(key) ?? {
        achievementId: achievement.achievementId,
        parameters: cloneAchievementParameters(achievement.parameters),
        assigned: 0,
        completed: 0,
        expired: 0,
      };
      count.assigned += 1;
      count.expired += 1;
      counts.set(key, count);
    }
  }
  return Array.from(counts.values());
}

function cloneAchievementParameters(
  parameters: AchievementAssignment["parameters"] | undefined,
): AchievementAssignment["parameters"] | undefined {
  return parameters
    ? {
        ...parameters,
        trait: parameters.trait ? normalizeCogTrait(parameters.trait) : undefined,
      }
    : undefined;
}

function expandAchievementParameters<T>(
  candidates: AchievementParameters[],
  values: readonly T[],
  assign: (parameters: AchievementParameters, value: T) => AchievementParameters,
): AchievementParameters[] {
  return candidates.flatMap((parameters) => values.map((value) => assign(parameters, value)));
}

function cloneAttributes(attributes: Record<string, number>): Record<string, number> {
  return { ...attributes };
}

function cloneSpriteUrls(spriteUrls: SpriteColorUrls | undefined): SpriteColorUrls | undefined {
  const red = spriteUrls?.red?.trim();
  const blue = spriteUrls?.blue?.trim();
  if (!red && !blue) {
    return undefined;
  }

  return {
    ...(red ? { red } : {}),
    ...(blue ? { blue } : {}),
  };
}

function truncateCogName(name: string, reservedLength = 0): string {
  return name.slice(0, Math.max(1, 40 - reservedLength)).trimEnd() || "Cog";
}

function normalizeCogName(name: string): string {
  return name.trim().toLocaleLowerCase();
}

function defaultSpriteUrl(spriteKey: string): string | undefined {
  if (!["cog-default", "cog-ada", "cog-babbage", "cog-mira"].includes(spriteKey)) {
    return undefined;
  }

  return `/assets/cogshambo/sprite-sheets/${spriteKey}/frames/${spriteKey}-01.png`;
}

function sanitizeCogTicksAlive(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0;
}

function scoreLifetimeTicks(cog: Cog): number {
  return Math.max(1, sanitizeCogTicksAlive(cog.ticksAlive));
}

function cogStatus(cog: Cog): "active" | "home" {
  return (cog as Cog & { status?: unknown }).status === "home" ? "home" : "active";
}

function cloneCog(cog: Cog): Cog {
  const { doubt: _legacyDoubt, speech: _legacySpeech, ...cleanCog } = cog as Cog & { doubt?: unknown; speech?: unknown };
  return {
    ...cleanCog,
    status: cogStatus(cog) === "home" ? "home" : undefined,
    position: clonePosition(cog.position),
    location: cog.location ? cloneVenueLocation(cog.location) : undefined,
    spriteUrls: cloneSpriteUrls(cog.spriteUrls),
    attributes: cloneAttributes(cog.attributes),
    defensiveTrait: normalizeCogTrait(cog.defensiveTrait),
    activeTrait: normalizeCogTrait(cog.activeTrait),
    achievements: cloneAchievementAssignments(cog.achievements),
    completedAchievements: cloneCompletedAchievements(cog.completedAchievements),
    failedAchievements: cloneFailedAchievements(cog.failedAchievements),
    goalScores: cloneGoalScoreTracks(cog.goalScores),
    stats: { ...cog.stats },
    ticksAlive: sanitizeCogTicksAlive((cog as Cog & { ticksAlive?: number }).ticksAlive),
    certainty: Math.max(0, cog.certainty),
    debate: cog.debate ? { ...cog.debate } : undefined,
    moving: cog.moving
      ? {
          from: cloneVenueLocation(cog.moving.from),
          to: cloneVenueLocation(cog.moving.to),
          fromPosition: clonePosition(cog.moving.fromPosition),
          toPosition: clonePosition(cog.moving.toPosition),
          path: venueMovementPath(cog.moving),
          startedTick: cog.moving.startedTick,
          arriveTick: cog.moving.arriveTick,
        }
      : undefined,
    roomHistory: cloneCogRoomHistory(cog.roomHistory),
    conversationLog: cog.conversationLog.map((message) => ({ ...message })),
  };
}

function normalizeCogTrait(trait: Trait | string): Trait {
  return normalizeTraitId(trait) as Trait;
}

function cogRoomHistoryEntry(location: VenueLocation, enteredTick: number): CogRoomHistoryEntry {
  return {
    roomId: location.roomId,
    spotId: location.spotId,
    enteredTick,
  };
}

function cloneCogRoomHistory(history: Cog["roomHistory"]): CogRoomHistoryEntry[] {
  return (history ?? [])
    .filter(isValidCogRoomHistoryEntry)
    .map((entry) => ({
      roomId: entry.roomId,
      spotId: entry.spotId,
      enteredTick: entry.enteredTick,
      leftTick: entry.leftTick,
    }));
}

function cloneDimensions(dimensions: WorldDimensions): WorldDimensions {
  return { ...dimensions };
}

function cloneVenue(venue: VenueLayout): VenueLayout {
  return {
    rooms: venue.rooms.map(cloneVenueRoom),
    spots: venue.spots.map(cloneVenueSpot),
    spotLinks: [],
    roomPaths: (venue.roomPaths ?? []).map(cloneVenueRoomPath),
  };
}

function cloneVenueRoom(room: VenueRoom): VenueRoom {
  return {
    ...room,
    position: room.position ? clonePosition(room.position) : undefined,
    rect: room.rect ? { ...room.rect } : undefined,
    spotIds: [...room.spotIds],
    neighborIds: [...room.neighborIds],
  };
}

function cloneVenueSpot(spot: VenueSpot): VenueSpot {
  return {
    ...spot,
    position: clonePosition(spot.position),
  };
}

function cloneVenueRoomPath(path: VenueLayout["roomPaths"][number]): VenueLayout["roomPaths"][number] {
  return {
    ...path,
    points: path.points.map(clonePosition),
  };
}

function cloneVenueLocation(location: VenueLocation): VenueLocation {
  return { ...location };
}

function cloneEvent(event: WorldEvent): WorldEvent {
  return {
    ...event,
    position: event.position ? clonePosition(event.position) : undefined,
    debate: event.debate
      ? {
          actions: event.debate.actions.map((action) => ({ ...action })) as DebateEventDetail["actions"],
          choicesRevealedAtTick: event.debate.choicesRevealedAtTick,
          resultRevealedAtTick: event.debate.resultRevealedAtTick,
          expiresAtTick: event.debate.expiresAtTick,
          outcome: event.debate.outcome,
          round: event.debate.round,
          winnerCogId: event.debate.winnerCogId,
          winnerColor: event.debate.winnerColor,
          witnessCogIds: event.debate.witnessCogIds ? [...event.debate.witnessCogIds] : undefined,
        }
      : undefined,
  };
}

function isLegacySpeechEvent(event: WorldEvent): boolean {
  return (event.type as string) === "speech";
}

function cloneDebateLogEntry(entry: DebateLogEntry): DebateLogEntry {
  return {
    ...entry,
    actions: entry.actions.map((action) => ({ ...action })) as DebateLogEntry["actions"],
    changes: entry.changes.map((change) => ({ ...change })),
    conversions: entry.conversions.map((conversion) => ({ ...conversion })),
  };
}

function cloneObject(object: WorldObject): WorldObject {
  return {
    ...object,
    position: clonePosition(object.position),
    attributes: cloneAttributes(object.attributes),
  };
}

const WORLD_OBJECT_TYPE_SET = new Set<string>(WORLD_OBJECT_TYPES);

function isKnownWorldObject(object: WorldObject): boolean {
  return WORLD_OBJECT_TYPE_SET.has(object.type);
}

function clonePosition(position: Position): Position {
  return { ...position };
}

function venueMoveDurationTicks(path: Position[], dimensions: WorldDimensions): number {
  return venueMoveDurationTicksForDistance(pathLength(path), dimensions);
}

function venueMovementPath(moving: NonNullable<Cog["moving"]>): Position[] {
  const path = moving.path?.length > 0 ? moving.path : [moving.fromPosition, moving.toPosition];
  return path.map(clonePosition);
}

function venueMovementDistanceAtTick(moving: NonNullable<Cog["moving"]>, tick: number): number {
  const path = venueMovementPath(moving);
  const durationTicks = Math.max(1, moving.arriveTick - moving.startedTick);
  const elapsedTicks = Math.min(durationTicks, Math.max(0, tick - moving.startedTick));
  return (pathLength(path) / durationTicks) * elapsedTicks;
}

function appendPathPoint(path: Position[], point: Position): void {
  if (path.length === 0 || !samePosition(path[path.length - 1], point)) {
    path.push(clonePosition(point));
  }
}

function pathLength(path: Position[]): number {
  let length = 0;
  for (let index = 1; index < path.length; index += 1) {
    length += Math.sqrt(squaredDistance(path[index - 1], path[index]));
  }
  return length;
}

function positionAlongPath(path: Position[], distance: number): Position {
  const first = path[0];
  if (!first) {
    return { x: 0, y: 0 };
  }

  let remaining = Math.max(0, distance);
  for (let index = 1; index < path.length; index += 1) {
    const start = path[index - 1];
    const end = path[index];
    const segmentLength = Math.sqrt(squaredDistance(start, end));
    if (segmentLength <= 0) {
      continue;
    }
    if (remaining <= segmentLength) {
      const amount = remaining / segmentLength;
      return {
        x: start.x + (end.x - start.x) * amount,
        y: start.y + (end.y - start.y) * amount,
      };
    }
    remaining -= segmentLength;
  }

  return clonePosition(path[path.length - 1]);
}

function titleCase(value: string): string {
  return `${value.slice(0, 1).toUpperCase()}${value.slice(1)}`;
}
