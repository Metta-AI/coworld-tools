import type { ACHIEVEMENT_IDS } from "./achievements/ids.js";
import type { GameConfig } from "./rules.js";
import { SELECTABLE_TRAITS, TRAITS } from "./traits/ids.js";

export { SELECTABLE_TRAITS, TRAITS } from "./traits/ids.js";

export type Direction = "north" | "south" | "east" | "west";

export type ControllerId = "stub" | "wander" | "llm";

export type EntityKind = "cog" | "object";

export type SimulationMode = "playing" | "paused";

export const TEAM_COLORS = ["red", "blue"] as const;
export const VENUE_ROOM_KINDS = ["stage", "table", "bar", "lounge", "walkway"] as const;
export const WORLD_OBJECT_TYPES = ["picknick", "bench", "stairs", "tree", "block"] as const;

export type Color = (typeof TEAM_COLORS)[number];
export type VenueRoomKind = (typeof VENUE_ROOM_KINDS)[number];
export type WorldObjectType = (typeof WORLD_OBJECT_TYPES)[number];

export function oppositeTeamColor(color: Color): Color {
  return color === TEAM_COLORS[0] ? TEAM_COLORS[1] : TEAM_COLORS[0];
}

export type DebateTactic = "reason" | "spin" | "passion";

export type DebateChoice = DebateTactic;

export type Trait = (typeof TRAITS)[number];

export type SelectableTrait = (typeof SELECTABLE_TRAITS)[number];

export type PersonalGoal = "majority" | "underdog";

export type CogActivity = "idle" | "moving" | "debating";

export type AchievementId = (typeof ACHIEVEMENT_IDS)[number];

export type Terrain = "floor" | "wall" | "sand";

export type Position = {
  x: number;
  y: number;
};

export type VenueRect = Position & {
  width: number;
  height: number;
};

export type VenueLocation = {
  roomId: string;
  spotId: string;
};

export type VenueSpotRole = "speaker" | "audience";

export type VenueRoom = {
  id: string;
  label: string;
  kind: VenueRoomKind;
  position?: Position;
  rect?: VenueRect;
  spotIds: string[];
  neighborIds: string[];
};

export type VenueSpot = {
  id: string;
  roomId: string;
  label: string;
  position: Position;
  role?: VenueSpotRole;
};

export type VenueSpotLink = {
  id: string;
  fromSpotId: string;
  toSpotId: string;
};

export type VenueRoomPath = {
  id: string;
  fromRoomId: string;
  toRoomId: string;
  points: Position[];
};

export type VenueLayout = {
  rooms: VenueRoom[];
  spots: VenueSpot[];
  spotLinks: VenueSpotLink[];
  roomPaths: VenueRoomPath[];
};

export type VenueEditorState = {
  imageUrl: string;
  dimensions: WorldDimensions;
  rooms: VenueRoom[];
  spots: VenueSpot[];
  links: VenueSpotLink[];
  paths: VenueRoomPath[];
  updatedAt?: string;
};

export type Attributes = Record<string, number>;

export type SpriteColorUrls = Partial<Record<Color, string>>;

export type DebateState = {
  opponentId: string;
  startedTick: number;
  nextRoundTick: number;
  roundsResolved: number;
};

export type MovementState = {
  from: VenueLocation;
  to: VenueLocation;
  fromPosition: Position;
  toPosition: Position;
  path: Position[];
  startedTick: number;
  arriveTick: number;
};

export type CogConversationRole = "user" | "assistant";

export type CogConversationMessage = {
  id: string;
  tick: number;
  role: CogConversationRole;
  content: string;
};

export type CogRoomHistoryEntry = {
  roomId: string;
  spotId?: string;
  enteredTick: number;
  leftTick?: number;
};

export type CogStats = {
  argumentsWon: number;
  argumentsLost: number;
  teamFlips: number;
};

export type GoalScoreSample = {
  tick: number;
  points: number;
};

export type GoalScoreTrack = {
  goal: PersonalGoal;
  points: number;
  history: GoalScoreSample[];
};

export type AchievementParameters = {
  trait?: Trait;
  team?: Color;
  roomKind?: VenueRoomKind;
  tactic?: DebateTactic;
  rounds?: number;
  cogId?: string;
  cogName?: string;
};

export type AchievementAssignment = {
  assignmentId: string;
  achievementId: AchievementId;
  parameters?: AchievementParameters;
  assignedTick: number;
  timeoutTick: number;
};

export type CompletedAchievement = AchievementAssignment & {
  completedTick: number;
  points: number;
};

export type FailedAchievement = AchievementAssignment & {
  failedTick: number;
};

export type AchievementCount = {
  achievementId: AchievementId;
  parameters?: AchievementParameters;
  assigned: number;
  completed: number;
  current: number;
  expired: number;
};

export type SpriteSheetRef = {
  key: string;
  url: string;
  frameWidth: number;
  frameHeight: number;
  animations: Record<string, number[]>;
};

export type Cog = {
  id: string;
  name: string;
  behaviorPrompt: string;
  status?: CogStatus;
  position: Position;
  location?: VenueLocation;
  spriteSheetKey: string;
  spriteUrl?: string;
  spriteUrls?: SpriteColorUrls;
  attributes: Attributes;
  color: Color;
  defensiveTrait: Trait;
  activeTrait: Trait;
  personalGoal: PersonalGoal;
  activity: CogActivity;
  ticksAlive: number;
  personalScore: number;
  achievements: AchievementAssignment[];
  completedAchievements: CompletedAchievement[];
  failedAchievements: FailedAchievement[];
  goalScores: GoalScoreTrack[];
  stats: CogStats;
  certainty: number;
  debate?: DebateState;
  moving?: MovementState;
  controllerId: ControllerId;
  intent?: string;
  movementCooldown: number;
  lastVenueMoveTick?: number;
  roomHistory?: CogRoomHistoryEntry[];
  conversationLog: CogConversationMessage[];
};

export type CogStatus = "active" | "home";

export type WorldObject = {
  id: string;
  type: WorldObjectType;
  position: Position;
  spriteKey: string;
  attributes: Attributes;
};

export type WorldDimensions = {
  width: number;
  height: number;
};

export type TerrainCell = {
  position: Position;
  terrain: Exclude<Terrain, "floor">;
};

export type VisibleEntity =
  | {
      kind: "cog";
      id: string;
      name: string;
      position: Position;
      location?: VenueLocation;
      color: Color;
      certainty?: number;
      activity: CogActivity;
      debate?: DebateState;
      moving?: MovementState;
      spriteSheetKey: string;
      spriteUrl?: string;
      spriteUrls?: SpriteColorUrls;
    }
  | {
      kind: "object";
      id: string;
      objectType: WorldObject["type"];
      position: Position;
      spriteKey: string;
    };

export type DebateEventAction = {
  cogId: string;
  action: DebateChoice;
};

export type DebateEventDetail = {
  actions: [DebateEventAction, DebateEventAction];
  choicesRevealedAtTick: number;
  resultRevealedAtTick: number;
  expiresAtTick: number;
  outcome: "win" | "lose" | "draw";
  round: number;
  roomKind?: VenueRoomKind;
  winnerCogId?: string;
  winnerColor?: Color;
  witnessCogIds?: string[];
};

export type DebateLogAction = {
  cogId: string;
  cogName: string;
  color: Color;
  tactic: DebateTactic;
};

export type DebateLogCogRole = "participant" | "witness";

export type DebateLogCogChange = {
  cogId: string;
  cogName: string;
  role: DebateLogCogRole;
  colorBefore: Color;
  colorAfter: Color;
  certaintyBefore: number;
  certaintyAfter: number;
  certaintyDelta: number;
};

export type DebateLogConversion = {
  cogId: string;
  cogName: string;
  fromColor: Color;
  toColor: Color;
  certaintyBefore: number;
  certaintyAfter: number;
};

export type DebateLogEntry = {
  id: string;
  tick: number;
  round: number;
  outcome: DebateEventDetail["outcome"];
  winnerCogId?: string;
  winnerColor?: Color;
  actions: [DebateLogAction, DebateLogAction];
  changes: DebateLogCogChange[];
  conversions: DebateLogConversion[];
};

export type WorldEvent = {
  id: string;
  tick: number;
  type:
    | "spawn"
    | "move"
    | "moveBlocked"
    | "controllerError"
    | "inspect"
    | "poke"
    | "abandon"
    | "kick"
    | "score"
    | "debateStart"
    | "debateExchange"
    | "gameFlow"
    | "colorChange";
  actorId?: string;
  targetId?: string;
  message: string;
  position?: Position;
  debate?: DebateEventDetail;
};

export type CogObservation = {
  cog: Cog;
  dimensions: WorldDimensions;
  venue?: VenueLayout;
  visibleEntities: VisibleEntity[];
  visibleTerrain: TerrainCell[];
  visibleCells: Position[];
  recentEvents: WorldEvent[];
};

export type CogActionMetadata = {
  choiceNumber?: number;
  intent?: string;
  thoughts?: string;
  timedOut?: boolean;
};

export type CogAction =
  | ({ type: "wait" } & CogActionMetadata)
  | ({ type: "move"; direction?: Direction; roomId?: string } & CogActionMetadata)
  | ({ type: "debate"; targetId?: string } & CogActionMetadata)
  | ({ type: "chooseTactic"; tactic: DebateTactic } & CogActionMetadata);

export type CogDecisionInput = {
  tick: number;
  observation: CogObservation;
  allowedActions: CogAction["type"][];
  allowedRoomIds?: string[];
  allowedDirections?: Direction[];
  gameConfig?: GameConfig;
};

export type WorldSnapshot = {
  tick: number;
  dimensions: WorldDimensions;
  venue?: VenueLayout;
  cogs: Cog[];
  objects: WorldObject[];
  terrain: TerrainCell[];
  recentEvents: WorldEvent[];
  achievementCounts: AchievementCount[];
  debateLog?: DebateLogEntry[];
};

export type ServerStatus = {
  tick: number;
  cogCount: number;
  clientCount: number;
  controllerMode: ControllerId;
  discoMode: boolean;
  llmMoveDecisions: number;
  llmTimedOutMoves: number;
  llmTimedOutMovePercent: number;
  simulationMode: SimulationMode;
  stepRequested: boolean;
};
