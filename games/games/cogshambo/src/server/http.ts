import express, { type ErrorRequestHandler, type RequestHandler } from "express";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  controlRequestSchema,
  createSettingsPresetRequestSchema,
  createCogRequestSchema,
  generateCogSpritesRequestSchema,
  selectSettingsPresetRequestSchema,
  updateGameConfigRequestSchema,
  updateCogProfileRequestSchema,
  updateVenueEditorRequestSchema,
} from "../shared/protocol.js";
import { ACHIEVEMENT_RULES, GOAL_RULES, RULE_PARAMETERS, TRAIT_RULES } from "../shared/rules.js";
import type { VenueEditorState, VenueRoom, VenueSpot } from "../shared/types.js";
import { venueRoomPathsFromNeighbors, venueRoomRect } from "../shared/venue.js";
import { createNanoBananaCogSpriteGenerator, type CogSpriteGenerator } from "./art/sprite-generator.js";
import { compactWorldSnapshot } from "./client-snapshot.js";
import type { ControllerRegistry } from "./controllers/cog-controller.js";
import { readDeployVersion, type DeployVersion } from "./deploy-version.js";
import type { SimulationControls } from "./simulation/control.js";
import type { GridWorld } from "./simulation/world.js";
import {
  createJsonVenueEditorStore,
  VENUE_EDITOR_IMAGE_URL,
  type VenueEditorStore,
} from "./venue-editor-store.js";
import { venueLayoutFromEditorState } from "./venue-graph.js";
import { createSqliteSettingsStore, type SettingsState, type SettingsStore } from "./settings-store.js";
import type { WorldStateStore } from "./world-state-store.js";

const MAIN_GAME_AUTH_USERNAME = "daveey";
const MAIN_GAME_AUTH_PASSWORD = "daviddavid";
const MAIN_GAME_AUTH_REALM = "Cogshambo";

export type CreateAppOptions = {
  world: GridWorld;
  controllers: ControllerRegistry;
  controls: SimulationControls;
  spriteGenerator?: CogSpriteGenerator;
  venueEditorStore?: VenueEditorStore;
  settingsStore?: SettingsStore;
  worldStateStore?: WorldStateStore;
  deployVersion?: () => DeployVersion;
};

export function createApp({
  world,
  controllers,
  controls,
  spriteGenerator = createNanoBananaCogSpriteGenerator(),
  venueEditorStore,
  settingsStore,
  worldStateStore,
  deployVersion = readDeployVersion,
}: CreateAppOptions): express.Express {
  const app = express();
  let ownedVenueEditorStore: VenueEditorStore | undefined;
  let ownedSettingsStore: SettingsStore | undefined;
  const getVenueEditorStore = (): VenueEditorStore => {
    return venueEditorStore ?? (ownedVenueEditorStore ??= createJsonVenueEditorStore());
  };
  const getSettingsStore = (): SettingsStore => {
    return settingsStore ?? (ownedSettingsStore ??= createSqliteSettingsStore());
  };
  const loadVenueEditorState = (): VenueEditorState => {
    return getVenueEditorStore().load(() => seedVenueEditorState(world));
  };
  const applyVenueEditorState = (state: Omit<VenueEditorState, "updatedAt">): void => {
    world.updateVenueLayout(venueLayoutFromEditorState(state));
  };
  const persistWorld = (): void => {
    worldStateStore?.save(world);
  };
  applyVenueEditorState(loadVenueEditorState());
  world.updateGameConfig(getSettingsStore().load().config);
  persistWorld();

  app.use(express.json());
  app.use(jsonParseErrorHandler);

  app.get("/health", (_request, response) => {
    response.json({
      ok: true,
      snapshot: compactWorldSnapshot(world.snapshot()),
    });
  });

  app.get("/version", (_request, response) => {
    response.json(deployVersion());
  });

  app.get("/api/world", (_request, response) => {
    response.json(compactWorldSnapshot(world.snapshot()));
  });

  app.get("/api/config", (_request, response) => {
    const state = getSettingsStore().load();
    world.updateGameConfig(state.config);
    persistWorld();
    response.json(configResponse(state));
  });

  app.get("/api/venue-editor", (_request, response) => {
    response.json({
      state: loadVenueEditorState(),
    });
  });

  app.put("/api/venue-editor", (request, response) => {
    const result = updateVenueEditorRequestSchema.safeParse(request.body);
    if (!result.success) {
      response.status(400).json({
        error: "Invalid venue editor request",
        issues: result.error.issues,
      });
      return;
    }

    const editorState = {
      ...result.data,
      links: [],
    };
    const issues = validateVenueEditorState(editorState);
    if (issues.length > 0) {
      response.status(400).json({
        error: "Invalid venue editor request",
        issues,
      });
      return;
    }

    const savedState = getVenueEditorStore().save(editorState);
    applyVenueEditorState(savedState);
    persistWorld();

    response.json({
      state: savedState,
    });
  });

  app.patch("/api/config", (request, response) => {
    const result = updateGameConfigRequestSchema.safeParse(request.body);
    if (!result.success) {
      response.status(400).json({
        error: "Invalid config request",
        issues: result.error.issues,
      });
      return;
    }

    const state = getSettingsStore().saveCurrentConfig(result.data);
    world.updateGameConfig(state.config);
    persistWorld();
    response.json(configResponse(state));
  });

  app.post("/api/config/presets", (request, response) => {
    const result = createSettingsPresetRequestSchema.safeParse(request.body);
    if (!result.success) {
      response.status(400).json({
        error: "Invalid settings preset request",
        issues: result.error.issues,
      });
      return;
    }

    const state = getSettingsStore().createPreset(result.data.name);
    world.updateGameConfig(state.config);
    persistWorld();
    response.status(201).json(configResponse(state));
  });

  app.patch("/api/config/current", (request, response) => {
    const result = selectSettingsPresetRequestSchema.safeParse(request.body);
    if (!result.success) {
      response.status(400).json({
        error: "Invalid settings preset request",
        issues: result.error.issues,
      });
      return;
    }

    try {
      const state = getSettingsStore().selectPreset(result.data.settingsDb);
      world.updateGameConfig(state.config);
      persistWorld();
      response.json(configResponse(state));
    } catch (error) {
      response.status(404).json({
        error: error instanceof Error ? error.message : "Unknown settings preset",
      });
    }
  });

  app.post("/api/control", (request, response) => {
    const result = controlRequestSchema.safeParse(request.body);
    if (!result.success) {
      response.status(400).json({
        error: "Invalid control request",
        issues: result.error.issues,
      });
      return;
    }

    switch (result.data.command) {
      case "pause":
        controls.pause();
        break;
      case "play":
        controls.play();
        break;
      case "step":
        controls.step();
        break;
      case "toggleDisco":
        controls.toggleDisco();
        break;
    }

    response.json({
      status: controls.statusPatch(),
    });
  });

  app.post("/api/cogs", (request, response) => {
    const result = createCogRequestSchema.safeParse(request.body);
    if (!result.success) {
      response.status(400).json({
        error: "Invalid create cog request",
        issues: result.error.issues,
      });
      return;
    }

    if (!controllers[result.data.controllerId]) {
      response.status(400).json({
        error: "Unknown controller",
      });
      return;
    }

    let cog;
    try {
      cog = world.addCog(result.data);
      persistWorld();
    } catch (error) {
      response.status(400).json({
        error: "Invalid create cog request",
        issues: [
          {
            path: ["position"],
            message: error instanceof Error ? error.message : "Unable to create cog",
          },
        ],
      });
      return;
    }

    response.status(201).json({
      cogId: cog.id,
      snapshot: compactWorldSnapshot(world.snapshot()),
    });
  });

  app.post("/api/cogs/shuffle-teams", (_request, response) => {
    const snapshot = world.shuffleCogTeams();
    persistWorld();
    response.json({
      snapshot: compactWorldSnapshot(snapshot),
    });
  });

  app.post("/api/cogs/:cogId/abandon", (request, response) => {
    try {
      const cog = world.abandonCog(request.params.cogId);
      persistWorld();
      response.json({
        cogId: cog.id,
        snapshot: compactWorldSnapshot(world.snapshot()),
      });
    } catch (error) {
      response.status(404).json({
        error: error instanceof Error ? error.message : "Unable to abandon cog",
      });
    }
  });

  app.post("/api/cogs/:cogId/kick", (request, response) => {
    try {
      const cog = world.kickCogHome(request.params.cogId);
      persistWorld();
      response.json({
        cogId: cog.id,
        snapshot: compactWorldSnapshot(world.snapshot()),
      });
    } catch (error) {
      response.status(404).json({
        error: error instanceof Error ? error.message : "Unable to kick cog",
      });
    }
  });

  app.post("/api/cogs/:cogId/poke", (request, response) => {
    try {
      const cog = world.pokeCog(request.params.cogId);
      persistWorld();
      response.json({
        cogId: cog.id,
        snapshot: compactWorldSnapshot(world.snapshot()),
      });
    } catch (error) {
      response.status(404).json({
        error: error instanceof Error ? error.message : "Unable to poke cog",
      });
    }
  });

  app.post("/api/cog-sprites", async (request, response) => {
    const result = generateCogSpritesRequestSchema.safeParse(request.body);
    if (!result.success) {
      response.status(400).json({
        error: "Invalid cog avatar request",
        issues: result.error.issues,
      });
      return;
    }

    try {
      response.json({
        sprites: await spriteGenerator(result.data),
        source: "nano-banana",
      });
    } catch (error) {
      response.status(503).json({
        error: "Avatar generation failed",
        detail: compactGenerationError(error),
      });
    }
  });

  app.patch("/api/cogs/:cogId/profile", (request, response) => {
    const result = updateCogProfileRequestSchema.safeParse(request.body);
    if (!result.success) {
      response.status(400).json({
        error: "Invalid cog profile request",
        issues: result.error.issues,
      });
      return;
    }

    try {
      const cog = world.updateCogProfile(request.params.cogId, result.data);
      persistWorld();
      response.json({
        cogId: cog.id,
        snapshot: compactWorldSnapshot(world.snapshot()),
      });
    } catch (error) {
      response.status(404).json({
        error: error instanceof Error ? error.message : "Unable to update cog profile",
      });
    }
  });

  const staticPath = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../dist");
  const publicPath = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../public");
  const indexPath = path.join(staticPath, "index.html");
  app.use("/api/*", (_request, response) => {
    response.status(404).json({ error: "Not found" });
  });
  app.use(mainGameBasicAuth);
  app.use(express.static(publicPath));
  app.use(express.static(staticPath));
  app.get("*", (_request, response) => {
    if (existsSync(indexPath)) {
      response.sendFile(indexPath);
      return;
    }

    response.status(404).type("text/plain").send("Client application has not been built");
  });

  return app;
}

const mainGameBasicAuth: RequestHandler = (request, response, next) => {
  if (!isMainGameDocumentRequest(request.method, request.path)) {
    next();
    return;
  }

  if (hasMainGameCredentials(request.get("authorization"))) {
    next();
    return;
  }

  response
    .status(401)
    .set("WWW-Authenticate", `Basic realm="${MAIN_GAME_AUTH_REALM}", charset="UTF-8"`)
    .type("text/plain")
    .send("Authentication required");
};

function isMainGameDocumentRequest(method: string, requestPath: string): boolean {
  return (method === "GET" || method === "HEAD") && (requestPath === "/" || requestPath === "/index.html");
}

function hasMainGameCredentials(authorization: string | undefined): boolean {
  if (!authorization) {
    return false;
  }

  const [scheme, encodedCredentials] = authorization.split(/\s+/, 2);
  if (scheme?.toLowerCase() !== "basic" || !encodedCredentials) {
    return false;
  }

  const decodedCredentials = Buffer.from(encodedCredentials, "base64").toString("utf8");
  const separatorIndex = decodedCredentials.indexOf(":");
  if (separatorIndex === -1) {
    return false;
  }

  return (
    decodedCredentials.slice(0, separatorIndex) === MAIN_GAME_AUTH_USERNAME &&
    decodedCredentials.slice(separatorIndex + 1) === MAIN_GAME_AUTH_PASSWORD
  );
}

function seedVenueEditorState(world: GridWorld): Omit<VenueEditorState, "updatedAt"> {
  const trackedSeed = loadTrackedVenueEditorSeed();
  if (trackedSeed) {
    return trackedSeed;
  }

  const snapshot = world.snapshot();
  const rooms = withSeededRoomRects(snapshot.venue?.rooms ?? [], snapshot.venue?.spots ?? []);
  return {
    imageUrl: VENUE_EDITOR_IMAGE_URL,
    dimensions: snapshot.dimensions,
    rooms,
    spots: snapshot.venue?.spots ?? [],
    links: [],
    paths: venueRoomPathsFromNeighbors(rooms),
  };
}

function loadTrackedVenueEditorSeed(): Omit<VenueEditorState, "updatedAt"> | undefined {
  const seedPath = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "venue-editor-seed.json");
  if (!existsSync(seedPath)) {
    return undefined;
  }

  const parsed = JSON.parse(readFileSync(seedPath, "utf8")) as Partial<Omit<VenueEditorState, "updatedAt">>;
  if (!parsed || !Array.isArray(parsed.rooms) || !Array.isArray(parsed.spots) || !Array.isArray(parsed.paths)) {
    return undefined;
  }

  return {
    imageUrl: typeof parsed.imageUrl === "string" ? parsed.imageUrl : VENUE_EDITOR_IMAGE_URL,
    dimensions:
      parsed.dimensions &&
      typeof parsed.dimensions.width === "number" &&
      typeof parsed.dimensions.height === "number"
        ? parsed.dimensions
        : { width: 50, height: 28 },
    rooms: withSeededRoomRects(parsed.rooms as VenueRoom[], parsed.spots as VenueSpot[]),
    spots: parsed.spots as VenueSpot[],
    links: [],
    paths: parsed.paths,
  };
}

function validateVenueEditorState(state: Omit<VenueEditorState, "updatedAt">): Array<{ path: Array<string | number>; message: string }> {
  const issues: Array<{ path: Array<string | number>; message: string }> = [];
  const roomIds = new Set<string>();
  const spotIds = new Set<string>();

  state.rooms.forEach((room, index) => {
    if (roomIds.has(room.id)) {
      issues.push({ path: ["rooms", index, "id"], message: `Duplicate room id: ${room.id}` });
      return;
    }

    roomIds.add(room.id);
  });

  state.rooms.forEach((room, index) => {
    const missingNeighbor = room.neighborIds.find((roomId) => !roomIds.has(roomId));
    if (missingNeighbor) {
      issues.push({ path: ["rooms", index, "neighborIds"], message: `Room references an unknown neighbor: ${missingNeighbor}` });
    }
  });

  state.spots.forEach((spot, index) => {
    if (spotIds.has(spot.id)) {
      issues.push({ path: ["spots", index, "id"], message: `Duplicate spot id: ${spot.id}` });
      return;
    }

    if (!roomIds.has(spot.roomId)) {
      issues.push({ path: ["spots", index, "roomId"], message: `Spot references an unknown room: ${spot.roomId}` });
    }

    spotIds.add(spot.id);
  });

  state.rooms.forEach((room, index) => {
    const missingSpot = room.spotIds.find((spotId) => !spotIds.has(spotId));
    if (missingSpot) {
      issues.push({ path: ["rooms", index, "spotIds"], message: `Room references an unknown spot: ${missingSpot}` });
    }

    const mismatchedSpot = room.spotIds.find((spotId) => state.spots.find((spot) => spot.id === spotId)?.roomId !== room.id);
    if (mismatchedSpot) {
      issues.push({ path: ["rooms", index, "spotIds"], message: `Room includes a spot assigned to another room: ${mismatchedSpot}` });
    }
  });

  state.paths.forEach((path, index) => {
    if (path.fromRoomId === path.toRoomId) {
      issues.push({ path: ["paths", index], message: "Path cannot connect a room to itself" });
      return;
    }

    if (!roomIds.has(path.fromRoomId) || !roomIds.has(path.toRoomId)) {
      issues.push({ path: ["paths", index], message: "Path references an unknown room" });
    }
  });

  return issues;
}

function withSeededRoomRects(rooms: VenueRoom[], spots: VenueSpot[]): VenueRoom[] {
  return rooms.map((room) => ({
    ...room,
    rect: room.rect ?? venueRoomRect(room, spots),
  }));
}

function configResponse(state: SettingsState): SettingsState & {
  parameters: typeof RULE_PARAMETERS;
  traits: typeof TRAIT_RULES;
  goals: typeof GOAL_RULES;
  achievements: typeof ACHIEVEMENT_RULES;
} {
  return {
    ...state,
    parameters: RULE_PARAMETERS,
    traits: TRAIT_RULES,
    goals: GOAL_RULES,
    achievements: ACHIEVEMENT_RULES,
  };
}

export function compactGenerationError(error: unknown): string {
  if (!error || typeof error !== "object") {
    return "Unknown avatar generation error";
  }

  const messageLines = error instanceof Error ? errorLines(error.message) : [];
  const stderrLines = "stderr" in error && typeof error.stderr === "string" ? errorLines(error.stderr) : [];
  const stdoutLines = "stdout" in error && typeof error.stdout === "string" ? errorLines(error.stdout) : [];
  const allLines = [...messageLines, ...stderrLines, ...stdoutLines];
  const importantLines = allLines.filter(isImportantGenerationErrorLine);
  const selectedLines =
    importantLines.length > 0
      ? importantLines.slice(-5)
      : stderrLines.length > 0
        ? stderrLines.slice(-4)
        : messageLines.length > 0
          ? messageLines.slice(-4)
          : stdoutLines.slice(-4);

  return selectedLines.join(" ") || "Unknown avatar generation error";
}

function errorLines(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function isImportantGenerationErrorLine(line: string): boolean {
  return /^(detail:|title:|status:|- input\.|Error:|replicate\.exceptions\.ReplicateError|ReplicateError Details:)/i.test(
    line,
  );
}

const jsonParseErrorHandler: ErrorRequestHandler = (error, request, response, next) => {
  if (error instanceof SyntaxError && "body" in error && request.path.startsWith("/api/")) {
    response.status(400).json({
      error: "Invalid JSON request body",
      issues: [
        {
          path: [],
          message: error.message,
        },
      ],
    });
    return;
  }

  next(error);
};
