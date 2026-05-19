import "./ui/styles.css";

import type {
  ControlRequest,
  CreateCogRequest,
  CreateCogResponse,
  GenerateCogSpritesResponse,
  KickCogResponse,
  PokeCogResponse,
  ServerMessage,
  ShuffleTeamsResponse,
  UpdateCogProfileRequest,
} from "../shared/protocol";
import type { GameConfig, GameConfigInput } from "../shared/rules";
import { legacyHalfSecondTicksToSimulationTicks, simulationTicksToMs } from "../shared/timing";
import type { CogAction, Color, Direction, ServerStatus, WorldSnapshot } from "../shared/types";
import { TEAM_COLORS } from "../shared/types";
import { WorldSocket } from "./net/world-socket";
import { CanvasBoardRenderer } from "./render/canvas-board-renderer";
import { CogRenderPositionTracker, cogPositionForRender, type CogRenderTiming } from "./render/cog-render-position";
import { renderOptionsForFrame } from "./render/render-clock";
import type { RenderOptions } from "./render/webgpu-board-renderer";
import { WebGpuBoardRenderer } from "./render/webgpu-board-renderer";
import type { CogBuilderCreateRequest, CogBuilderSpriteRequest, CogSpriteOption } from "./ui/cog-builder";
import { COG_ID_COOKIE_CLAIM_PARAM, clearCogIdCookie, setCogIdCookie } from "./cog-cookie";
import { isTrait, traits } from "./ui/cog-traits";
import { renderDebateBubbleContent } from "./ui/debate-bubble";
import { debateBubbleBoardPosition, debatePairKey, settledDebateEventsForOverlay } from "./ui/debate-overlay";
import { escapeHtml } from "./ui/html";
import { Hud, type ConfigPayload } from "./ui/hud";
import { mountVenueEditor } from "./ui/venue-editor";
import { mountStandaloneRoute, standaloneRouteForLocation } from "./standalone-routes";

const standaloneRoute = standaloneRouteForLocation();
if (standaloneRoute) {
  mountStandaloneRoute(standaloneRoute);
} else if (isVenueEditorRoute()) {
  mountVenueEditorRoute();
} else {
  startGameApp();
}

function mountVenueEditorRoute(): void {
  const app = document.querySelector<HTMLElement>("#app");
  if (!app) {
    throw new Error("Missing #app");
  }

  mountVenueEditor(app);
}

function isVenueEditorRoute(): boolean {
  const params = new URLSearchParams(window.location.search);
  return window.location.pathname === "/venue-editor" || params.get("editor") === "venue";
}

function startGameApp(): void {
const canvas = document.querySelector<HTMLCanvasElement>("#world-canvas");
const bubbleLayer = document.querySelector<HTMLElement>("#world-bubbles");
const hudElement = document.querySelector<HTMLElement>("#hud");

if (!canvas) {
  throw new Error("Missing #world-canvas");
}

if (!bubbleLayer) {
  throw new Error("Missing #world-bubbles");
}

if (!hudElement) {
  throw new Error("Missing #hud");
}

let snapshot: WorldSnapshot | undefined;
let gameConfig: GameConfig | undefined;
let serverStatus: ServerStatus | undefined;
let selectedCogId: string | undefined;
let selectionClearedManually = false;
let cogNumber = 1;
let socket: WorldSocket | undefined;
let renderer: BoardRenderer | undefined;
let renderEnabled = false;
let lastWorldOverlayMarkup = "";
const renderPositionTracker = new CogRenderPositionTracker();

type BuilderCreatedMessage = {
  type: "cogshambo-builder-created";
  cogId: string;
  snapshot: WorldSnapshot;
};

type BoardRenderer = {
  render(snapshot: WorldSnapshot | undefined, options: RenderOptions): void;
};

type BoardHitLayout = {
  offsetX: number;
  offsetY: number;
  tileSize: number;
  tileWidth: number;
  tileHeight: number;
  boardWidth: number;
  boardHeight: number;
};

type OverlayRect = {
  left: number;
  top: number;
  right: number;
  bottom: number;
};

type DebateBubbleInput = {
  first: WorldSnapshot["cogs"][number];
  second: WorldSnapshot["cogs"][number];
  boardX: number;
  boardY: number;
  events: WorldSnapshot["recentEvents"];
  currentTick: number;
  debateLog: NonNullable<WorldSnapshot["debateLog"]>;
};

type DebateBubblePlacement = {
  left: number;
  top: number;
  rect: OverlayRect;
};

const COG_HIT_RADIUS_TILES = 1.35;
const DEBATE_BUBBLE_Y_OFFSET_TILES = 3.25;
const DEBATE_BUBBLE_LINK_TIP_OFFSET_PX = 4;
const DEBATE_BUBBLE_LINK_COG_OFFSET_TILES = 0.48;
const DEBATE_BUBBLE_ESTIMATED_WIDTH = 200;
const DEBATE_BUBBLE_ESTIMATED_HEIGHT = 100;
const DEBATE_BUBBLE_LAYER_MARGIN = 12;
const DEBATE_BUBBLE_GAP = 10;
const CONVERSION_BUBBLE_TICKS = legacyHalfSecondTicksToSimulationTicks(24);
const COG_NAME_LABEL_Y_OFFSET_TILES = 1.08;
const PROFILE_WINDOW_TARGET = "cogshambo-profile";
const VENUE_EDITOR_WINDOW_TARGET = "cogshambo-venue-editor";
const MANUAL_MOVE_KEYS = new Map<string, Direction>([
  ["w", "north"],
  ["a", "west"],
  ["s", "south"],
  ["d", "east"],
]);

const hud = new Hud(hudElement, {
  onSpawnCog: () => {
    void spawnCog();
  },
  onCreateCog: (request) => createCog(request),
  onGenerateCogSprites: (request) => generateCogSprites(request),
  onOpenBuilderWindow: () => {
    openBuilderWindow();
  },
  onOpenProfileWindow: (cogId) => {
    openProfileWindow(cogId);
  },
  onOpenConfigWindow: () => {
    openConfigWindow();
  },
  onOpenVenueEditorWindow: () => {
    openVenueEditorWindow();
  },
  onCloseBuilder: () => {
    if (isBuilderWindow()) {
      window.close();
    }
  },
  onCloseConfig: () => {
    if (isConfigWindow()) {
      window.close();
    }
  },
  onSelectNextCog: () => {
    if (!snapshot?.cogs.length) {
      selectCog(undefined);
      return;
    }

    const selectedIndex = snapshot.cogs.findIndex((cog) => cog.id === selectedCogId);
    selectCog(snapshot.cogs[(selectedIndex + 1) % snapshot.cogs.length]?.id);
  },
  onSelectCog: (cogId) => {
    selectCog(cogId);
  },
  onSelectCogChoice: (cogId, action) => {
    sendManualCogAction(cogId, action);
  },
  onSaveCogProfile: (cogId, profile) => {
    void saveCogProfile(cogId, profile);
  },
  onKickCog: (cogId) => kickCog(cogId),
  onPokeCog: (cogId) => pokeCog(cogId),
  onAbandonCog: (cogId) => abandonCog(cogId),
  onSaveGameConfig: (config) => {
    void saveGameConfig(config);
  },
  onSelectSettingsPreset: (settingsDb) => {
    void selectSettingsPreset(settingsDb);
  },
  onCreateSettingsPreset: (name) => {
    void createSettingsPreset(name);
  },
  onShuffleTeams: () => {
    void shuffleTeams();
  },
  onToggleDisco: () => {
    void sendControl("toggleDisco");
  },
  onStop: () => {
    void sendControl("pause");
  },
  onPlay: () => {
    void sendControl("play");
  },
  onStep: () => {
    void sendControl("step");
  },
});

syncViewportSize();
hud.render();
void loadGameConfig();
canvas.addEventListener("click", (event) => {
  const cogId = cogIdAtCanvasPoint(event.clientX, event.clientY);
  if (cogId) {
    selectCog(cogId);
  }
});
window.addEventListener("keydown", handleManualControlKey);
window.addEventListener("message", handleWindowMessage);
window.addEventListener("resize", queueViewportSync);
window.visualViewport?.addEventListener("resize", queueViewportSync);
window.visualViewport?.addEventListener("scroll", queueViewportSync);

socket = WorldSocket.connect({
  onStatus: (connectionStatus) => {
    hud.update({ connectionStatus });
  },
  onMessage: (message) => {
    handleServerMessage(message);
  },
});
requestAnimationFrame(frame);
void initializeRenderer();

async function initializeRenderer(): Promise<void> {
  const webGpuRenderer = new WebGpuBoardRenderer(canvas, {
    onDeviceLost: (message) => {
      renderEnabled = false;
      renderer = undefined;
      void initializeCanvasFallback(`${message}; using Canvas2D renderer`);
    },
  });
  renderer = webGpuRenderer;

  try {
    await webGpuRenderer.initialize();
    renderEnabled = true;
  } catch (error) {
    await initializeCanvasFallback(`WebGPU unavailable: ${compactError(error)}; using Canvas2D renderer`);
  }
}

async function initializeCanvasFallback(notice: string | undefined): Promise<void> {
  try {
    const canvasRenderer = new CanvasBoardRenderer(canvas);
    await canvasRenderer.initialize();
    renderer = canvasRenderer;
    renderEnabled = true;
    if (notice) {
      hud.update({ notice: compactDetail(notice) });
    }
  } catch (error) {
    renderEnabled = false;
    renderer = undefined;
    hud.update({ notice: `Render unavailable: ${compactError(error)}` });
  }
}

async function spawnCog(): Promise<void> {
  const name = `Cog ${cogNumber}`;

  try {
    const response = await fetch("/api/cogs", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name,
        spriteSheetKey: "cog-default",
        controllerId: "llm",
        color: TEAM_COLORS[(cogNumber - 1) % TEAM_COLORS.length],
        defensiveTrait: traits[(cogNumber - 1) % traits.length],
        activeTrait: traits[cogNumber % traits.length],
        behaviorPrompt: "Use the current rules, seek useful debates, and coordinate with same-room cogs.",
        attributes: {
          energy: 5,
          focus: 5,
        },
      }),
    });

    if (!response.ok) {
      hud.update({ notice: `Spawn failed: ${await failureDetail(response)}` });
      return;
    }

    cogNumber += 1;
    hud.update({ notice: `Spawned ${name}` });
  } catch (error) {
    hud.update({ notice: `Spawn failed: ${compactError(error)}` });
  }
}

async function createCog(request: CogBuilderCreateRequest): Promise<string | undefined> {
  if (!isTrait(request.defensiveTrait) || !isTrait(request.activeTrait)) {
    hud.update({ notice: "Create failed: builder trait is not available for new cogs" });
    return undefined;
  }
  const payload: CreateCogRequest = {
    ...request,
    defensiveTrait: request.defensiveTrait,
    activeTrait: request.activeTrait,
    controllerId: "llm",
    color: request.color,
  };

  try {
    const response = await fetch("/api/cogs", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      hud.update({ notice: `Create failed: ${await failureDetail(response)}` });
      return undefined;
    }

    const body = (await response.json()) as CreateCogResponse;
    snapshot = body.snapshot;
    cogNumber += 1;
    setCogIdCookie(body.cogId);
    selectCog(body.cogId);
    hud.update({ notice: `Created ${request.name}` });
    notifyBuilderCreated(body.cogId, body.snapshot);
    return body.cogId;
  } catch (error) {
    hud.update({ notice: `Create failed: ${compactError(error)}` });
    return undefined;
  }
}

async function generateCogSprites(request: CogBuilderSpriteRequest): Promise<CogSpriteOption[] | undefined> {
  try {
    const response = await fetch("/api/cog-sprites", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      throw new Error(await failureDetail(response));
    }

    const body = (await response.json()) as GenerateCogSpritesResponse;
    const avatarNoun = body.sprites.length === 1 ? "avatar" : "avatars";
    hud.update({ notice: `Generated ${body.sprites.length} Nano Banana ${avatarNoun}` });
    return body.sprites;
  } catch (error) {
    hud.update({ notice: `Avatar generation failed: ${compactError(error)}` });
    throw error;
  }
}

async function shuffleTeams(): Promise<void> {
  try {
    const response = await fetch("/api/cogs/shuffle-teams", {
      method: "POST",
    });

    if (!response.ok) {
      hud.update({ notice: `Shuffle failed: ${await failureDetail(response)}` });
      return;
    }

    const body = (await response.json()) as ShuffleTeamsResponse;
    snapshot = body.snapshot;
    syncSelectedCogWithSnapshot(snapshot);
    hud.update({ notice: "Shuffled teams" });
    updateHud();
  } catch (error) {
    hud.update({ notice: `Shuffle failed: ${compactError(error)}` });
  }
}

function openBuilderWindow(): void {
  const url = new URL(window.location.href);
  url.pathname = "/builder";
  url.searchParams.delete("builder");
  url.searchParams.delete("config");
  url.searchParams.delete("profile");
  url.searchParams.delete("editor");
  url.hash = "";
  const popup = window.open(url.toString(), "cogshambo-cog-builder", "popup,width=1180,height=760");

  if (popup) {
    popup.focus();
    return;
  }

  window.location.href = url.toString();
}

function openProfileWindow(cogId: string): void {
  const url = new URL(window.location.href);
  url.pathname = `/profile/${encodeURIComponent(cogId)}`;
  url.searchParams.delete("profile");
  url.searchParams.delete("builder");
  url.searchParams.delete("config");
  url.searchParams.delete("editor");
  url.searchParams.set(COG_ID_COOKIE_CLAIM_PARAM, "1");
  url.hash = "";
  const popup = window.open(url.toString(), PROFILE_WINDOW_TARGET, "popup,width=980,height=820");

  if (popup) {
    popup.focus();
    return;
  }

  window.location.href = url.toString();
}

function openConfigWindow(): void {
  const url = new URL(window.location.href);
  url.pathname = "/config";
  url.searchParams.delete("config");
  url.searchParams.delete("builder");
  url.searchParams.delete("profile");
  url.searchParams.delete("editor");
  url.hash = "";
  const popup = window.open(url.toString(), "cogshambo-settings", "popup,width=1180,height=820");

  if (popup) {
    popup.focus();
    return;
  }

  window.location.href = url.toString();
}

function openVenueEditorWindow(): void {
  const url = new URL(window.location.href);
  url.pathname = "/venue-editor";
  url.searchParams.delete("editor");
  url.searchParams.delete("builder");
  url.searchParams.delete("config");
  url.searchParams.delete("profile");
  url.hash = "";
  const popup = window.open(url.toString(), VENUE_EDITOR_WINDOW_TARGET, "popup,width=1180,height=820");

  if (popup) {
    popup.focus();
    return;
  }

  window.location.href = url.toString();
}

function isBuilderWindow(): boolean {
  return trimTrailingSlash(window.location.pathname) === "/builder";
}

function isConfigWindow(): boolean {
  return trimTrailingSlash(window.location.pathname) === "/config";
}

function trimTrailingSlash(pathname: string): string {
  return pathname.length > 1 && pathname.endsWith("/") ? pathname.slice(0, -1) : pathname;
}

function notifyBuilderCreated(cogId: string, createdSnapshot: WorldSnapshot): void {
  if (!isBuilderWindow()) {
    return;
  }

  window.opener?.postMessage(
    {
      type: "cogshambo-builder-created",
      cogId,
      snapshot: createdSnapshot,
    } satisfies BuilderCreatedMessage,
    window.location.origin,
  );
  window.setTimeout(() => window.close(), 0);
}

function handleWindowMessage(event: MessageEvent<unknown>): void {
  if (event.origin !== window.location.origin || !isBuilderCreatedMessage(event.data)) {
    return;
  }

  snapshot = event.data.snapshot;
  selectCog(event.data.cogId);
  openProfileWindow(event.data.cogId);
  hud.update({ notice: "Created cog" });
}

function isBuilderCreatedMessage(value: unknown): value is BuilderCreatedMessage {
  return (
    Boolean(value) &&
    typeof value === "object" &&
    (value as { type?: unknown }).type === "cogshambo-builder-created" &&
    typeof (value as { cogId?: unknown }).cogId === "string" &&
    Boolean((value as { snapshot?: unknown }).snapshot) &&
    typeof (value as { snapshot?: unknown }).snapshot === "object" &&
    Array.isArray(((value as { snapshot: { cogs?: unknown } }).snapshot).cogs)
  );
}

async function saveCogProfile(cogId: string, profile: UpdateCogProfileRequest): Promise<void> {
  try {
    const response = await fetch(`/api/cogs/${encodeURIComponent(cogId)}/profile`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(profile),
    });

    if (!response.ok) {
      hud.update({ notice: `Profile save failed: ${await failureDetail(response)}` });
      return;
    }

    const body = (await response.json()) as { snapshot?: WorldSnapshot };
    if (body.snapshot) {
      snapshot = body.snapshot;
    }
    hud.update({ notice: "Profile saved" });
    updateHud();
  } catch (error) {
    hud.update({ notice: `Profile save failed: ${compactError(error)}` });
  }
}

async function abandonCog(_cogId: string): Promise<boolean> {
  clearCogIdCookie();
  hud.update({ notice: "Abandoned cog claim" });
  updateHud();
  window.location.href = "/builder";
  return true;
}

async function kickCog(cogId: string): Promise<boolean> {
  try {
    const response = await fetch(`/api/cogs/${encodeURIComponent(cogId)}/kick`, {
      method: "POST",
    });

    if (!response.ok) {
      hud.update({ notice: `Kick failed: ${await failureDetail(response)}` });
      return false;
    }

    const body = (await response.json()) as KickCogResponse;
    snapshot = body.snapshot;
    syncSelectedCogWithSnapshot(snapshot);
    hud.update({ notice: "Kicked cog home" });
    updateHud();
    return true;
  } catch (error) {
    hud.update({ notice: `Kick failed: ${compactError(error)}` });
    return false;
  }
}

async function pokeCog(cogId: string): Promise<boolean> {
  try {
    const response = await fetch(`/api/cogs/${encodeURIComponent(cogId)}/poke`, {
      method: "POST",
    });

    if (!response.ok) {
      hud.update({ notice: `Poke failed: ${await failureDetail(response)}` });
      return false;
    }

    const body = (await response.json()) as PokeCogResponse;
    snapshot = body.snapshot;
    hud.update({ notice: "Cog poked" });
    updateHud();
    return true;
  } catch (error) {
    hud.update({ notice: `Poke failed: ${compactError(error)}` });
    return false;
  }
}

async function loadGameConfig(): Promise<void> {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) {
      hud.update({ notice: `Config load failed: ${await failureDetail(response)}` });
      return;
    }

    const payload = (await response.json()) as ConfigPayload;
    gameConfig = payload.config;
    hud.update({ gameConfig: payload });
  } catch (error) {
    hud.update({ notice: `Config load failed: ${compactError(error)}` });
  }
}

async function saveGameConfig(config: GameConfigInput): Promise<void> {
  try {
    const response = await fetch("/api/config", {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(config),
    });

    if (!response.ok) {
      hud.update({ notice: `Config save failed: ${await failureDetail(response)}` });
      return;
    }

    const payload = (await response.json()) as ConfigPayload;
    gameConfig = payload.config;
    hud.update({ gameConfig: payload, notice: "Config saved" });
  } catch (error) {
    hud.update({ notice: `Config save failed: ${compactError(error)}` });
  }
}

async function selectSettingsPreset(settingsDb: string): Promise<void> {
  try {
    const response = await fetch("/api/config/current", {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ settingsDb }),
    });

    if (!response.ok) {
      hud.update({ notice: `Settings preset switch failed: ${await failureDetail(response)}` });
      return;
    }

    const payload = (await response.json()) as ConfigPayload;
    gameConfig = payload.config;
    hud.update({ gameConfig: payload, notice: "Settings preset selected" });
  } catch (error) {
    hud.update({ notice: `Settings preset switch failed: ${compactError(error)}` });
  }
}

async function createSettingsPreset(name: string): Promise<void> {
  try {
    const response = await fetch("/api/config/presets", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ name }),
    });

    if (!response.ok) {
      hud.update({ notice: `Settings preset create failed: ${await failureDetail(response)}` });
      return;
    }

    const payload = (await response.json()) as ConfigPayload;
    gameConfig = payload.config;
    hud.update({ gameConfig: payload, notice: "Settings preset created" });
  } catch (error) {
    hud.update({ notice: `Settings preset create failed: ${compactError(error)}` });
  }
}

async function sendControl(command: ControlRequest["command"]): Promise<void> {
  try {
    const response = await fetch("/api/control", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ command }),
    });

    if (!response.ok) {
      hud.update({ notice: `Control failed: ${await failureDetail(response)}` });
      return;
    }

    const body = (await response.json()) as {
      status?: Pick<
        ServerStatus,
        | "discoMode"
        | "llmMoveDecisions"
        | "llmTimedOutMovePercent"
        | "llmTimedOutMoves"
        | "simulationMode"
        | "stepRequested"
      >;
    };
    if (body.status) {
      serverStatus = {
        tick: serverStatus?.tick ?? snapshot?.tick ?? 0,
        cogCount: serverStatus?.cogCount ?? snapshot?.cogs.length ?? 0,
        clientCount: serverStatus?.clientCount ?? 0,
        controllerMode: serverStatus?.controllerMode ?? snapshot?.cogs[0]?.controllerId ?? "llm",
        discoMode: body.status.discoMode,
        llmMoveDecisions: body.status.llmMoveDecisions ?? serverStatus?.llmMoveDecisions ?? 0,
        llmTimedOutMovePercent: body.status.llmTimedOutMovePercent ?? serverStatus?.llmTimedOutMovePercent ?? 0,
        llmTimedOutMoves: body.status.llmTimedOutMoves ?? serverStatus?.llmTimedOutMoves ?? 0,
        simulationMode: body.status.simulationMode,
        stepRequested: body.status.stepRequested,
      };
    }

    hud.update({ notice: controlNotice(command) });
    updateHud();
  } catch (error) {
    hud.update({ notice: `Control failed: ${compactError(error)}` });
  }
}

async function failureDetail(response: Response): Promise<string> {
  const fallback = `${response.status} ${response.statusText || "error"}`.trim();

  try {
    const body: unknown = await response.json();
    if (
      body &&
      typeof body === "object" &&
      "error" in body &&
      typeof body.error === "string"
    ) {
      const detail = "detail" in body && typeof body.detail === "string" ? `: ${body.detail}` : "";
      return compactDetail(`${fallback} ${body.error}${detail}`);
    }
  } catch {
    // Fall back to the HTTP status below.
  }

  return compactDetail(fallback);
}

function controlNotice(command: ControlRequest["command"]): string {
  switch (command) {
    case "pause":
      return "Stopped simulation";
    case "play":
      return "Playing simulation";
    case "step":
      return "Queued one step";
    case "toggleDisco":
      return serverStatus?.discoMode ? "Disco mode on" : "Disco mode off";
  }
}

function selectCog(cogId: string | undefined): void {
  selectedCogId = cogId;
  selectionClearedManually = !cogId;
  if (selectedCogId) {
    socket?.send({ type: "debugCommand", command: "followCog", cogId: selectedCogId });
  }
  updateHud();
}

function syncSelectedCogWithSnapshot(nextSnapshot: WorldSnapshot): void {
  if (nextSnapshot.cogs.length === 0) {
    selectedCogId = undefined;
    selectionClearedManually = false;
    return;
  }

  if (selectedCogId && !nextSnapshot.cogs.some((cog) => cog.id === selectedCogId)) {
    selectedCogId = undefined;
  }

  if (!selectedCogId && !selectionClearedManually) {
    selectedCogId = nextSnapshot.cogs[0]?.id;
  }
}

function handleManualControlKey(event: KeyboardEvent): void {
  if (event.defaultPrevented) {
    return;
  }

  if (isShortcutsPanelShortcut(event)) {
    event.preventDefault();
    hud.toggleShortcutsPanel();
    return;
  }

  if (isControlsPanelShortcut(event)) {
    event.preventDefault();
    hud.toggleControlsPanel();
    return;
  }

  if (isRosterPanelShortcut(event)) {
    event.preventDefault();
    hud.toggleRosterPanel();
    return;
  }

  if (isBuilderQrShortcut(event)) {
    event.preventDefault();
    hud.toggleBuilderQrCard();
    return;
  }

  if (isDiscoModeShortcut(event)) {
    event.preventDefault();
    void sendControl("toggleDisco");
    return;
  }

  if (isShuffleTeamsShortcut(event)) {
    event.preventDefault();
    void shuffleTeams();
    return;
  }

  if (isBrowserShortcutChord(event) || shouldIgnoreManualControlKey(event.target)) {
    return;
  }

  if (isClearCogSelectionShortcut(event)) {
    if (selectedCogId) {
      event.preventDefault();
      selectCog(undefined);
    }
    return;
  }

  if (event.key === " " || event.code === "Space" || event.key === "Spacebar") {
    event.preventDefault();
    void sendControl((serverStatus?.simulationMode ?? "playing") === "paused" ? "play" : "pause");
    return;
  }

  const direction = MANUAL_MOVE_KEYS.get(event.key.toLowerCase());
  if (!direction || !selectedCogId) {
    return;
  }

  event.preventDefault();
  socket?.send({ type: "manualMove", cogId: selectedCogId, direction });
}

function isShortcutsPanelShortcut(event: KeyboardEvent): boolean {
  return !event.metaKey &&
    !event.ctrlKey &&
    !event.altKey &&
    !event.shiftKey &&
    (event.key === "F1" || event.code === "F1");
}

function isControlsPanelShortcut(event: KeyboardEvent): boolean {
  return event.metaKey &&
    !event.ctrlKey &&
    !event.altKey &&
    !event.shiftKey &&
    (event.key.toLowerCase() === "g" || event.code === "KeyG");
}

function isRosterPanelShortcut(event: KeyboardEvent): boolean {
  return event.metaKey &&
    !event.ctrlKey &&
    !event.altKey &&
    !event.shiftKey &&
    (event.key.toLowerCase() === "r" || event.code === "KeyR");
}

function isBuilderQrShortcut(event: KeyboardEvent): boolean {
  return event.metaKey &&
    !event.ctrlKey &&
    !event.altKey &&
    !event.shiftKey &&
    (event.key.toLowerCase() === "b" || event.code === "KeyB");
}

function isDiscoModeShortcut(event: KeyboardEvent): boolean {
  return event.metaKey &&
    !event.ctrlKey &&
    !event.altKey &&
    !event.shiftKey &&
    (event.key.toLowerCase() === "d" || event.code === "KeyD");
}

function isShuffleTeamsShortcut(event: KeyboardEvent): boolean {
  return event.metaKey &&
    !event.ctrlKey &&
    !event.altKey &&
    !event.shiftKey &&
    (event.key.toLowerCase() === "s" || event.code === "KeyS");
}

function isClearCogSelectionShortcut(event: KeyboardEvent): boolean {
  return !event.metaKey &&
    !event.ctrlKey &&
    !event.altKey &&
    !event.shiftKey &&
    (event.key === "Escape" || event.code === "Escape");
}

function isBrowserShortcutChord(event: KeyboardEvent): boolean {
  return event.metaKey || event.ctrlKey || event.altKey;
}

function sendManualCogAction(
  cogId: string,
  action:
    | Extract<CogAction, { type: "move" }>
    | Extract<CogAction, { type: "debate" }>
    | Extract<CogAction, { type: "chooseTactic" }>
    | Extract<CogAction, { type: "wait" }>,
): void {
  selectCog(cogId);
  socket?.send({ type: "manualAction", cogId, action });
}

function shouldIgnoreManualControlKey(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }

  if (target.isContentEditable || target.closest("input, textarea, select, .cog-profile-page, .cog-builder-page")) {
    return true;
  }

  return false;
}

function compactError(error: unknown): string {
  if (error instanceof Error && error.message) {
    return compactDetail(error.message);
  }

  return "network error";
}

function compactDetail(detail: string): string {
  return detail.length > 80 ? `${detail.slice(0, 77)}...` : detail;
}

function handleServerMessage(message: ServerMessage): void {
  if (message.type === "snapshot") {
    snapshot = message.snapshot;
    serverStatus = serverStatus
      ? {
          ...serverStatus,
          tick: snapshot.tick,
          cogCount: snapshot.cogs.length,
        }
      : serverStatus;

    syncSelectedCogWithSnapshot(snapshot);
    updateHud();
    return;
  }

  if (message.type === "serverStatus") {
    serverStatus = message.status;
    updateHud();
  }
}

function updateHud(): void {
  hud.update({
    selectedCogId,
    serverStatus,
    snapshot,
  });
}

function cogIdAtCanvasPoint(clientX: number, clientY: number): string | undefined {
  if (!snapshot) {
    return undefined;
  }

  const rect = canvas.getBoundingClientRect();
  const x = clientX - rect.left;
  const y = clientY - rect.top;
  const layout = fitBoardForHitTest(rect.width, rect.height, snapshot.dimensions.width, snapshot.dimensions.height);
  const hitRadius = layout.tileSize * COG_HIT_RADIUS_TILES;
  let bestHit: { cogId: string; distance: number } | undefined;

  for (const cog of snapshot.cogs) {
    const [centerX, centerY] = boardPointForHitTest(cog.position.x + 0.5, cog.position.y + 0.5, layout);
    const distance = Math.hypot(x - centerX, y - centerY);
    if (distance <= hitRadius && (!bestHit || distance < bestHit.distance)) {
      bestHit = { cogId: cog.id, distance };
    }
  }

  return bestHit?.cogId;
}

function fitBoardForHitTest(width: number, height: number, columns: number, rows: number): BoardHitLayout {
  const boardRatio = columns / rows;
  const targetRatio = width / height;
  const boardWidth = targetRatio > boardRatio ? height * boardRatio : width;
  const boardHeight = targetRatio > boardRatio ? height : width / boardRatio;
  const tileWidth = boardWidth / columns;
  const tileHeight = boardHeight / rows;
  const tileSize = Math.min(tileWidth, tileHeight);
  return {
    offsetX: (width - boardWidth) / 2,
    offsetY: (height - boardHeight) / 2,
    tileSize,
    tileWidth,
    tileHeight,
    boardWidth,
    boardHeight,
  };
}

function boardPointForHitTest(x: number, y: number, layout: BoardHitLayout): [number, number] {
  return [layout.offsetX + x * layout.tileWidth, layout.offsetY + y * layout.tileHeight];
}

function renderWorldOverlay(frameTimeMs: number, renderTiming: CogRenderTiming | undefined): void {
  if (!snapshot) {
    setWorldOverlayMarkup("");
    return;
  }

  const layout = fitBoardForHitTest(
    bubbleLayer.clientWidth,
    bubbleLayer.clientHeight,
    snapshot.dimensions.width,
    snapshot.dimensions.height,
  );
  const debatePairs: Array<{ first: WorldSnapshot["cogs"][number]; second: WorldSnapshot["cogs"][number] }> = [];
  const pairedCogIds = new Set<string>();
  const activeDebatePairKeys = new Set<string>();
  for (const cog of snapshot.cogs) {
    if (!cog.debate || pairedCogIds.has(cog.id)) {
      continue;
    }

    const opponent = snapshot.cogs.find((candidate) => candidate.id === cog.debate?.opponentId);
    if (!opponent || opponent.debate?.opponentId !== cog.id || pairedCogIds.has(opponent.id) || opponent.color === cog.color) {
      continue;
    }

    debatePairs.push({ first: cog, second: opponent });
    pairedCogIds.add(cog.id);
    pairedCogIds.add(opponent.id);
    activeDebatePairKeys.add(debatePairKey(cog.id, opponent.id));
  }

  const activeDebateBubbles: DebateBubbleInput[] = debatePairs.map(({ first, second }) => {
    const position = debateBubbleBoardPosition(first, second);
    return {
      first,
      second,
      boardX: position.x,
      boardY: position.y,
      events: snapshot.recentEvents,
      currentTick: snapshot.tick,
      debateLog: snapshot.debateLog ?? [],
    };
  });
  const settledDebateBubbles: DebateBubbleInput[] = settledDebateEventsForOverlay(snapshot, activeDebatePairKeys)
    .flatMap((event) => {
      if (!event.debate) {
        return [];
      }

      const [firstAction, secondAction] = event.debate.actions;
      const first = snapshot.cogs.find((cog) => cog.id === firstAction.cogId);
      const second = snapshot.cogs.find((cog) => cog.id === secondAction.cogId);
      if (!first || !second) {
        return [];
      }

      const position = debateBubbleBoardPosition(first, second);
      return [
        {
          first,
          second,
          boardX: position.x,
          boardY: position.y,
          events: [event],
          currentTick: snapshot.tick,
          debateLog: snapshot.debateLog ?? [],
        },
      ];
  });
  const debateBubbleInputs = [...activeDebateBubbles, ...settledDebateBubbles];
  const cogNameLabelsMarkup = renderCogNameLabels(snapshot, layout, frameTimeMs, renderTiming);
  const debateBubblesMarkup = renderDebateBubbles(debateBubbleInputs, layout);

  const conversionBubblesMarkup = snapshot.recentEvents
    .filter((event) => event.type === "colorChange" && event.actorId && snapshot.tick - event.tick < CONVERSION_BUBBLE_TICKS)
    .map((event) => {
      const cog = snapshot.cogs.find((candidate) => candidate.id === event.actorId);
      return cog ? renderConversionBubble(cog, event, layout, snapshot.tick - event.tick) : "";
    })
    .join("");
  const worldOverlayMarkup = `${cogNameLabelsMarkup}${debateBubblesMarkup}${conversionBubblesMarkup}`;

  setWorldOverlayMarkup(worldOverlayMarkup);
}

function renderCogNameLabels(
  currentSnapshot: WorldSnapshot,
  layout: BoardHitLayout,
  frameTimeMs: number,
  renderTiming: CogRenderTiming | undefined,
): string {
  return currentSnapshot.cogs
    .map((cog) => renderCogNameLabel(cog, currentSnapshot, layout, frameTimeMs, renderTiming))
    .join("");
}

function renderCogNameLabel(
  cog: WorldSnapshot["cogs"][number],
  currentSnapshot: WorldSnapshot,
  layout: BoardHitLayout,
  frameTimeMs: number,
  renderTiming: CogRenderTiming | undefined,
): string {
  const position = cogPositionForRender(cog, currentSnapshot, frameTimeMs, renderTiming);
  const [centerX, centerY] = boardPointForHitTest(position.x + 0.5, position.y + 0.5, layout);
  const left = clamp(centerX, 12, bubbleLayer.clientWidth - 12);
  const top = clamp(centerY - layout.tileSize * COG_NAME_LABEL_Y_OFFSET_TILES, 12, bubbleLayer.clientHeight - 12);
  return `
    <div
      aria-label="${escapeAttribute(`${cog.name} name label`)}"
      class="cog-name-label cog-name-label-${escapeAttribute(cog.color)}"
      data-cog-id="${escapeAttribute(cog.id)}"
      data-cog-name-label
      style="left: ${left.toFixed(1)}px; top: ${top.toFixed(1)}px;"
    >${escapeHtml(cog.name)}</div>
  `;
}

function renderDebateBubbles(inputs: DebateBubbleInput[], layout: BoardHitLayout): string {
  const occupiedRects: OverlayRect[] = [];
  return inputs
    .map((input) => {
      const placement = placeDebateBubble(input.boardX, input.boardY, layout, occupiedRects);
      occupiedRects.push(expandRect(placement.rect, DEBATE_BUBBLE_GAP));
      return renderDebateBubble(input, layout, placement.left, placement.top);
    })
    .join("");
}

function renderDebateBubble(input: DebateBubbleInput, layout: BoardHitLayout, left: number, top: number): string {
  const { first, second, events, currentTick, debateLog } = input;
  const cogIds = `${first.id} ${second.id}`;
  const bubbleClasses = `debate-bubble debate-bubble-first-${first.color} debate-bubble-second-${second.color}`;
  return `${renderDebateBubbleLinks(first, second, left, top, layout, cogIds)}<div class="${bubbleClasses}" data-debate-bubble data-debate-cogs="${escapeAttribute(cogIds)}" style="left: ${left.toFixed(1)}px; top: ${top.toFixed(1)}px;" aria-label="${escapeAttribute(`${first.name} versus ${second.name} debate actions`)}">${renderDebateBubbleContent(first, second, events, currentTick, debateLog, gameConfig?.conversionThreshold)}</div>`;
}

function placeDebateBubble(
  boardX: number,
  boardY: number,
  layout: BoardHitLayout,
  occupiedRects: OverlayRect[],
): DebateBubblePlacement {
  const [centerX, centerY] = boardPointForHitTest(boardX, boardY, layout);
  const candidates = debateBubblePlacementCandidates(centerX, centerY, layout);

  let bestPlacement: DebateBubblePlacement | undefined;
  let bestScore = Number.POSITIVE_INFINITY;
  for (const candidate of candidates) {
    const placement = debateBubblePlacement(candidate.left, candidate.top);
    const overlapPenalty = occupiedRects.reduce((total, rect) => total + rectOverlapArea(placement.rect, rect), 0);
    const distancePenalty = Math.hypot(placement.left - candidates[0].left, placement.top - candidates[0].top);
    const score = overlapPenalty * 100 + distancePenalty;
    if (score < bestScore) {
      bestScore = score;
      bestPlacement = placement;
    }

    if (overlapPenalty === 0) {
      break;
    }
  }

  return bestPlacement ?? debateBubblePlacement(candidates[0].left, candidates[0].top);
}

function debateBubblePlacementCandidates(
  centerX: number,
  centerY: number,
  layout: BoardHitLayout,
): Array<{ left: number; top: number }> {
  const preferredTop = centerY - layout.tileSize * DEBATE_BUBBLE_Y_OFFSET_TILES;
  const sideTop = centerY - layout.tileSize * 1.45;
  const highTop = preferredTop - DEBATE_BUBBLE_ESTIMATED_HEIGHT * 0.78;
  const belowTop = centerY + DEBATE_BUBBLE_ESTIMATED_HEIGHT + layout.tileSize * 0.7;
  const sideOffset = DEBATE_BUBBLE_ESTIMATED_WIDTH * 0.62;
  const wideOffset = DEBATE_BUBBLE_ESTIMATED_WIDTH * 0.86;

  return [
    { left: centerX, top: preferredTop },
    { left: centerX - sideOffset, top: preferredTop },
    { left: centerX + sideOffset, top: preferredTop },
    { left: centerX, top: highTop },
    { left: centerX - sideOffset, top: highTop },
    { left: centerX + sideOffset, top: highTop },
    { left: centerX - wideOffset, top: sideTop },
    { left: centerX + wideOffset, top: sideTop },
    { left: centerX, top: belowTop },
    { left: centerX - sideOffset, top: belowTop },
    { left: centerX + sideOffset, top: belowTop },
  ];
}

function debateBubblePlacement(left: number, top: number): DebateBubblePlacement {
  const clampedLeft = clamp(
    left,
    DEBATE_BUBBLE_LAYER_MARGIN + DEBATE_BUBBLE_ESTIMATED_WIDTH / 2,
    bubbleLayer.clientWidth - DEBATE_BUBBLE_LAYER_MARGIN - DEBATE_BUBBLE_ESTIMATED_WIDTH / 2,
  );
  const clampedTop = clamp(
    top,
    DEBATE_BUBBLE_LAYER_MARGIN + DEBATE_BUBBLE_ESTIMATED_HEIGHT,
    bubbleLayer.clientHeight - DEBATE_BUBBLE_LAYER_MARGIN,
  );
  const rect = {
    left: clampedLeft - DEBATE_BUBBLE_ESTIMATED_WIDTH / 2,
    top: clampedTop - DEBATE_BUBBLE_ESTIMATED_HEIGHT,
    right: clampedLeft + DEBATE_BUBBLE_ESTIMATED_WIDTH / 2,
    bottom: clampedTop,
  };

  return {
    left: clampedLeft,
    top: clampedTop,
    rect,
  };
}

function rectOverlapArea(first: OverlayRect, second: OverlayRect): number {
  const width = Math.max(0, Math.min(first.right, second.right) - Math.max(first.left, second.left));
  const height = Math.max(0, Math.min(first.bottom, second.bottom) - Math.max(first.top, second.top));
  return width * height;
}

function expandRect(rect: OverlayRect, amount: number): OverlayRect {
  return {
    left: rect.left - amount,
    top: rect.top - amount,
    right: rect.right + amount,
    bottom: rect.bottom + amount,
  };
}

function renderDebateBubbleLinks(
  first: WorldSnapshot["cogs"][number],
  second: WorldSnapshot["cogs"][number],
  bubbleLeft: number,
  bubbleTop: number,
  layout: BoardHitLayout,
  cogIds: string,
): string {
  const [firstX, firstY] = debateCogLinkAnchor(first, layout);
  const [secondX, secondY] = debateCogLinkAnchor(second, layout);
  const startX = bubbleLeft;
  const startY = bubbleTop + DEBATE_BUBBLE_LINK_TIP_OFFSET_PX;
  const width = Math.max(1, bubbleLayer.clientWidth);
  const height = Math.max(1, bubbleLayer.clientHeight);

  return `
    <svg
      class="debate-bubble-links"
      data-debate-bubble-links
      data-debate-cogs="${escapeAttribute(cogIds)}"
      width="${width}"
      height="${height}"
      viewBox="0 0 ${width} ${height}"
      aria-hidden="true"
      focusable="false"
    >
      ${renderDebateBubbleLink(startX, startY, firstX, firstY, "first", first.color)}
      ${renderDebateBubbleLink(startX, startY, secondX, secondY, "second", second.color)}
    </svg>
  `;
}

function renderDebateBubbleLink(startX: number, startY: number, endX: number, endY: number, role: string, color: Color): string {
  return `<line class="debate-bubble-link debate-bubble-link-${role} debate-bubble-link-${color}" data-debate-bubble-link x1="${startX.toFixed(1)}" y1="${startY.toFixed(1)}" x2="${endX.toFixed(1)}" y2="${endY.toFixed(1)}"></line>`;
}

function debateCogLinkAnchor(cog: WorldSnapshot["cogs"][number], layout: BoardHitLayout): [number, number] {
  const [centerX, centerY] = boardPointForHitTest(cog.position.x + 0.5, cog.position.y + 0.5, layout);
  return [centerX, centerY - layout.tileSize * DEBATE_BUBBLE_LINK_COG_OFFSET_TILES];
}

function renderConversionBubble(
  cog: WorldSnapshot["cogs"][number],
  event: WorldSnapshot["recentEvents"][number],
  layout: BoardHitLayout,
  ageTicks: number,
): string {
  const [centerX, centerY] = boardPointForHitTest(cog.position.x + 0.5, cog.position.y + 0.5, layout);
  const left = clamp(centerX, 18, bubbleLayer.clientWidth - 18);
  const top = clamp(centerY - layout.tileSize * 1.15, 12, bubbleLayer.clientHeight - 12);
  const ageMs = simulationTicksToMs(Math.max(0, ageTicks));
  const colors = conversionColorsForEvent(event, cog.color);
  return `
    <div
      aria-label="${escapeAttribute(`${cog.name} converted from ${colors.from} to ${colors.to}`)}"
      class="conversion-bubble conversion-bubble-from-${escapeAttribute(colors.from)} conversion-bubble-to-${escapeAttribute(colors.to)}"
      data-conversion-bubble
      data-cog-id="${escapeAttribute(cog.id)}"
      style="left: ${left.toFixed(1)}px; top: ${top.toFixed(1)}px; --conversion-age-ms: -${ageMs}ms;"
    >
      <span class="conversion-team-wave" aria-hidden="true"></span>
      <span class="conversion-token" aria-hidden="true">
        <span class="conversion-old-color"></span>
        <span class="conversion-new-color"></span>
        <span class="conversion-split-line"></span>
      </span>
      <span class="conversion-team-stamp" aria-hidden="true">${escapeHtml(colors.to.toUpperCase())}</span>
    </div>
  `;
}

function conversionColorsForEvent(event: WorldSnapshot["recentEvents"][number], fallbackTo: Color): { from: Color; to: Color } {
  const match = event.message.match(/\bfrom (red|blue) to (red|blue)\b/i);
  const from = teamColorFromString(match?.[1]) ?? (fallbackTo === "red" ? "blue" : "red");
  const to = teamColorFromString(match?.[2]) ?? fallbackTo;
  return { from, to };
}

function teamColorFromString(value: string | undefined): Color | undefined {
  return value && TEAM_COLORS.includes(value.toLowerCase() as Color) ? (value.toLowerCase() as Color) : undefined;
}

function setWorldOverlayMarkup(markup: string): void {
  if (markup === lastWorldOverlayMarkup) {
    return;
  }

  bubbleLayer.innerHTML = markup;
  lastWorldOverlayMarkup = markup;
}

let viewportSyncFrame: number | undefined;

function queueViewportSync(): void {
  if (viewportSyncFrame !== undefined) {
    window.cancelAnimationFrame(viewportSyncFrame);
  }

  viewportSyncFrame = window.requestAnimationFrame(() => {
    viewportSyncFrame = undefined;
    syncViewportSize();
  });
}

function syncViewportSize(): void {
  const viewport = window.visualViewport;
  const width = Math.max(1, Math.floor(viewport?.width ?? window.innerWidth));
  const height = Math.max(1, Math.floor(viewport?.height ?? window.innerHeight));
  const rootStyle = document.documentElement.style;
  rootStyle.setProperty("--app-width", `${width}px`);
  rootStyle.setProperty("--app-height", `${height}px`);
  lastWorldOverlayMarkup = "";
}

function escapeAttribute(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("\"", "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function clamp(value: number, minimum: number, maximum: number): number {
  if (maximum < minimum) {
    return minimum;
  }

  return Math.min(Math.max(value, minimum), maximum);
}

function frame(now: number): void {
  const frameOptions = renderOptionsForFrame({
    frameTimeMs: now,
    selectedCogId,
    serverStatus,
  });
  const renderTiming = snapshot ? renderPositionTracker.timingForSnapshot(snapshot, frameOptions.discoLightTimeMs ?? now) : undefined;
  const sharedFrameOptions = { ...frameOptions, renderTiming };

  if (renderEnabled) {
    renderer?.render(snapshot, sharedFrameOptions);
  }
  renderWorldOverlay(frameOptions.discoLightTimeMs ?? now, renderTiming);
  requestAnimationFrame(frame);
}
}
