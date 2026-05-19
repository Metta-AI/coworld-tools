import { z } from "zod";
import { ACHIEVEMENT_IDS, DEFAULT_GAME_CONFIG, RULE_PARAMETERS, TRAIT_RULES } from "./rules.js";
import { SELECTABLE_TRAITS, TEAM_COLORS, TRAITS, VENUE_ROOM_KINDS, WORLD_OBJECT_TYPES } from "./types.js";
import type { Color, ControllerId, SpriteColorUrls, WorldSnapshot } from "./types.js";

export const controllerIdSchema = z.enum(["stub", "wander", "llm"]);
export const directionSchema = z.enum(["north", "south", "east", "west"]);
export const simulationModeSchema = z.enum(["playing", "paused"]);
export const controlCommandSchema = z.enum(["play", "pause", "step", "toggleDisco"]);
export const colorSchema = z.enum(TEAM_COLORS);
export const cogActivitySchema = z.enum(["idle", "moving", "debating"]);
export const cogStatusSchema = z.enum(["active", "home"]);
export const traitSchema = z.enum(TRAITS);
export const selectableTraitSchema = z.enum(SELECTABLE_TRAITS);
export const defensiveTraitSchema = traitSchema;
export const activeTraitSchema = traitSchema;
const PERSONAL_GOAL_VALUES = ["majority", "underdog"] as const;
const LEGACY_PERSONAL_GOALS: Record<string, (typeof PERSONAL_GOAL_VALUES)[number]> = {
  converter: "majority",
  follower: "majority",
  leader: "majority",
  majority: "majority",
  minority: "underdog",
  underdog: "underdog",
  royalist: "majority",
  survivor: "majority",
};
export const personalGoalSchema = z.preprocess(
  (value) => (typeof value === "string" ? LEGACY_PERSONAL_GOALS[value] ?? value : value),
  z.enum(PERSONAL_GOAL_VALUES),
);
export const achievementIdSchema = z.enum(ACHIEVEMENT_IDS);
export const debateTacticSchema = z.enum(["reason", "spin", "passion"]);
export const debateChoiceSchema = debateTacticSchema;
export const cogConversationRoleSchema = z.enum(["user", "assistant"]);
export const terrainSchema = z.enum(["floor", "wall", "sand"]);

export const positionSchema = z
  .object({
    x: z.number().finite(),
    y: z.number().finite(),
  })
  .strict();

export const venueRectSchema = positionSchema
  .extend({
    width: z.number().finite().positive(),
    height: z.number().finite().positive(),
  })
  .strict();

export const venueLocationSchema = z
  .object({
    roomId: z.string().min(1),
    spotId: z.string().min(1),
  })
  .strict();

export const venueRoomSchema = z
  .object({
    id: z.string().min(1),
    label: z.string().min(1),
    kind: z.enum(VENUE_ROOM_KINDS),
    position: positionSchema.optional(),
    rect: venueRectSchema.optional(),
    spotIds: z.array(z.string().min(1)),
    neighborIds: z.array(z.string().min(1)),
  })
  .strict();

export const venueSpotSchema = z
  .object({
    id: z.string().min(1),
    roomId: z.string().min(1),
    label: z.string().min(1),
    position: positionSchema,
    role: z.enum(["speaker", "audience"]).optional(),
  })
  .strict();

export const venueSpotLinkSchema = z
  .object({
    id: z.string().min(1),
    fromSpotId: z.string().min(1),
    toSpotId: z.string().min(1),
  })
  .strict();

export const venueRoomPathSchema = z
  .object({
    id: z.string().min(1),
    fromRoomId: z.string().min(1),
    toRoomId: z.string().min(1),
    points: z.array(positionSchema),
  })
  .strict();

export const venueLayoutSchema = z
  .object({
    rooms: z.array(venueRoomSchema),
    spots: z.array(venueSpotSchema),
    spotLinks: z.array(venueSpotLinkSchema).optional().default([]),
    roomPaths: z.array(venueRoomPathSchema),
  })
  .strict();

const worldDimensionsSchema = z
  .object({
    width: z.number().int().positive(),
    height: z.number().int().positive(),
  })
  .strict();

export const venueEditorStateSchema = z
  .object({
    imageUrl: z.string().min(1),
    dimensions: worldDimensionsSchema,
    rooms: z.array(venueRoomSchema),
    spots: z.array(venueSpotSchema),
    links: z.array(venueSpotLinkSchema).optional().default([]),
    paths: z.array(venueRoomPathSchema),
    updatedAt: z.string().optional(),
  })
  .strict();

export const updateVenueEditorRequestSchema = venueEditorStateSchema.omit({ updatedAt: true });

export type VenueEditorStateResponse = {
  state: z.infer<typeof venueEditorStateSchema>;
};

export const attributesSchema = z.record(z.number().finite());
export const spriteUrlSchema = z.string().min(1).max(20000);
export const spriteColorUrlsSchema = z
  .object({
    red: spriteUrlSchema.optional(),
    blue: spriteUrlSchema.optional(),
  })
  .strict();

export const createCogRequestSchema = z
  .object({
    name: z.string().min(1).max(40),
    behaviorPrompt: z.string().max(1000).default(""),
    spriteSheetKey: z.string().min(1).max(80).default("cog-default"),
    spriteUrl: spriteUrlSchema.optional(),
    spriteUrls: spriteColorUrlsSchema.optional(),
    controllerId: controllerIdSchema.default("llm"),
    color: colorSchema.default("red"),
    defensiveTrait: selectableTraitSchema.default("stubborn"),
    activeTrait: selectableTraitSchema.default("forceful"),
    personalGoal: personalGoalSchema.default("majority"),
    attributes: attributesSchema.default({ energy: 5, focus: 5 }),
    position: positionSchema
      .extend({
        x: z.number().int().nonnegative().finite(),
        y: z.number().int().nonnegative().finite(),
      })
      .optional(),
    location: venueLocationSchema.optional(),
  })
  .strict();

export type CreateCogRequest = z.infer<typeof createCogRequestSchema>;

export type CreateCogResponse = {
  cogId: string;
  snapshot: WorldSnapshot;
};

export type ShuffleTeamsResponse = {
  snapshot: WorldSnapshot;
};

export type AbandonCogResponse = {
  cogId: string;
  snapshot: WorldSnapshot;
};

export type KickCogResponse = {
  cogId: string;
  snapshot: WorldSnapshot;
};

export type PokeCogResponse = {
  cogId: string;
  snapshot: WorldSnapshot;
};

export const updateCogProfileRequestSchema = z
  .object({
    name: z.string().trim().min(1).max(40).optional(),
    behaviorPrompt: z.string().max(1000),
    attributes: attributesSchema,
    defensiveTrait: defensiveTraitSchema.optional(),
    activeTrait: activeTraitSchema.optional(),
    personalGoal: personalGoalSchema.optional(),
  })
  .strict();

export type UpdateCogProfileRequest = z.infer<typeof updateCogProfileRequestSchema>;

export type UpdateCogProfileResponse = {
  cogId: string;
  snapshot: WorldSnapshot;
};

export const generateCogSpritesRequestSchema = z
  .object({
    name: z.string().max(40).default(""),
    description: z.string().max(1000).default(""),
    defensiveTrait: selectableTraitSchema.default("stubborn"),
    activeTrait: selectableTraitSchema.default("passionate"),
    personalGoal: personalGoalSchema.default("majority"),
    spriteRoll: z.number().int().nonnegative().finite().default(0),
    count: z.number().int().min(1).max(5).default(5),
  })
  .strict();

export type GenerateCogSpritesRequest = z.infer<typeof generateCogSpritesRequestSchema>;

export type GeneratedCogSprite = {
  key: string;
  label: string;
  url: string;
  spriteUrls?: SpriteColorUrls;
};

export type GenerateCogSpritesResponse = {
  sprites: GeneratedCogSprite[];
  source: "nano-banana";
};

export const controlRequestSchema = z
  .object({
    command: controlCommandSchema,
  })
  .strict();

export type ControlRequest = z.infer<typeof controlRequestSchema>;

const gameConfigShape = Object.fromEntries(
  RULE_PARAMETERS.map((parameter) => [
    parameter.key,
    z.number().finite().min(parameter.min).max(parameter.max).default(DEFAULT_GAME_CONFIG[parameter.key]),
  ]),
) as {
  [key in keyof Omit<typeof DEFAULT_GAME_CONFIG, "traitConfig">]: z.ZodDefault<z.ZodNumber>;
};

function createTraitConfigSchemaShape(mode: "default" | "update"): Record<string, z.ZodTypeAny> {
  return Object.fromEntries(
    TRAIT_RULES.filter((trait) => trait.parameters?.length).map((trait) => {
      const parameterShape = Object.fromEntries(
        (trait.parameters ?? []).map((parameter) => [
          parameter.key,
          mode === "default"
            ? z
                .number()
                .finite()
                .min(parameter.min)
                .max(parameter.max)
                .default((DEFAULT_GAME_CONFIG.traitConfig[trait.id] as Record<string, number>)[parameter.key])
            : z.number().finite().min(parameter.min).max(parameter.max).optional(),
        ]),
      );
      const schema = z.object(parameterShape).strict();
      return [
        trait.id,
        mode === "default" ? schema.default(DEFAULT_GAME_CONFIG.traitConfig[trait.id]) : schema.partial().optional(),
      ];
    }),
  );
}

const traitConfigSchema = z
  .object(createTraitConfigSchemaShape("default"))
  .strict();

export const gameConfigSchema = z
  .object({
    ...gameConfigShape,
    traitConfig: traitConfigSchema.default(DEFAULT_GAME_CONFIG.traitConfig),
  })
  .strict();

const updateGameConfigShape = Object.fromEntries(
  RULE_PARAMETERS.map((parameter) => [
    parameter.key,
    z.number().finite().min(parameter.min).max(parameter.max).optional(),
  ]),
) as {
  [key in keyof Omit<typeof DEFAULT_GAME_CONFIG, "traitConfig">]: z.ZodOptional<z.ZodNumber>;
};

const updateTraitConfigSchema = z
  .object(createTraitConfigSchemaShape("update"))
  .strict();

export const updateGameConfigRequestSchema = z
  .object({
    ...updateGameConfigShape,
    traitConfig: updateTraitConfigSchema.optional(),
  })
  .strict();
export type UpdateGameConfigRequest = z.infer<typeof updateGameConfigRequestSchema>;

export const createSettingsPresetRequestSchema = z
  .object({
    name: z.string().trim().min(1).max(80),
  })
  .strict();
export type CreateSettingsPresetRequest = z.infer<typeof createSettingsPresetRequestSchema>;

export const selectSettingsPresetRequestSchema = z
  .object({
    settingsDb: z.string().trim().min(1).max(80),
  })
  .strict();
export type SelectSettingsPresetRequest = z.infer<typeof selectSettingsPresetRequestSchema>;

export const worldEventSchema = z
  .object({
    id: z.string().min(1),
    tick: z.number().int().nonnegative().finite(),
    type: z.enum([
      "spawn",
      "move",
      "moveBlocked",
      "controllerError",
      "inspect",
      "poke",
      "abandon",
      "kick",
      "score",
      "debateStart",
      "debateExchange",
      "gameFlow",
      "colorChange",
    ]),
    actorId: z.string().min(1).optional(),
    targetId: z.string().min(1).optional(),
    message: z.string(),
    position: positionSchema.optional(),
    debate: z
      .object({
        actions: z.tuple([
          z
            .object({
              cogId: z.string().min(1),
              action: debateChoiceSchema,
            })
            .strict(),
          z
            .object({
              cogId: z.string().min(1),
              action: debateChoiceSchema,
            })
            .strict(),
        ]),
        choicesRevealedAtTick: z.number().int().nonnegative().finite().optional(),
        resultRevealedAtTick: z.number().int().nonnegative().finite().optional(),
        expiresAtTick: z.number().int().nonnegative().finite(),
        outcome: z.enum(["win", "lose", "draw"]),
        round: z.number().int().positive().finite(),
        roomKind: z.enum(VENUE_ROOM_KINDS).optional(),
        winnerCogId: z.string().min(1).optional(),
        winnerColor: colorSchema.optional(),
        witnessCogIds: z.array(z.string().min(1)).optional(),
      })
      .strict()
      .optional(),
  })
  .strict();

export const debateLogEntrySchema = z
  .object({
    id: z.string().min(1),
    tick: z.number().int().nonnegative().finite(),
    round: z.number().int().positive().finite(),
    outcome: z.enum(["win", "lose", "draw"]),
    winnerCogId: z.string().min(1).optional(),
    winnerColor: colorSchema.optional(),
    actions: z.tuple([
      z
        .object({
          cogId: z.string().min(1),
          cogName: z.string().min(1),
          color: colorSchema,
          tactic: debateTacticSchema,
        })
        .strict(),
      z
        .object({
          cogId: z.string().min(1),
          cogName: z.string().min(1),
          color: colorSchema,
          tactic: debateTacticSchema,
        })
        .strict(),
    ]),
    changes: z.array(
      z
        .object({
          cogId: z.string().min(1),
          cogName: z.string().min(1),
          role: z.enum(["participant", "witness"]),
          colorBefore: colorSchema,
          colorAfter: colorSchema,
          certaintyBefore: z.number().finite().nonnegative(),
          certaintyAfter: z.number().finite().nonnegative(),
          certaintyDelta: z.number().finite(),
        })
        .strict(),
    ),
    conversions: z.array(
      z
        .object({
          cogId: z.string().min(1),
          cogName: z.string().min(1),
          fromColor: colorSchema,
          toColor: colorSchema,
          certaintyBefore: z.number().finite().nonnegative(),
          certaintyAfter: z.number().finite().nonnegative(),
        })
        .strict(),
    ),
  })
  .strict();

export const cogConversationMessageSchema = z
  .object({
    id: z.string().min(1),
    tick: z.number().int().nonnegative().finite(),
    role: cogConversationRoleSchema,
    content: z.string(),
  })
  .strict();

export const cogRoomHistoryEntrySchema = z
  .object({
    roomId: z.string().min(1),
    spotId: z.string().min(1).optional(),
    enteredTick: z.number().int().nonnegative().finite(),
    leftTick: z.number().int().nonnegative().finite().optional(),
  })
  .strict();

export const movementStateSchema = z
  .object({
    from: venueLocationSchema,
    to: venueLocationSchema,
    fromPosition: positionSchema,
    toPosition: positionSchema,
    path: z.array(positionSchema).default([]),
    startedTick: z.number().int().nonnegative().finite(),
    arriveTick: z.number().int().nonnegative().finite(),
  })
  .strict();

export const cogStatsSchema = z
  .object({
    argumentsWon: z.number().int().nonnegative().finite(),
    argumentsLost: z.number().int().nonnegative().finite(),
    teamFlips: z.number().int().nonnegative().finite(),
  })
  .strict();

export const goalScoreSampleSchema = z
  .object({
    tick: z.number().int().nonnegative().finite(),
    points: z.number().finite(),
  })
  .strict();

export const goalScoreTrackSchema = z
  .object({
    goal: personalGoalSchema,
    points: z.number().finite(),
    history: z.array(goalScoreSampleSchema),
  })
  .strict();

export const achievementAssignmentSchema = z
  .object({
    assignmentId: z.string().min(1),
    achievementId: achievementIdSchema,
    parameters: z
      .object({
        trait: z.union([activeTraitSchema, defensiveTraitSchema]).optional(),
        team: colorSchema.optional(),
        roomKind: z.enum(VENUE_ROOM_KINDS).optional(),
        tactic: debateTacticSchema.optional(),
        rounds: z.number().int().positive().finite().optional(),
        cogId: z.string().min(1).optional(),
        cogName: z.string().min(1).optional(),
      })
      .strict()
      .optional(),
    assignedTick: z.number().int().nonnegative().finite(),
    timeoutTick: z.number().int().nonnegative().finite(),
  })
  .strict();

export const completedAchievementSchema = achievementAssignmentSchema
  .extend({
    completedTick: z.number().int().nonnegative().finite(),
    points: z.number().finite(),
  })
  .strict();

export const failedAchievementSchema = achievementAssignmentSchema
  .extend({
    failedTick: z.number().int().nonnegative().finite(),
  })
  .strict();

export const achievementCountSchema = z
  .object({
    achievementId: achievementIdSchema,
    parameters: z
      .object({
        trait: z.union([activeTraitSchema, defensiveTraitSchema]).optional(),
        team: colorSchema.optional(),
        roomKind: z.enum(VENUE_ROOM_KINDS).optional(),
        tactic: debateTacticSchema.optional(),
        rounds: z.number().int().positive().finite().optional(),
        cogId: z.string().min(1).optional(),
        cogName: z.string().min(1).optional(),
      })
      .strict()
      .optional(),
    assigned: z.number().int().nonnegative().finite(),
    completed: z.number().int().nonnegative().finite(),
    current: z.number().int().nonnegative().finite(),
    expired: z.number().int().nonnegative().finite(),
  })
  .strict();

export const cogSchema = z
  .object({
    id: z.string().min(1),
    name: z.string().min(1),
    behaviorPrompt: z.string(),
    status: cogStatusSchema.optional(),
    position: positionSchema,
    location: venueLocationSchema.optional(),
    spriteSheetKey: z.string().min(1),
    spriteUrl: spriteUrlSchema.optional(),
    spriteUrls: spriteColorUrlsSchema.optional(),
    attributes: attributesSchema,
    color: colorSchema,
    defensiveTrait: defensiveTraitSchema,
    activeTrait: activeTraitSchema,
    personalGoal: personalGoalSchema,
    activity: cogActivitySchema.default("idle"),
    ticksAlive: z.number().int().nonnegative().finite().default(0),
    personalScore: z.number().finite(),
    achievements: z.array(achievementAssignmentSchema).default([]),
    completedAchievements: z.array(completedAchievementSchema).default([]),
    failedAchievements: z.array(failedAchievementSchema).default([]),
    goalScores: z.array(goalScoreTrackSchema),
    stats: cogStatsSchema,
    certainty: z.number().finite().nonnegative(),
    debate: z
      .object({
        opponentId: z.string().min(1),
        startedTick: z.number().int().nonnegative().finite(),
        nextRoundTick: z.number().int().nonnegative().finite(),
        roundsResolved: z.number().int().nonnegative().finite(),
      })
      .strict()
      .optional(),
    moving: movementStateSchema.optional(),
    controllerId: controllerIdSchema,
    intent: z.string().optional(),
    movementCooldown: z.number().int().nonnegative().finite(),
    lastVenueMoveTick: z.number().int().nonnegative().finite().optional(),
    roomHistory: z.array(cogRoomHistoryEntrySchema).optional(),
    conversationLog: z.array(cogConversationMessageSchema),
  })
  .strict();

export const terrainCellSchema = z
  .object({
    position: positionSchema,
    terrain: z.enum(["wall", "sand"]),
  })
  .strict();

export const worldObjectSchema = z
  .object({
    id: z.string().min(1),
    type: z.enum(WORLD_OBJECT_TYPES),
    position: positionSchema,
    spriteKey: z.string().min(1),
    attributes: attributesSchema,
  })
  .strict();

export const worldSnapshotSchema = z
  .object({
    tick: z.number().int().nonnegative().finite(),
    dimensions: z
      .object({
        width: z.number().int().positive().finite(),
        height: z.number().int().positive().finite(),
    })
      .strict(),
    venue: venueLayoutSchema.optional(),
    cogs: z.array(cogSchema),
    objects: z.array(worldObjectSchema),
    terrain: z.array(terrainCellSchema),
    recentEvents: z.array(worldEventSchema),
    achievementCounts: z.array(achievementCountSchema).default([]),
    debateLog: z.array(debateLogEntrySchema).optional(),
  })
  .strict();

export const serverStatusSchema = z
  .object({
    tick: z.number().int().nonnegative().finite(),
    cogCount: z.number().int().nonnegative().finite(),
    clientCount: z.number().int().nonnegative().finite(),
    controllerMode: controllerIdSchema,
    discoMode: z.boolean().default(false),
    llmMoveDecisions: z.number().int().nonnegative().finite().default(0),
    llmTimedOutMoves: z.number().int().nonnegative().finite().default(0),
    llmTimedOutMovePercent: z.number().nonnegative().finite().default(0),
    simulationMode: simulationModeSchema,
    stepRequested: z.boolean(),
  })
  .strict();

export const serverMessageSchema = z.discriminatedUnion("type", [
  z
    .object({
      type: z.literal("snapshot"),
      snapshot: worldSnapshotSchema,
    })
    .strict(),
  z
    .object({
      type: z.literal("event"),
      event: worldEventSchema,
    })
    .strict(),
  z
    .object({
      type: z.literal("serverStatus"),
      status: serverStatusSchema,
    })
    .strict(),
]);

const manualCogActionSchema = z.discriminatedUnion("type", [
  z
    .object({
      type: z.literal("move"),
      roomId: z.string().min(1).optional(),
      direction: directionSchema.optional(),
      intent: z.string().min(1).max(240).optional(),
    })
    .strict(),
  z
    .object({
      type: z.literal("debate"),
      targetId: z.string().min(1).optional(),
      intent: z.string().min(1).max(240).optional(),
    })
    .strict(),
  z
    .object({
      type: z.literal("chooseTactic"),
      tactic: debateTacticSchema,
      intent: z.string().min(1).max(240).optional(),
    })
    .strict(),
  z
    .object({
      type: z.literal("wait"),
      intent: z.string().min(1).max(240).optional(),
    })
    .strict(),
]);

export const clientMessageSchema = z.discriminatedUnion("type", [
  z
    .object({
      type: z.literal("hello"),
      clientName: z.string(),
    })
    .strict(),
  z
    .object({
      type: z.literal("debugCommand"),
      command: z.enum(["followCog", "togglePerception"]),
      cogId: z.string().optional(),
    })
    .strict(),
  z
    .object({
      type: z.literal("manualMove"),
      cogId: z.string().min(1),
      direction: directionSchema,
    })
    .strict(),
  z
    .object({
      type: z.literal("manualAction"),
      cogId: z.string().min(1),
      action: manualCogActionSchema,
    })
    .strict(),
]);

export type ServerMessage = z.infer<typeof serverMessageSchema>;

export type ClientMessage = z.infer<typeof clientMessageSchema>;

export function isServerMessage(value: unknown): value is ServerMessage {
  return serverMessageSchema.safeParse(value).success;
}

export function isClientMessage(value: unknown): value is ClientMessage {
  return clientMessageSchema.safeParse(value).success;
}

export function parseControllerId(value: string | undefined): ControllerId {
  return controllerIdSchema.catch("llm").parse(value);
}

export function parseColor(value: string | undefined): Color {
  return colorSchema.catch("red").parse(value);
}
