import { TEAM_COLORS } from "../../shared/types";
import type {
  AchievementCount,
  AchievementAssignment,
  AchievementParameters,
  CogAction,
  CogConversationMessage,
  DebateLogEntry,
  Color,
  CompletedAchievement,
  DebateTactic,
  FailedAchievement,
  ServerStatus,
  WorldEvent,
  WorldSnapshot,
} from "../../shared/types";
import {
  ACHIEVEMENT_RULES,
  DEFAULT_GAME_CONFIG,
  achievementKey,
  achievementRuleByAssignment,
  traitPlayerDescription,
  traitPromptDescription,
  type AchievementRule,
  type GameConfig,
  type GameConfigInput,
  type GoalRule,
  type RuleParameter,
  type TraitParameter,
  type TraitRule,
} from "../../shared/rules";
import { isValidCogRoomHistoryEntry } from "../../shared/room-history";
import {
  cogTactic as debateTacticForCog,
  convertedDebatersFromWitnessedDebates,
  convertedOpponentsAfterDebate,
  hasCounterComeback,
  hasDenySweep,
  hasDrawBreaker,
  hasRoomComeback,
  hasWinFromBehind,
} from "../../shared/achievements/helpers";
import {
  SIMULATION_STEPS_PER_SECOND,
  SIMULATION_TICK_SECONDS,
  legacyHalfSecondTicksToSimulationTicks,
  secondsToSimulationTicks,
  simulationTicksToMs,
} from "../../shared/timing";
import { venueSpotIsSpeaker } from "../../shared/venue";
import { spriteEntries } from "../render/atlas";
import { spriteUrlForCog } from "../render/cog-sprite-ref";
import {
  BUILDER_APPEARANCE_MAX_LENGTH,
  BUILDER_STRATEGY_PROMPTS,
  BUILDER_STRATEGY_MAX_LENGTH,
  cogBuilderSteps,
  createBuilderPreviewDraft,
  createInitialBuilderDraft,
  parseBuilderColor,
  randomItem,
  renderCogBuilderPage,
  sanitizeCogForename,
  type CogBuilderCreateRequest,
  type CogBuilderDraft,
  type CogBuilderStep,
  type CogBuilderSpriteRequest,
  type CogBuilderTextRollStep,
  type CogBuilderTraitKind,
  type CogBuilderTraitRoll,
  type CogSpriteOption,
} from "./cog-builder";
import { profileQrUrl, renderBuilderQrCard, renderQrSvg } from "./builder-qr";
import type { CogProfileUpdate } from "./cog-profile";
import {
  isTrait,
  traits,
  type TraitKind,
} from "./cog-traits";
import { DEBATE_TACTIC_BEATS, DEBATE_TACTIC_ICONS, DEBATE_TACTIC_LABELS } from "./debate-tactics";
import { escapeHtml } from "./html";
import { renderReadOnlyTraitBadge } from "./trait-badges";
import { mountVenueEditor } from "./venue-editor";

export type HudState = {
  connectionStatus: string;
  gameConfig: ConfigPayload | undefined;
  notice: string | undefined;
  selectedCogId: string | undefined;
  serverStatus: ServerStatus | undefined;
  snapshot: WorldSnapshot | undefined;
};

export type ConfigPayload = {
  config: GameConfig;
  settingsDb?: string;
  presets?: Array<{
    settingsDb: string;
    name: string;
    updatedAt: string;
  }>;
  parameters: RuleParameter[];
  traits: TraitRule[];
  goals: GoalRule[];
  achievements: AchievementRule[];
};

export type HudActions = {
  onSpawnCog: () => void;
  onCreateCog: (request: CogBuilderCreateRequest) => Promise<string | undefined>;
  onGenerateCogSprites: (request: CogBuilderSpriteRequest) => Promise<CogSpriteOption[] | undefined>;
  onOpenBuilderWindow: () => void;
  onOpenProfileWindow: (cogId: string) => void;
  onOpenConfigWindow: () => void;
  onOpenVenueEditorWindow: () => void;
  onCloseBuilder: () => void;
  onCloseConfig: () => void;
  onSelectNextCog: () => void;
  onSelectCog: (cogId: string) => void;
  onSelectCogChoice: (cogId: string, action: ManualCogChoiceAction) => void;
  onSaveCogProfile: (cogId: string, profile: CogProfileUpdate) => void;
  onKickCog: (cogId: string) => Promise<boolean>;
  onPokeCog: (cogId: string) => Promise<boolean>;
  onAbandonCog: (cogId: string) => Promise<boolean>;
  onSaveGameConfig: (config: GameConfigInput) => void;
  onSelectSettingsPreset: (settingsDb: string) => void;
  onCreateSettingsPreset: (name: string) => void;
  onShuffleTeams: () => void;
  onToggleDisco: () => void;
  onStop: () => void;
  onPlay: () => void;
  onStep: () => void;
};

type CogProfileDraft = CogProfileUpdate;
type CogSnapshot = WorldSnapshot["cogs"][number];
export type DiaryEventKind = "achievement" | "flip" | "debate" | "witness" | "person";
type DiaryCogRef = Pick<CogSnapshot, "id" | "name" | "color" | "spriteSheetKey" | "spriteUrl" | "spriteUrls">;
type DiaryRoomHistoryEntry = NonNullable<CogSnapshot["roomHistory"]>[number];
type DiaryDebateEvent = WorldEvent & { diaryDebateLog?: DebateLogEntry };
export type DiaryEventItem = {
  actor?: DiaryCogRef;
  event: DiaryDebateEvent;
  kind: DiaryEventKind;
};
export type ManualCogChoiceAction =
  | Extract<CogAction, { type: "move" }>
  | Extract<CogAction, { type: "debate" }>
  | Extract<CogAction, { type: "chooseTactic" }>
  | Extract<CogAction, { type: "wait" }>;
export type DiaryRoomEntry = {
  id: string;
  roomId: string;
  roomLabel: string;
  enterTick: number;
  leaveTick: number | undefined;
  events: DiaryEventItem[];
  flips: WorldEvent[];
  achievements: WorldEvent[];
  debateResults: DiaryDebateEvent[];
  witnessedDebates: DiaryDebateEvent[];
  people: WorldEvent[];
  roomCogs: DiaryCogRef[];
};
export type PendingManualChoice = {
  action: ManualCogChoiceAction;
  signature: string;
  timestamp: number;
};
type AchievementProgress = {
  current: number;
  target: number;
};
type CertaintyMeter = {
  color: string;
  value: number;
};
type GameTickerItem = {
  color?: Color;
  id: string;
  kind: "achievement" | "arrival" | "conversion" | "majority";
  label?: string;
  name?: string;
  teamColor?: Color;
  tick: number;
};
type RenderRestoreState = {
  details: DetailsRestoreState[];
  focus: FocusRestoreState | undefined;
  scroll: ScrollRestoreState[];
};
type DetailsRestoreState = {
  open: boolean;
  selector: string;
};
type DescriptionRollParts = {
  archetype: string;
  detail: string;
  silhouette: string;
  prop: string;
  style: number;
};
type TextRollFrame = {
  delay: number;
  text: string;
};
type FocusRestoreState = {
  checked: boolean | undefined;
  scrollLeft: number;
  scrollTop: number;
  selectionEnd: number | null;
  selectionStart: number | null;
  selector: string;
  value: string | undefined;
};
type ScrollRestoreState = {
  index: number;
  scrollLeft: number;
  scrollTop: number;
  selector: string;
};
export type ConfigTab = "params" | "timing" | "traits" | "achievements" | "debates" | "venue";
export type ControllerLogFilterKey = "debates" | "movement";
export type ControllerLogFilters = Record<ControllerLogFilterKey, boolean>;
type TimingParameterKey = (typeof TIMING_PARAMETER_KEYS)[number];
type RosterMode = "score" | "room";

const CONVERSION_THRESHOLD = 100;
const PERSONAL_SCORE_DISPLAY_MULTIPLIER = 1000;
export const DIARY_INITIAL_ROOM_LIMIT = 6;
export const DIARY_LOAD_MORE_ROOM_COUNT = 10;
const GAME_FLOW_EVENT_LIMIT = 6;
const GAME_TICKER_ITEM_LIMIT = 12;
const GAME_TICKER_QUEUE_LIMIT = 40;
const GAME_TICKER_SCROLL_SPEED_PX_PER_SECOND = 48;
const GAME_TICKER_VISIBLE_TICKS = secondsToSimulationTicks(30);
const TEAM_COUNT_IMPACT_TICKS = legacyHalfSecondTicksToSimulationTicks(4);
const BUILDER_SPRITE_PROGRESS_MIN_MS = 1_500;
const TIMING_PARAMETER_KEYS = [
  "debatePrepTicks",
  "debateChoiceRevealTicks",
  "debateResultTicks",
  "debateCooldownTicks",
  "roomMoveCooldownTicks",
] as const;
const SCROLL_RESTORE_SELECTORS = [
  ".cog-profile-scroll",
  ".log-thread",
  ".profile-log-thread",
  ".game-flow-list",
  ".cog-roster",
  ".cog-builder-shell",
  ".builder-wizard-stage",
  ".config-page-scroll",
] as const;
const LIVE_UPDATE_STATE_KEYS = new Set<keyof HudState>([
  "connectionStatus",
  "serverStatus",
  "snapshot",
  "selectedCogId",
]);
const DEFAULT_CONTROLLER_LOG_FILTERS: ControllerLogFilters = { debates: true, movement: true };
const PROFILE_PAGE_IN_PLACE_SELECTORS = [
  ".profile-mobile-score-strip",
  ".profile-mobile-risk-strip",
  ".profile-mobile-current-strip",
  ".profile-mobile-guidance-panel",
  ".profile-mobile-achievements-panel",
  ".profile-mobile-feed-panel",
  ".profile-stat-band",
  ".profile-achievements-block",
  ".profile-diary-block",
  ".profile-controller-log",
] as const;
const staticCogSpriteUrls = new Map(
  spriteEntries()
    .filter((entry) => entry.key.startsWith("cog-"))
    .map((entry) => [entry.key, entry.spriteUrl]),
);

export class Hud {
  private state: HudState = {
    connectionStatus: "connecting",
    gameConfig: undefined,
    notice: undefined,
    selectedCogId: undefined,
    serverStatus: undefined,
    snapshot: undefined,
  };
  private readonly profileDrafts = new Map<string, CogProfileDraft>();
  private readonly diaryRoomLimits = new Map<string, number>();
  private controllerLogFilters: ControllerLogFilters = { ...DEFAULT_CONTROLLER_LOG_FILTERS };
  private profileOpen = false;
  private profilePageCogId: string | undefined;
  private builderOpen = false;
  private builderCreating = false;
  private builderGeneratingSprites = false;
  private builderSpriteError: string | undefined;
  private readonly builderSpriteGeneration = new LatestRequestGuard();
  private builderDraft = createInitialBuilderDraft();
  private builderPreviewDraft = createBuilderPreviewDraft(this.builderDraft);
  private lastBuilderDescriptionRoll: DescriptionRollParts | undefined;
  private builderRollGeneration = 0;
  private builderRollTimers: Array<ReturnType<typeof setTimeout>> = [];
  private builderTextRollStep: CogBuilderTextRollStep | undefined;
  private builderTraitRoll: CogBuilderTraitRoll | undefined;
  private builderStep: CogBuilderStep = "intro";
  private configOpen = false;
  private configTab: ConfigTab = "params";
  private venueEditorDispose: (() => void) | undefined;
  private controlsPanelOpen = false;
  private builderQrCardOpen = true;
  private rosterPanelOpen = true;
  private shortcutsPanelOpen = false;
  private rosterSettingsOpen = false;
  private rosterMode: RosterMode = "score";
  private tickerAnimationFrame: number | undefined;
  private tickerLastFrameMs: number | undefined;
  private tickerOffsetPx = 0;
  private readonly tickerItemKeys = new Set<string>();
  private tickerItems: GameTickerItem[] = [];
  private expandedRosterCogId: string | undefined;
  private pendingRosterScrollCogId: string | undefined;
  private pendingControllerLogFilterRestoreState: RenderRestoreState | undefined;
  private pointerRenderDeferralActive = false;
  private pointerRenderDeferralQueued = false;
  private pointerRenderDeferralTimer: number | undefined;
  private removePointerEndListeners: (() => void) | undefined;
  private lastChoicePress: { signature: string; timestamp: number } | undefined;
  private readonly expandedMobileFeedCogIds = new Set<string>();
  private readonly mobilePromptSuggestionSteps = new Map<string, number>();
  private readonly pendingManualChoices = new Map<string, PendingManualChoice>();

  constructor(
    private readonly element: HTMLElement,
    private readonly actions: HudActions,
  ) {
    this.element.addEventListener("pointerdown", this.handlePointerRenderDeferralStart, true);
    this.element.addEventListener("click", this.handlePointerRenderDeferralClick, true);
    this.element.addEventListener("click", this.handleDelegatedProfileClick);
    this.element.addEventListener("submit", this.handleDelegatedProfileSubmit);
  }

  update(state: Partial<HudState>): void {
    const preserveVenueEditor = this.shouldPreserveVenueEditor(state);
    const updateProfilePageInPlace = this.shouldUpdateProfilePageInPlace(state);
    if (state.selectedCogId && state.selectedCogId !== this.state.selectedCogId) {
      this.pendingRosterScrollCogId = state.selectedCogId;
    }
    this.state = {
      ...this.state,
      ...state,
    };
    if (state.snapshot) {
      this.enqueueGameTickerItems(state.snapshot);
    }
    this.prunePendingManualChoices();
    if (preserveVenueEditor) {
      return;
    }
    if (this.pointerRenderDeferralActive) {
      this.pointerRenderDeferralQueued = true;
      return;
    }
    if (updateProfilePageInPlace && this.updateOpenProfilePageInPlace()) {
      return;
    }
    this.render();
  }

  selectedCogId(): string | undefined {
    return this.state.selectedCogId;
  }

  private prunePendingManualChoices(): void {
    const snapshot = this.state.snapshot;
    if (!snapshot) {
      this.pendingManualChoices.clear();
      return;
    }

    for (const [cogId, pending] of this.pendingManualChoices) {
      const cog = snapshot.cogs.find((candidate) => candidate.id === cogId);
      const age = Date.now() - pending.timestamp;
      if (
        !cog ||
        age > 8000 ||
        (pending.action.type === "move" && Boolean(cog.moving)) ||
        (pending.action.type === "chooseTactic" && !cog.debate) ||
        (pending.action.type === "debate" && (cog.debate || cog.moving)) ||
        (pending.action.type === "wait" && shouldPrunePendingWaitChoice(pending, age))
      ) {
        this.pendingManualChoices.delete(cogId);
      }
    }
  }

  openBuilderPage(): void {
    this.builderOpen = true;
    this.profilePageCogId = undefined;
    this.configOpen = false;
    this.controlsPanelOpen = false;
    this.render();
  }

  openCogProfilePage(cogId: string): void {
    this.builderOpen = false;
    this.configOpen = false;
    this.profilePageCogId = cogId;
    this.controlsPanelOpen = false;
    this.render();
  }

  openConfigPage(): void {
    this.builderOpen = false;
    this.profilePageCogId = undefined;
    this.configOpen = true;
    this.configTab = "params";
    this.render();
  }

  toggleControlsPanel(): void {
    this.controlsPanelOpen = !this.controlsPanelOpen;
    this.render();
  }

  toggleRosterPanel(): void {
    this.rosterPanelOpen = !this.rosterPanelOpen;
    this.render();
  }

  toggleBuilderQrCard(): void {
    this.builderQrCardOpen = !this.builderQrCardOpen;
    this.render();
  }

  toggleShortcutsPanel(): void {
    this.shortcutsPanelOpen = !this.shortcutsPanelOpen;
    this.render();
  }

  render(restoreState = this.captureRenderRestoreState()): void {
    this.venueEditorDispose?.();
    this.venueEditorDispose = undefined;
    const snapshot = this.state.snapshot;
    const serverStatus = this.state.serverStatus;
    const selectedCog = snapshot?.cogs.find((cog) => cog.id === this.state.selectedCogId);
    if (this.profilePageCogId && snapshot && !snapshot.cogs.some((cog) => cog.id === this.profilePageCogId)) {
      this.profilePageCogId = undefined;
    }
    const profilePageCog = snapshot?.cogs.find((cog) => cog.id === this.profilePageCogId);
    const selectedDraft = selectedCog ? this.profileDraftFor(selectedCog) : undefined;
    const profilePage = profilePageCog && snapshot
      ? renderCogProfilePage(
          profilePageCog,
          snapshot,
          this.profileDraftFor(profilePageCog),
          this.state.gameConfig?.config,
          this.pendingManualChoices.get(profilePageCog.id),
          this.expandedMobileFeedCogIds.has(profilePageCog.id),
          this.mobilePromptSuggestionSteps.get(profilePageCog.id) ?? 0,
          this.diaryRoomLimitFor(profilePageCog.id),
          this.controllerLogFilters,
        )
      : "";
    const builderPage = this.builderOpen
      ? renderCogBuilderPage(
          this.builderDraft,
          this.builderCreating,
          this.builderGeneratingSprites,
          this.builderSpriteError,
          this.builderStep,
          this.builderTraitRoll,
          this.builderTextRollStep,
          this.builderPreviewDraft,
        )
      : "";
    const configPage = this.configOpen && this.state.gameConfig
      ? renderConfigPage(this.state.gameConfig, this.configTab, snapshot)
      : "";
    const builderQrCard = this.builderQrCardOpen && !this.builderOpen && !this.profilePageCogId && !this.configOpen
      ? renderBuilderQrCard()
      : "";
    const simulationMode = serverStatus?.simulationMode ?? "playing";
    const discoMode = serverStatus?.discoMode ?? false;
    const stopActiveClass = simulationMode === "paused" ? " is-active" : "";
    const playActiveClass = simulationMode === "playing" ? " is-active" : "";
    const stepQueuedClass = serverStatus?.stepRequested ? " is-active" : "";
    const discoActiveClass = discoMode ? " is-active" : "";
    const controlsPanelOpenClass = this.controlsPanelOpen ? " is-open" : "";
    const cogs = snapshot?.cogs ?? [];
    const teamsGauge = renderTeamsGauge(cogs, discoMode, snapshot?.recentEvents ?? [], snapshot?.tick);
    const gameTicker = renderGameTickerItems(this.tickerItems, this.tickerOffsetPx);
    const conversationLog = selectedCog?.conversationLog ?? [];
    const rosterGrouped = this.rosterMode === "room";
    const rosterSettingsOpenClass = this.rosterSettingsOpen ? " is-open" : "";
    const rosterGroupActiveClass = rosterGrouped ? " is-active" : "";
    const rosterCogs = sortedRosterCogs(cogs, this.rosterMode);
    const gameConfig = this.state.gameConfig?.config;
    const cogRows = rosterCogs
      .map((cog) =>
        renderCogRosterRow(cog, {
          discoMode,
          expandedCogId: this.expandedRosterCogId,
          gameConfig,
          selectedCogId: this.state.selectedCogId,
          snapshot,
        }),
      )
      .join("");
    const roomCogRows = this.rosterMode === "room"
      ? renderRoomRoster(cogs, snapshot, this.state.selectedCogId, this.expandedRosterCogId, gameConfig, discoMode)
      : cogRows;
    const emptyRoster = `
      <div class="cogs-empty">No cogs</div>
    `;
    const rosterPanel = this.rosterPanelOpen
      ? `
        <div class="right-panel">
          <div class="cogs-panel" aria-label="Cogs roster">
            <div class="cogs-panel-toolbar">
              <button
                aria-controls="cogs-roster-settings"
                aria-expanded="${this.rosterSettingsOpen ? "true" : "false"}"
                aria-label="Roster settings"
                class="cogs-settings-button"
                data-action="toggle-roster-settings"
                title="Roster settings"
                type="button"
              >
                <span aria-hidden="true">&#9881;</span>
              </button>
              <div class="cogs-settings-panel${rosterSettingsOpenClass}" id="cogs-roster-settings" aria-label="Roster settings">
                <button
                  aria-pressed="${rosterGrouped}"
                  class="cogs-setting-toggle${rosterGroupActiveClass}"
                  type="button"
                  data-action="toggle-roster-mode"
                >
                  <span class="cogs-setting-switch" aria-hidden="true"></span>
                  <span>Group by room</span>
                </button>
              </div>
            </div>
            <div class="cog-roster">
              ${roomCogRows || emptyRoster}
            </div>
          </div>
        </div>
      `
      : "";
    const logSections = groupLogByTick(conversationLog)
      .slice(0, 14)
      .map(renderLogSection)
      .join("");
    const emptyLog = selectedCog
      ? `<div class="log-empty">No controller messages yet.</div>`
      : `<div class="log-empty">Select a cog to inspect its controller conversation.</div>`;
    const gameFlowPanel = this.controlsPanelOpen ? renderGameFlowPanel(snapshot?.recentEvents ?? []) : "";
    const shortcutsPanel = this.shortcutsPanelOpen ? renderShortcutsPanel() : "";
    const profileOpen = this.profileOpen ? " open" : "";
    const profileSection = selectedCog && selectedDraft
      ? `
        <details class="profile-section"${profileOpen}>
          <summary>
            <span>Profile</span>
            <span>${escapeHtml(selectedCog.name)}</span>
          </summary>
          ${renderProfileEditor(selectedCog, selectedDraft, "compact")}
        </details>
      `
      : `
        <div class="profile-empty">Select a cog to edit its profile.</div>
      `;
    this.element.innerHTML = `
      <div class="top-drawer${controlsPanelOpenClass}" id="top-controls-panel" aria-label="Simulation controls">
        <div class="top-panel" aria-label="Simulation controls">
          <div class="top-sim-controls" aria-label="Playback controls">
            <button aria-label="Stop" class="control-button icon-control-button${stopActiveClass}" type="button" data-action="stop" title="Stop">
              <span aria-hidden="true">||</span>
            </button>
            <button aria-label="Play" class="control-button icon-control-button${playActiveClass}" type="button" data-action="play" title="Play">
              <span aria-hidden="true">|&gt;</span>
            </button>
            <button aria-label="Step" class="control-button icon-control-button${stepQueuedClass}" type="button" data-action="step" title="Step">
              <span aria-hidden="true">&gt;|</span>
            </button>
            ${renderLlmTimeoutMeter(serverStatus)}
          </div>
          <div class="top-actions">
            ${
              selectedCog
                ? `<button class="hud-button hud-button-secondary" type="button" data-action="open-profile-page" data-cog-id="${escapeHtml(selectedCog.id)}">Profile</button>`
                : ""
            }
            <a
              aria-label="Build cog in new window"
              class="hud-button hud-button-secondary"
              href="/builder"
              target="cogshambo-cog-builder"
              title="Build cog"
              data-action="open-builder-link"
            >Build cog</a>
            <a
              aria-label="Open settings in new window"
              class="hud-button hud-settings-link hud-button-secondary"
              href="/config"
              target="cogshambo-settings"
              title="Settings"
              data-action="open-config-window"
            ><span aria-hidden="true">&#9881;</span><span>Settings</span></a>
            <button class="hud-button hud-button-secondary" type="button" data-action="open-venue-editor-window">Venue editor</button>
            <button class="hud-button hud-button-secondary" type="button" data-action="shuffle-teams">Shuffle</button>
            <button
              aria-pressed="${discoMode ? "true" : "false"}"
              class="hud-button hud-button-secondary disco-toggle${discoActiveClass}"
              type="button"
              data-action="toggle-disco"
            >Disco</button>
            <button class="hud-button" type="button" data-action="spawn">Spawn cog</button>
            <button class="hud-button" type="button" data-action="next">Next cog</button>
          </div>
        </div>
        ${gameFlowPanel}
      </div>
      ${teamsGauge}
      ${gameTicker}
      ${renderDebateTacticLegend()}
      ${rosterPanel}
      ${profilePage}
      ${builderPage}
      ${configPage}
      ${shortcutsPanel}
      ${builderQrCard}
    `;

    this.bindBuilderEvents();
    this.bindCogSelectionEvents();
    this.bindProfileEvents();
    this.bindConfigEvents();
    this.bindSimulationEvents();
    this.mountVenueEditorTab();
    this.restoreRenderState(restoreState);
    this.scrollPendingRosterSelectionIntoView();
    this.applyTickerOffset();
    this.syncGameTickerRenderLoop();
  }

  private enqueueGameTickerItems(snapshot: WorldSnapshot): void {
    for (const item of gameTickerItems(snapshot)) {
      if (this.tickerItemKeys.has(item.id)) {
        continue;
      }
      this.tickerItems.push(item);
      this.tickerItemKeys.add(item.id);
    }

    while (this.tickerItems.length > GAME_TICKER_QUEUE_LIMIT) {
      this.tickerItems.shift();
    }
  }

  private syncGameTickerRenderLoop(): void {
    const tickerWindow = browserWindow();
    if (!tickerWindow || this.tickerItems.length === 0 || this.tickerAnimationFrame !== undefined) {
      return;
    }

    this.tickerLastFrameMs = undefined;
    this.tickerAnimationFrame = tickerWindow.requestAnimationFrame(this.advanceGameTicker);
  }

  private readonly advanceGameTicker = (timestamp: number): void => {
    const tickerWindow = browserWindow();
    if (!tickerWindow || this.tickerItems.length === 0) {
      this.tickerAnimationFrame = undefined;
      this.tickerLastFrameMs = undefined;
      return;
    }

    const elapsedMs = this.tickerLastFrameMs === undefined ? 0 : Math.min(Math.max(timestamp - this.tickerLastFrameMs, 0), 250);
    this.tickerLastFrameMs = timestamp;
    if (!prefersReducedMotion()) {
      this.tickerOffsetPx -= (elapsedMs / 1000) * GAME_TICKER_SCROLL_SPEED_PX_PER_SECOND;
      if (this.removeScrolledTickerItems()) {
        return;
      }
    }
    this.applyTickerOffset();
    this.tickerAnimationFrame = tickerWindow.requestAnimationFrame(this.advanceGameTicker);
  };

  private removeScrolledTickerItems(): boolean {
    const scrollWidth = this.tickerScrollWidthPx();
    if ((scrollWidth && this.tickerOffsetPx <= -scrollWidth) || this.tickerOffsetPx < -10000) {
      this.tickerItems = [];
      this.tickerOffsetPx = 0;
      this.tickerAnimationFrame = undefined;
      this.tickerLastFrameMs = undefined;
      this.render();
      return true;
    }

    return false;
  }

  private tickerScrollWidthPx(): number | undefined {
    const group = this.element.querySelector<HTMLElement>(".game-ticker-group");
    const track = this.element.querySelector<HTMLElement>(".game-ticker-track");
    const width = group?.offsetWidth ?? track?.scrollWidth ?? track?.offsetWidth;
    return width && Number.isFinite(width) && width > 0 ? width : undefined;
  }

  private applyTickerOffset(): void {
    const transform = `translate3d(${formatTickerOffset(this.tickerOffsetPx)}px, 0, 0)`;
    this.element.querySelectorAll<HTMLElement>(".game-ticker-track").forEach((track) => {
      track.style.transform = transform;
    });
  }

  private scrollPendingRosterSelectionIntoView(): void {
    const cogId = this.pendingRosterScrollCogId;
    if (!cogId) {
      return;
    }

    if (scrollRosterCogTowardTop(this.element, cogId)) {
      this.pendingRosterScrollCogId = undefined;
      return;
    }

    if (this.state.snapshot && !this.state.snapshot.cogs.some((cog) => cog.id === cogId)) {
      this.pendingRosterScrollCogId = undefined;
    }
  }

  private shouldPreserveVenueEditor(state: Partial<HudState>): boolean {
    return Boolean(
      this.configOpen &&
        this.configTab === "venue" &&
        Object.keys(state).length > 0 &&
        Object.keys(state).every((key) => LIVE_UPDATE_STATE_KEYS.has(key as keyof HudState)),
    );
  }

  private shouldUpdateProfilePageInPlace(state: Partial<HudState>): boolean {
    if (document.activeElement instanceof HTMLElement && document.activeElement.closest(".profile-diary-block")) {
      return false;
    }

    return Boolean(
      this.profilePageCogId &&
        Object.keys(state).length > 0 &&
        Object.keys(state).every((key) => LIVE_UPDATE_STATE_KEYS.has(key as keyof HudState)),
    );
  }

  private updateOpenProfilePageInPlace(): boolean {
    const cogId = this.profilePageCogId;
    const snapshot = this.state.snapshot;
    if (!cogId || !snapshot) {
      return false;
    }

    const cog = snapshot.cogs.find((candidate) => candidate.id === cogId);
    if (!cog) {
      return false;
    }

    const profilePage = this.element.querySelector<HTMLElement>(
      `.cog-profile-page[data-cog-id="${cssAttributeValue(cogId)}"]`,
    );
    if (!profilePage) {
      return false;
    }

    const restoreState = this.captureRenderRestoreState();
    updateCogProfilePageInPlace(
      profilePage,
      cog,
      snapshot,
      this.profileDraftFor(cog),
      this.state.gameConfig?.config,
      this.pendingManualChoices.get(cog.id),
      this.expandedMobileFeedCogIds.has(cog.id),
      this.mobilePromptSuggestionSteps.get(cog.id) ?? 0,
      this.diaryRoomLimitFor(cog.id),
      this.controllerLogFilters,
    );
    this.restoreRenderState(restoreState);
    return true;
  }

  private readonly handlePointerRenderDeferralStart = (event: PointerEvent): void => {
    if (event.button !== 0 || !isHudInteractiveTarget(event.target, this.element)) {
      return;
    }

    this.pointerRenderDeferralActive = true;
    this.clearPointerRenderDeferralTimer();
    this.removePointerEndListeners?.();

    const pointerId = event.pointerId;
    const handlePointerEnd = (endEvent: PointerEvent): void => {
      if (endEvent.pointerId !== pointerId) {
        return;
      }

      this.removePointerEndListeners?.();
      this.schedulePointerRenderDeferralRelease(120);
    };

    window.addEventListener("pointerup", handlePointerEnd, true);
    window.addEventListener("pointercancel", handlePointerEnd, true);
    this.removePointerEndListeners = () => {
      window.removeEventListener("pointerup", handlePointerEnd, true);
      window.removeEventListener("pointercancel", handlePointerEnd, true);
      this.removePointerEndListeners = undefined;
    };
  };

  private readonly handlePointerRenderDeferralClick = (event: MouseEvent): void => {
    if (!this.pointerRenderDeferralActive || !isHudInteractiveTarget(event.target, this.element)) {
      return;
    }

    this.schedulePointerRenderDeferralRelease(0);
  };

  private readonly handleDelegatedProfileClick = (event: MouseEvent): void => {
    if (event.defaultPrevented || !(event.target instanceof Element)) {
      return;
    }

    const openProfileButton = event.target.closest<HTMLButtonElement>("[data-action='open-profile-page']");
    if (openProfileButton && this.element.contains(openProfileButton)) {
      event.preventDefault();
      event.stopPropagation();
      const cogId = openProfileButton.dataset.cogId ?? this.state.selectedCogId;
      if (!cogId) {
        return;
      }

      this.controlsPanelOpen = false;
      this.profilePageCogId = cogId;
      if (cogId !== this.state.selectedCogId) {
        this.actions.onSelectCog(cogId);
      }
      this.render();
      return;
    }

    const actionsButton = event.target.closest<HTMLButtonElement>("[data-action='toggle-mobile-actions']");
    if (actionsButton && this.element.contains(actionsButton)) {
      event.preventDefault();
      this.toggleMobileActions(actionsButton);
    }
  };

  private readonly handleDelegatedProfileSubmit = (event: SubmitEvent): void => {
    void event;
  };

  private schedulePointerRenderDeferralRelease(delayMs: number): void {
    this.clearPointerRenderDeferralTimer();
    this.pointerRenderDeferralTimer = window.setTimeout(() => {
      this.pointerRenderDeferralTimer = undefined;
      this.releasePointerRenderDeferral();
    }, delayMs);
  }

  private releasePointerRenderDeferral(): void {
    if (!this.pointerRenderDeferralActive) {
      return;
    }

    this.pointerRenderDeferralActive = false;
    this.removePointerEndListeners?.();

    if (!this.pointerRenderDeferralQueued) {
      return;
    }

    this.pointerRenderDeferralQueued = false;
    this.render();
  }

  private clearPointerRenderDeferralTimer(): void {
    if (this.pointerRenderDeferralTimer === undefined) {
      return;
    }

    window.clearTimeout(this.pointerRenderDeferralTimer);
    this.pointerRenderDeferralTimer = undefined;
  }

  private forgetProfileCog(cogId: string): void {
    if (this.profilePageCogId === cogId) {
      this.profilePageCogId = undefined;
    }
    this.profileDrafts.delete(cogId);
    this.diaryRoomLimits.delete(cogId);
    this.expandedMobileFeedCogIds.delete(cogId);
    this.mobilePromptSuggestionSteps.delete(cogId);
    this.pendingManualChoices.delete(cogId);
  }

  private mountVenueEditorTab(): void {
    if (!this.configOpen || this.configTab !== "venue") {
      return;
    }

    const host = this.element.querySelector<HTMLElement>("[data-venue-editor-host]");
    if (!host) {
      return;
    }

    this.venueEditorDispose = mountVenueEditor(host, { embedded: true });
  }

  private bindCogSelectionEvents(): void {
    this.element.querySelector("[data-action='spawn']")?.addEventListener("click", () => {
      this.actions.onSpawnCog();
    });
    this.element.querySelector("[data-action='next']")?.addEventListener("click", () => {
      this.actions.onSelectNextCog();
    });
    this.element.querySelector("[data-action='shuffle-teams']")?.addEventListener("click", () => {
      this.actions.onShuffleTeams();
    });
    this.element.querySelector("[data-action='toggle-roster-settings']")?.addEventListener("click", () => {
      this.rosterSettingsOpen = !this.rosterSettingsOpen;
      this.render();
    });
    this.element.querySelector("[data-action='toggle-roster-mode']")?.addEventListener("click", () => {
      this.rosterMode = this.rosterMode === "score" ? "room" : "score";
      this.render();
    });
    this.element.querySelector("[data-action='toggle-top-controls']")?.addEventListener("click", () => {
      this.builderOpen = false;
      this.profilePageCogId = undefined;
      this.controlsPanelOpen = !this.controlsPanelOpen;
      this.render();
    });
    this.element.querySelectorAll<HTMLElement>("[data-action='select-cog']").forEach((row) => {
      row.addEventListener("click", (event) => {
        const cogId = row.dataset.cogId;
        if (!cogId) {
          return;
        }

        event.preventDefault();
        this.expandedRosterCogId = this.expandedRosterCogId === cogId ? undefined : cogId;
        this.actions.onSelectCog(cogId);
      });
    });
    this.element.querySelectorAll<HTMLButtonElement>("[data-action='select-cog-choice']").forEach((button) => {
      button.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) {
          return;
        }

        event.preventDefault();
        event.stopPropagation();
        this.submitCogChoice(button, "press");
      });
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        this.submitCogChoice(button, "click");
      });
    });
    this.element.querySelectorAll<HTMLButtonElement>("[data-action='select-cog-valid-action']").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const cogId = button.dataset.cogId ?? button.closest<HTMLElement>("[data-cog-id]")?.dataset.cogId;
        if (cogId) {
          this.actions.onSelectCog(cogId);
        }
      });
    });
    this.element.querySelectorAll<HTMLButtonElement>("[data-action='kick-cog']").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const cogId = button.dataset.cogId ?? button.closest<HTMLElement>("[data-cog-id]")?.dataset.cogId;
        if (!cogId || button.disabled) {
          return;
        }

        button.disabled = true;
        void this.actions
          .onKickCog(cogId)
          .then((kicked) => {
            if (!kicked) {
              button.disabled = false;
              return;
            }
            if (this.expandedRosterCogId === cogId) {
              this.expandedRosterCogId = undefined;
            }
            this.forgetProfileCog(cogId);
            this.render();
          })
          .catch(() => {
            button.disabled = false;
          });
      });
    });
    this.element.querySelectorAll<HTMLElement>("[data-action='open-profile-window']").forEach((link) => {
      link.addEventListener("click", (event) => {
        const cogId = link.dataset.cogId ?? link.closest<HTMLElement>("[data-cog-id]")?.dataset.cogId;
        if (!cogId) {
          return;
        }

        event.preventDefault();
        event.stopPropagation();
        this.actions.onOpenProfileWindow(cogId);
      });
    });
    this.element.querySelectorAll<HTMLButtonElement>("[data-action='open-profile-page']").forEach((button) => {
      button.addEventListener("click", (event) => {
        const cogId = button.dataset.cogId ?? this.state.selectedCogId;
        if (!cogId) {
          return;
        }

        event.preventDefault();
        this.actions.onOpenProfileWindow(cogId);
      });
    });
    this.element.querySelectorAll<HTMLButtonElement>("[data-action='abandon-cog']").forEach((button) => {
      button.addEventListener("click", () => {
        const cogId = button.dataset.cogId ?? button.closest<HTMLElement>("[data-cog-id]")?.dataset.cogId;
        if (!cogId || button.disabled) {
          return;
        }

        button.disabled = true;
        void this.actions
          .onAbandonCog(cogId)
          .then((abandoned) => {
            if (!abandoned) {
              button.disabled = false;
              return;
            }
            this.forgetProfileCog(cogId);
            this.render();
          })
          .catch(() => {
            button.disabled = false;
          });
      });
    });
  }

  private bindBuilderEvents(): void {
    this.element.querySelector("[data-action='open-builder']")?.addEventListener("click", () => {
      this.openBuilderPage();
    });
    this.element.querySelector("[data-action='close-builder']")?.addEventListener("click", () => {
        this.clearBuilderRollAnimations();
        this.actions.onCloseBuilder();
        this.builderOpen = false;
        this.builderCreating = false;
        this.builderGeneratingSprites = false;
        this.lastBuilderDescriptionRoll = undefined;
        this.builderStep = "intro";
        this.render();
    });
    this.element.querySelectorAll<HTMLButtonElement>("[data-action='builder-next']").forEach((button) => {
      button.addEventListener("click", () => {
        this.advanceBuilderStep(1);
      });
    });
    this.element.querySelectorAll<HTMLButtonElement>("[data-action='builder-back']").forEach((button) => {
      button.addEventListener("click", () => {
        this.advanceBuilderStep(-1);
      });
    });
    this.element.querySelectorAll<HTMLButtonElement>("[data-action='roll-builder-step']").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.disabled) {
          return;
        }
        this.rollBuilderStep();
      });
    });
    this.element.querySelectorAll<HTMLButtonElement>("[data-action='roll-builder-description']").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.disabled) {
          return;
        }
        this.rollBuilderDescription();
      });
    });
    this.element.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("[data-builder-field]").forEach((field) => {
      field.addEventListener("input", () => {
        const builderField = field.dataset.builderField;
        if (builderField === "name") {
          const sanitizedName = sanitizeCogForename(field.value);
          this.builderDraft.name = sanitizedName;
          if (field.value !== sanitizedName) {
            field.value = sanitizedName;
          }
        } else if (builderField === "appearance") {
          this.builderDraft.appearanceDescription = field.value.slice(0, BUILDER_APPEARANCE_MAX_LENGTH);
        } else if (builderField === "strategy") {
          this.builderDraft.behaviorPrompt = field.value.slice(0, BUILDER_STRATEGY_MAX_LENGTH);
        }
        this.updateBuilderControlsDisabled();
      });
    });
    this.element.querySelectorAll<HTMLButtonElement>("[data-action='set-builder-trait']").forEach((button) => {
      button.addEventListener("click", () => {
        const kind = button.dataset.traitKind;
        const value = button.dataset.traitValue;
        if (!kind || !value) {
          return;
        }

        this.clearBuilderRollAnimations();
        if (kind === "defensiveTrait" && isTrait(value)) {
          this.builderDraft.defensiveTrait = value;
        } else if (kind === "activeTrait" && isTrait(value)) {
          this.builderDraft.activeTrait = value;
        }
        this.render();
      });
    });
    this.element.querySelectorAll<HTMLButtonElement>("[data-action='set-builder-side']").forEach((button) => {
      button.addEventListener("click", () => {
        const color = parseBuilderColor(button.dataset.builderColor);
        if (!color) {
          return;
        }

        this.builderDraft.color = color;
        this.commitBuilderStep("side");
        this.createBuilderCogFromDraft();
      });
    });
    this.element.querySelector("[data-action='random-builder-traits']")?.addEventListener("click", () => {
      this.randomizeBuilderTraits();
    });
    this.element.querySelector("[data-action='regenerate-builder-sprites']")?.addEventListener("click", () => {
      this.builderDraft.spriteRoll += 1;
      this.builderDraft.customSpriteOpen = true;
      void this.regenerateBuilderSprites({ keepSelected: false });
    });
    this.element.querySelector<HTMLButtonElement>("[data-action='open-builder-custom-sprite']")?.addEventListener("click", () => {
      this.builderDraft.customSpriteOpen = true;
      this.render();
    });
    this.element.querySelectorAll<HTMLButtonElement>("[data-action='select-builder-sprite']").forEach((button) => {
      button.addEventListener("click", () => {
        const index = Number.parseInt(button.dataset.spriteIndex ?? "", 10);
        if (Number.isInteger(index) && this.builderDraft.sprites[index]) {
          this.builderDraft.selectedSpriteIndex = index;
          this.builderDraft.customSpriteOpen = false;
          this.render();
        }
      });
    });
    this.element.querySelector<HTMLFormElement>("[data-action='create-builder-cog']")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const form = event.currentTarget as HTMLFormElement;
      if (!form.reportValidity()) {
        return;
      }

      this.createBuilderCogFromDraft();
    });
  }

  private bindConfigEvents(): void {
    this.element.querySelector("[data-action='open-config-window']")?.addEventListener("click", (event) => {
      event.preventDefault();
      this.actions.onOpenConfigWindow();
    });
    this.element.querySelector("[data-action='open-venue-editor-window']")?.addEventListener("click", () => {
      this.actions.onOpenVenueEditorWindow();
    });
    this.element.querySelector("[data-action='close-config']")?.addEventListener("click", () => {
      this.actions.onCloseConfig();
      this.configOpen = false;
      this.render();
    });
    this.element.querySelectorAll<HTMLButtonElement>("[data-config-tab]").forEach((button) => {
      button.addEventListener("click", () => {
        const tab = button.dataset.configTab;
        if (!isConfigTab(tab)) {
          return;
        }

        this.configTab = tab;
        this.render();
      });
    });
    this.element.querySelectorAll<HTMLInputElement>("[data-config-key]").forEach((input) => {
      input.addEventListener("change", () => {
        const key = input.dataset.configKey as keyof GameConfig | undefined;
        if (!key || !Number.isFinite(input.valueAsNumber)) {
          return;
        }

        this.actions.onSaveGameConfig({ [key]: input.valueAsNumber });
      });
    });
    this.element.querySelectorAll<HTMLInputElement>("[data-config-seconds-key]").forEach((input) => {
      input.addEventListener("change", () => {
        const key = input.dataset.configSecondsKey;
        if (!isTimingParameterKey(key) || !Number.isFinite(input.valueAsNumber)) {
          return;
        }

        const parameter = this.state.gameConfig?.parameters.find((candidate) => candidate.key === key);
        this.actions.onSaveGameConfig({ [key]: secondsToTicks(input.valueAsNumber, parameter) });
      });
    });
    this.element.querySelectorAll<HTMLButtonElement>("[data-settings-preset-choice]").forEach((button) => {
      button.addEventListener("click", () => {
        const settingsDb = button.dataset.settingsPresetChoice;
        if (settingsDb) {
          this.actions.onSelectSettingsPreset(settingsDb);
        }
      });
    });
    this.element.querySelector<HTMLSelectElement>("[data-settings-preset-select]")?.addEventListener("change", (event) => {
      const settingsDb = (event.currentTarget as HTMLSelectElement).value;
      if (settingsDb) {
        this.actions.onSelectSettingsPreset(settingsDb);
      }
    });
    this.element.querySelector<HTMLFormElement>("[data-settings-preset-form]")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const input = (event.currentTarget as HTMLFormElement).elements.namedItem("settingsPresetName");
      if (!(input instanceof HTMLInputElement)) {
        return;
      }

      const name = input.value.trim();
      if (!name) {
        return;
      }

      input.value = "";
      this.actions.onCreateSettingsPreset(name);
    });
    this.element.querySelectorAll<HTMLInputElement>("[data-trait-config-key]").forEach((input) => {
      input.addEventListener("change", () => {
        const traitId = input.dataset.traitConfigId;
        const key = input.dataset.traitConfigKey;
        if (!traitId || !key || !Number.isFinite(input.valueAsNumber)) {
          return;
        }

        this.actions.onSaveGameConfig({
          traitConfig: {
            [traitId]: {
              [key]: input.valueAsNumber,
            },
          },
        } as GameConfigInput);
      });
    });
  }

  private bindProfileEvents(): void {
    const profileDetails = this.element.querySelector<HTMLDetailsElement>(".profile-section");
    profileDetails?.addEventListener("toggle", () => {
      this.profileOpen = profileDetails.open;
    });
    profileDetails?.addEventListener("focusout", () => {
      window.setTimeout(() => {
        if (!this.isProfileEditing()) {
          this.render();
        }
      }, 0);
    });
    this.element.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("[data-profile-field]").forEach((field) => {
      field.addEventListener("input", () => {
        const cogId = field.closest<HTMLElement>("[data-cog-id]")?.dataset.cogId;
        const profileField = field.dataset.profileField;
        if (!cogId) {
          return;
        }

        const draft = this.ensureDraft(cogId);
        if (profileField === "name") {
          draft.name = field.value;
        } else if (profileField === "behaviorPrompt") {
          draft.behaviorPrompt = field.value;
          this.actions.onSaveCogProfile(cogId, this.profileForSave(cogId, { includeIdentityDraft: true }));
        }
      });
    });
    this.element.querySelectorAll<HTMLInputElement>("[data-profile-attribute]").forEach((input) => {
      input.addEventListener("input", () => {
        const cogId = input.closest<HTMLElement>("[data-cog-id]")?.dataset.cogId;
        const key = input.dataset.profileAttribute;
        if (!cogId || !key) {
          return;
        }

        const draft = this.ensureDraft(cogId);
        draft.attributes[key] = Number.isFinite(input.valueAsNumber) ? input.valueAsNumber : 0;
        this.actions.onSaveCogProfile(cogId, this.profileForSave(cogId, { includeIdentityDraft: false }));
      });
    });
    this.element.querySelectorAll<HTMLButtonElement>("[data-action='set-trait']").forEach((button) => {
      button.addEventListener("click", () => {
        const cogId = button.closest<HTMLElement>("[data-cog-id]")?.dataset.cogId;
        const kind = button.dataset.traitKind;
        const value = button.dataset.traitValue;
        if (!cogId || !kind || !value) {
          return;
        }

        const draft = this.ensureDraft(cogId);
        if (kind === "defensiveTrait" && isTrait(value)) {
          draft.defensiveTrait = value;
        } else if (kind === "activeTrait" && isTrait(value)) {
          draft.activeTrait = value;
        }
        this.actions.onSaveCogProfile(cogId, this.profileForSave(cogId, { includeIdentityDraft: false }));
        this.render();
      });
    });
    this.element.querySelectorAll<HTMLButtonElement>("[data-action='remove-attribute']").forEach((button) => {
      button.addEventListener("click", () => {
        const cogId = button.closest<HTMLElement>("[data-cog-id]")?.dataset.cogId;
        const key = button.dataset.attributeKey;
        if (!cogId || !key) {
          return;
        }

        const draft = this.ensureDraft(cogId);
        delete draft.attributes[key];
        this.actions.onSaveCogProfile(cogId, this.profileForSave(cogId, { includeIdentityDraft: false }));
        this.render();
      });
    });
    this.element.querySelectorAll<HTMLButtonElement>("[data-action='add-attribute']").forEach((button) => {
      button.addEventListener("click", () => {
        const form = button.closest<HTMLFormElement>("[data-cog-id]");
        const cogId = form?.dataset.cogId;
        const keyInput = form?.querySelector<HTMLInputElement>("[data-profile-add-key]");
        const valueInput = form?.querySelector<HTMLInputElement>("[data-profile-add-value]");
        const key = keyInput?.value.trim();
        if (!cogId || !key) {
          keyInput?.focus();
          return;
        }

        const draft = this.ensureDraft(cogId);
        draft.attributes[key] = valueInput && Number.isFinite(valueInput.valueAsNumber) ? valueInput.valueAsNumber : 0;
        this.actions.onSaveCogProfile(cogId, this.profileForSave(cogId, { includeIdentityDraft: false }));
        this.render();
      });
    });
    this.element.querySelectorAll<HTMLFormElement>("[data-action='save-profile']").forEach((form) => {
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        const cogId = form.dataset.cogId;
        if (!cogId) {
          return;
        }

        (document.activeElement as HTMLElement | null)?.blur();
        this.actions.onSaveCogProfile(cogId, this.profileForSave(cogId, { includeIdentityDraft: true }));
      });
    });
    this.element.querySelectorAll<HTMLButtonElement>("[data-action='load-more-diary-rooms']").forEach((button) => {
      button.addEventListener("click", () => {
        const cogId = button.dataset.cogId ?? button.closest<HTMLElement>("[data-cog-id]")?.dataset.cogId;
        if (!cogId) {
          return;
        }

        this.diaryRoomLimits.set(cogId, this.diaryRoomLimitFor(cogId) + DIARY_LOAD_MORE_ROOM_COUNT);
        this.render();
      });
    });
    this.element.querySelectorAll<HTMLButtonElement>("[data-action='toggle-controller-log-filter']").forEach((button) => {
      const captureRestoreState = () => {
        this.pendingControllerLogFilterRestoreState = this.captureControllerLogFilterRestoreState(button);
      };
      button.addEventListener("pointerdown", captureRestoreState);
      button.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          captureRestoreState();
        }
      });
      button.addEventListener("click", () => {
        const filter = button.dataset.controllerLogFilter;
        if (!isControllerLogFilterKey(filter)) {
          return;
        }

        const restoreState = this.pendingControllerLogFilterRestoreState ??
          this.captureControllerLogFilterRestoreState(button);
        this.pendingControllerLogFilterRestoreState = undefined;
        this.controllerLogFilters = {
          ...this.controllerLogFilters,
          [filter]: !this.controllerLogFilters[filter],
        };
        this.render(restoreState);
      });
    });
    this.element.querySelectorAll<HTMLButtonElement>("[data-action='poke-cog']").forEach((button) => {
      button.addEventListener("click", () => {
        const cogId = button.dataset.cogId ?? button.closest<HTMLElement>("[data-cog-id]")?.dataset.cogId;
        if (!cogId || button.disabled) {
          return;
        }

        button.disabled = true;
        void this.actions.onPokeCog(cogId).then((ok) => {
          if (!ok) {
            button.disabled = false;
          }
        });
      });
    });
    this.element.querySelectorAll<HTMLFormElement>("[data-action='submit-cog-prompt']").forEach((form) => {
      form.addEventListener("submit", (event) => {
        if (event.defaultPrevented) {
          return;
        }
        event.preventDefault();
        this.submitCogPrompt(form);
      });
    });
    this.element.querySelectorAll<HTMLButtonElement>("[data-action='fill-cog-prompt']").forEach((button) => {
      button.addEventListener("click", (event) => {
        if (event.defaultPrevented) {
          return;
        }
        event.preventDefault();
        this.fillCogPrompt(button);
      });
    });
    this.element.querySelectorAll<HTMLButtonElement>("[data-action='toggle-mobile-actions']").forEach((button) => {
      button.addEventListener("click", (event) => {
        if (event.defaultPrevented) {
          return;
        }
        event.preventDefault();
        this.toggleMobileActions(button);
      });
    });
  }

  private toggleMobileActions(button: HTMLButtonElement): void {
    const cogId = button.dataset.cogId;
    if (!cogId) {
      return;
    }

    if (this.expandedMobileFeedCogIds.has(cogId)) {
      this.expandedMobileFeedCogIds.delete(cogId);
    } else {
      this.expandedMobileFeedCogIds.add(cogId);
    }
    this.render();
  }

  private submitCogChoice(button: HTMLButtonElement, source: "click" | "press"): void {
    const cogId = button.dataset.cogId ?? button.closest<HTMLElement>("[data-cog-id]")?.dataset.cogId;
    if (!cogId) {
      return;
    }

    const action = rosterChoiceAction(button);
    if (!action) {
      return;
    }

    const signature = manualChoiceSignature(cogId, action);
    const now = Date.now();
    if (
      source === "click" &&
      this.lastChoicePress?.signature === signature &&
      now - this.lastChoicePress.timestamp < 800
    ) {
      return;
    }

    this.lastChoicePress = { signature, timestamp: now };
    this.pendingManualChoices.set(cogId, { action, signature, timestamp: now });
    button.classList.add("is-pressed");
    this.expandedRosterCogId = undefined;
    this.actions.onSelectCogChoice(cogId, action);
    this.render();
  }

  private bindSimulationEvents(): void {
    this.element.querySelector("[data-action='stop']")?.addEventListener("click", () => {
      this.actions.onStop();
    });
    this.element.querySelector("[data-action='play']")?.addEventListener("click", () => {
      this.actions.onPlay();
    });
    this.element.querySelector("[data-action='step']")?.addEventListener("click", () => {
      this.actions.onStep();
    });
    this.element.querySelector("[data-action='toggle-disco']")?.addEventListener("click", () => {
      this.actions.onToggleDisco();
    });
    this.element
      .querySelectorAll("[data-action='open-builder-window'], [data-action='open-builder-link']")
      .forEach((button) => {
        button.addEventListener("click", (event) => {
          event.preventDefault();
          this.actions.onOpenBuilderWindow();
        });
      });
  }

  private captureRenderRestoreState(): RenderRestoreState {
    return {
      details: this.captureDetailsState(),
      focus: this.captureFocusState(),
      scroll: this.captureScrollState(),
    };
  }

  private captureControllerLogFilterRestoreState(button: HTMLElement): RenderRestoreState {
    const state = this.captureRenderRestoreState();
    const selector = focusRestoreSelector(button);
    if (!selector) {
      return state;
    }

    return {
      ...state,
      focus: {
        checked: undefined,
        scrollLeft: button.scrollLeft,
        scrollTop: button.scrollTop,
        selectionEnd: null,
        selectionStart: null,
        selector,
        value: undefined,
      },
    };
  }

  private captureFocusState(): FocusRestoreState | undefined {
    const activeElement = document.activeElement;
    if (!(activeElement instanceof HTMLElement) || !this.element.contains(activeElement)) {
      return undefined;
    }

    const selector = focusRestoreSelector(activeElement);
    if (!selector) {
      return undefined;
    }

    const value = activeElement instanceof HTMLInputElement ||
      activeElement instanceof HTMLTextAreaElement ||
      activeElement instanceof HTMLSelectElement
      ? activeElement.value
      : undefined;
    const checked = activeElement instanceof HTMLInputElement && isCheckableInput(activeElement)
      ? activeElement.checked
      : undefined;
    const selectionStart = activeElement instanceof HTMLInputElement || activeElement instanceof HTMLTextAreaElement
      ? activeElement.selectionStart
      : null;
    const selectionEnd = activeElement instanceof HTMLInputElement || activeElement instanceof HTMLTextAreaElement
      ? activeElement.selectionEnd
      : null;

    return {
      checked,
      scrollLeft: activeElement.scrollLeft,
      scrollTop: activeElement.scrollTop,
      selectionEnd,
      selectionStart,
      selector,
      value,
    };
  }

  private captureScrollState(): ScrollRestoreState[] {
    return SCROLL_RESTORE_SELECTORS.flatMap((selector) =>
      Array.from(this.element.querySelectorAll<HTMLElement>(selector)).map((element, index) => ({
        index,
        scrollLeft: element.scrollLeft,
        scrollTop: element.scrollTop,
        selector,
      })),
    );
  }

  private captureDetailsState(): DetailsRestoreState[] {
    return Array.from(this.element.querySelectorAll<HTMLDetailsElement>("details")).flatMap((element) => {
      const selector = detailsRestoreSelector(element);
      return selector ? [{ open: element.open, selector }] : [];
    });
  }

  private restoreRenderState(state: RenderRestoreState): void {
    for (const detailsState of state.details) {
      const element = this.element.querySelector<HTMLDetailsElement>(detailsState.selector);
      if (element) {
        if (element.matches(".profile-diary-room-entry[data-current-room='true']")) {
          element.open = true;
          continue;
        }
        element.open = detailsState.open;
      }
    }

    this.restoreScrollState(state.scroll);

    const focusState = state.focus;
    if (!focusState) {
      return;
    }

    const element = this.element.querySelector<HTMLElement>(focusState.selector);
    if (!element) {
      return;
    }

    if (
      (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement) &&
      focusState.value !== undefined
    ) {
      element.value = focusState.value;
    }
    if (element instanceof HTMLInputElement && focusState.checked !== undefined) {
      element.checked = focusState.checked;
    }
    element.focus({ preventScroll: true });
    if (
      (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) &&
      focusState.selectionStart !== null &&
      focusState.selectionEnd !== null
    ) {
      element.setSelectionRange(focusState.selectionStart, focusState.selectionEnd);
    }
    element.scrollLeft = focusState.scrollLeft;
    element.scrollTop = focusState.scrollTop;
    this.restoreScrollState(state.scroll);
  }

  private restoreScrollState(scrollState: ScrollRestoreState[]): void {
    for (const item of scrollState) {
      const element = this.element.querySelectorAll<HTMLElement>(item.selector)[item.index];
      if (element) {
        element.scrollLeft = item.scrollLeft;
        element.scrollTop = item.scrollTop;
      }
    }
  }

  private profileDraftFor(cog: NonNullable<WorldSnapshot["cogs"][number]>): CogProfileDraft {
    const existing = this.profileDrafts.get(cog.id);
    if (existing) {
      return existing;
    }

    const draft = {
      name: cog.name,
      behaviorPrompt: cog.behaviorPrompt ?? "",
      attributes: { ...cog.attributes },
      defensiveTrait: cog.defensiveTrait,
      activeTrait: cog.activeTrait,
    };
    this.profileDrafts.set(cog.id, draft);
    return draft;
  }

  private diaryRoomLimitFor(cogId: string): number {
    return this.diaryRoomLimits.get(cogId) ?? DIARY_INITIAL_ROOM_LIMIT;
  }

  private ensureDraft(cogId: string): CogProfileDraft {
    const existing = this.profileDrafts.get(cogId);
    if (existing) {
      return existing;
    }

    const cog = this.state.snapshot?.cogs.find((candidate) => candidate.id === cogId);
    const draft = {
      name: cog?.name ?? "Cog",
      behaviorPrompt: cog?.behaviorPrompt ?? "",
      attributes: { ...(cog?.attributes ?? {}) },
      defensiveTrait: cog?.defensiveTrait ?? "stubborn",
      activeTrait: cog?.activeTrait ?? "forceful",
    };
    this.profileDrafts.set(cogId, draft);
    return draft;
  }

  private profileForSave(cogId: string, options: { includeIdentityDraft: boolean }): CogProfileUpdate {
    const draft = this.ensureDraft(cogId);
    const savedCog = this.state.snapshot?.cogs.find((candidate) => candidate.id === cogId);

    return {
      name: options.includeIdentityDraft ? draft.name : savedCog?.name ?? draft.name,
      behaviorPrompt: options.includeIdentityDraft ? draft.behaviorPrompt : savedCog?.behaviorPrompt ?? draft.behaviorPrompt,
      attributes: { ...draft.attributes },
      defensiveTrait: savedCog?.defensiveTrait === "zealot" ? "zealot" : draft.defensiveTrait,
      activeTrait: draft.activeTrait,
    };
  }

  private isProfileEditing(): boolean {
    const activeElement = document.activeElement;
    return activeElement instanceof HTMLElement && Boolean(activeElement.closest(".profile-section, .cog-profile-page, .cog-builder-page"));
  }

  private randomizeBuilderTraits(): void {
    this.clearBuilderRollAnimations();
    this.builderDraft.defensiveTrait = randomItem(traits);
    this.builderDraft.activeTrait = randomItem(traits);
    this.render();
  }

  private rollBuilderStep(): void {
    switch (this.builderStep) {
      case "name":
        this.animateBuilderTextRoll("name", rollCogName(this.state.snapshot?.cogs.map((cog) => cog.name) ?? []));
        return;
      case "appearance":
        {
          const roll = rollCogDescription(this.lastBuilderDescriptionRoll);
          this.lastBuilderDescriptionRoll = roll.parts;
          this.animateBuilderTextRoll("appearance", roll.text);
        }
        return;
      case "strategy":
        this.animateBuilderTextRoll("strategy", rollCogStrategy());
        return;
      case "defensiveTrait":
        this.animateBuilderTraitRoll("defensiveTrait", traits);
        return;
      case "activeTrait":
        this.animateBuilderTraitRoll("activeTrait", traits);
        return;
      case "side":
      case "intro":
        return;
    }
  }

  private rollBuilderDescription(): void {
    const roll = rollCogDescription(this.lastBuilderDescriptionRoll);
    this.lastBuilderDescriptionRoll = roll.parts;
    this.animateBuilderTextRoll("appearance", roll.text);
  }

  private animateBuilderTextRoll(field: CogBuilderTextRollStep, finalText: string): void {
    this.clearBuilderRollAnimations();
    const frames = typedTextFrames(finalText, field);
    let frameIndex = 0;
    const rollGeneration = this.builderRollGeneration;
    this.builderTextRollStep = field;

    const applyFrame = () => {
      if (rollGeneration !== this.builderRollGeneration) {
        return;
      }

      const frame = frames[frameIndex] ?? { delay: 0, text: finalText };
      if (field === "name") {
        this.builderDraft.name = sanitizeCogForename(frame.text);
      } else if (field === "appearance") {
        this.builderDraft.appearanceDescription = frame.text;
      } else {
        this.builderDraft.behaviorPrompt = frame.text;
      }

      frameIndex += 1;
      if (frameIndex >= frames.length) {
        if (field === "name") {
          this.builderDraft.name = sanitizeCogForename(finalText);
        } else if (field === "appearance") {
          this.builderDraft.appearanceDescription = finalText;
        } else {
          this.builderDraft.behaviorPrompt = finalText;
        }
        this.finishBuilderRollAnimation();
        this.render();
        return;
      }

      this.render();
      this.queueBuilderRollTimer(applyFrame, frame.delay);
    };

    applyFrame();
  }

  private animateBuilderTraitRoll<T extends string>(kind: CogBuilderTraitKind, values: readonly T[]): void {
    this.clearBuilderRollAnimations();
    this.clearBuilderTrait(kind);
    const finalValue = randomItem(values);
    const frames = arcadeTraitFrames(values, finalValue);
    let frameIndex = 0;
    const rollGeneration = this.builderRollGeneration;

    const applyFrame = () => {
      if (rollGeneration !== this.builderRollGeneration) {
        return;
      }

      const value = frames[frameIndex] ?? finalValue;
      this.builderTraitRoll = { kind, value };
      frameIndex += 1;

      if (frameIndex >= frames.length) {
        this.render();
        this.queueBuilderRollTimer(() => {
          if (rollGeneration !== this.builderRollGeneration) {
            return;
          }
          this.setBuilderTrait(kind, finalValue);
          this.finishBuilderRollAnimation();
          this.render();
        }, arcadeTraitLandingDelay());
        return;
      }

      this.render();
      this.queueBuilderRollTimer(applyFrame, arcadeTraitDelay(frameIndex, frames.length));
    };

    applyFrame();
  }

  private setBuilderTrait(kind: CogBuilderTraitKind, value: string): void {
    if (kind === "defensiveTrait" && isTrait(value)) {
      this.builderDraft.defensiveTrait = value;
    } else if (kind === "activeTrait" && isTrait(value)) {
      this.builderDraft.activeTrait = value;
    }
  }

  private clearBuilderTrait(kind: CogBuilderTraitKind): void {
    if (kind === "defensiveTrait") {
      this.builderDraft.defensiveTrait = undefined;
    } else {
      this.builderDraft.activeTrait = undefined;
    }
  }

  private queueBuilderRollTimer(callback: () => void, delay: number): void {
    const timer = setTimeout(callback, delay);
    this.builderRollTimers.push(timer);
  }

  private clearBuilderRollAnimations(): void {
    for (const timer of this.builderRollTimers) {
      clearTimeout(timer);
    }
    this.builderRollGeneration += 1;
    this.builderRollTimers = [];
    this.builderTextRollStep = undefined;
    this.builderTraitRoll = undefined;
  }

  private finishBuilderRollAnimation(): void {
    for (const timer of this.builderRollTimers) {
      clearTimeout(timer);
    }
    this.builderRollGeneration += 1;
    this.builderRollTimers = [];
    this.builderTextRollStep = undefined;
    this.builderTraitRoll = undefined;
  }

  private createBuilderCogFromDraft(): void {
    if (this.builderCreating) {
      return;
    }

    const request = this.builderRequest();
    if (!request) {
      this.render();
      return;
    }

    this.builderCreating = true;
    this.render();
    void this.actions
      .onCreateCog(request)
      .then((cogId) => {
        if (cogId) {
          this.builderOpen = false;
          this.profilePageCogId = cogId;
          this.builderDraft = createInitialBuilderDraft();
          this.builderPreviewDraft = createBuilderPreviewDraft(this.builderDraft);
          this.builderSpriteError = undefined;
          this.clearBuilderRollAnimations();
          this.lastBuilderDescriptionRoll = undefined;
          this.builderStep = "intro";
        }
      })
      .catch(() => {
        // The caller owns user-facing error notices; this keeps the builder usable on unexpected failures.
      })
      .finally(() => {
        this.builderCreating = false;
        this.render();
      });
  }

  private advanceBuilderStep(offset: -1 | 1): void {
    if (offset > 0 && !this.canAdvanceBuilderStep()) {
      return;
    }

    this.clearBuilderRollAnimations();
    if (offset > 0) {
      this.commitBuilderStep(this.builderStep);
    }
    const currentIndex = cogBuilderSteps.indexOf(this.builderStep);
    const nextIndex = Math.min(Math.max(currentIndex + offset, 0), cogBuilderSteps.length - 1);
    this.builderStep = cogBuilderSteps[nextIndex] ?? "intro";
    this.render();
  }

  private commitBuilderStep(step: CogBuilderStep): void {
    switch (step) {
      case "name":
        this.builderPreviewDraft.name = sanitizeCogForename(this.builderDraft.name);
        return;
      case "appearance":
        this.builderPreviewDraft.appearanceDescription = this.builderDraft.appearanceDescription;
        this.builderPreviewDraft.sprites = this.builderDraft.sprites;
        this.builderPreviewDraft.selectedSpriteIndex = this.builderDraft.selectedSpriteIndex;
        return;
      case "defensiveTrait":
        this.builderPreviewDraft.defensiveTrait = this.builderDraft.defensiveTrait;
        return;
      case "activeTrait":
        this.builderPreviewDraft.activeTrait = this.builderDraft.activeTrait;
        return;
      case "strategy":
        this.builderPreviewDraft.behaviorPrompt = this.builderDraft.behaviorPrompt;
        return;
      case "side":
        this.builderPreviewDraft.color = this.builderDraft.color;
        return;
      case "intro":
        return;
    }
  }

  private updateBuilderControlsDisabled(): void {
    const nextButton = this.element.querySelector<HTMLButtonElement>("[data-action='builder-next']");
    if (nextButton) {
      nextButton.disabled = !this.canAdvanceBuilderStep() || this.builderGeneratingSprites;
    }
    const generateButton = this.element.querySelector<HTMLButtonElement>("[data-action='regenerate-builder-sprites']");
    if (generateButton) {
      generateButton.disabled = !this.builderSpriteRequest() || this.builderGeneratingSprites || Boolean(this.builderTextRollStep);
    }
  }

  private canAdvanceBuilderStep(): boolean {
    if (this.builderTextRollStep || this.builderTraitRoll) {
      return false;
    }

    const selectedSprite = this.builderDraft.sprites[this.builderDraft.selectedSpriteIndex] ?? this.builderDraft.sprites[0];
    switch (this.builderStep) {
      case "name":
        return sanitizeCogForename(this.builderDraft.name).length > 0;
      case "appearance":
        return Boolean(selectedSprite);
      case "defensiveTrait":
        return Boolean(this.builderDraft.defensiveTrait);
      case "activeTrait":
        return Boolean(this.builderDraft.activeTrait);
      case "strategy":
        return (
          this.builderDraft.behaviorPrompt.trim().length > 0 &&
          this.builderDraft.behaviorPrompt.trim().length <= BUILDER_STRATEGY_MAX_LENGTH
        );
      case "side":
        return (
          Boolean(selectedSprite) &&
          sanitizeCogForename(this.builderDraft.name).length > 0 &&
          this.builderDraft.behaviorPrompt.trim().length > 0 &&
          this.builderDraft.behaviorPrompt.trim().length <= BUILDER_STRATEGY_MAX_LENGTH &&
          Boolean(this.builderDraft.defensiveTrait && this.builderDraft.activeTrait && this.builderDraft.color)
        );
      default:
        return true;
    }
  }

  private async regenerateBuilderSprites(options: { keepSelected: boolean }): Promise<void> {
    const request = this.builderSpriteRequest();
    if (!request) {
      return;
    }

    const generationId = this.builderSpriteGeneration.next();
    const selectedKey = this.builderDraft.sprites[this.builderDraft.selectedSpriteIndex]?.key;
    this.builderSpriteError = undefined;
    this.builderGeneratingSprites = true;
    this.render();
    let generationError: string | undefined;
    const [artGenSprites] = await Promise.all([
      this.actions.onGenerateCogSprites(request).catch((error: unknown) => {
        generationError = compactBuilderError(error);
        return undefined;
      }),
      delay(BUILDER_SPRITE_PROGRESS_MIN_MS),
    ]);
    if (!this.builderSpriteGeneration.isCurrent(generationId)) {
      return;
    }

    this.builderGeneratingSprites = false;
    if (artGenSprites?.length) {
      this.builderDraft.sprites = artGenSprites;
    } else {
      this.builderSpriteError = generationError ?? "Avatar generation unavailable. Try again.";
    }

    const selectedIndex = options.keepSelected
      ? this.builderDraft.sprites.findIndex((sprite) => sprite.key === selectedKey)
      : -1;
    this.builderDraft.selectedSpriteIndex = selectedIndex >= 0 ? selectedIndex : 0;
    this.render();
  }

  private builderSpriteRequest(): CogBuilderSpriteRequest | undefined {
    const { activeTrait, defensiveTrait } = this.builderDraft;
    if (!activeTrait || !defensiveTrait) {
      return undefined;
    }

    return {
      name: sanitizeCogForename(this.builderDraft.name),
      description: this.builderDraft.appearanceDescription.trim(),
      defensiveTrait,
      activeTrait,
      spriteRoll: this.builderDraft.spriteRoll,
      count: 1,
    };
  }

  private builderRequest(): CogBuilderCreateRequest | undefined {
    const name = sanitizeCogForename(this.builderDraft.name);
    const behaviorPrompt = this.builderDraft.behaviorPrompt.trim();
    const { activeTrait, defensiveTrait, color } = this.builderDraft;
    const sprite = this.builderDraft.sprites[this.builderDraft.selectedSpriteIndex];
    if (
      !name ||
      !behaviorPrompt ||
      !sprite ||
      !activeTrait ||
      !defensiveTrait ||
      !color
    ) {
      return undefined;
    }

    return {
      name,
      behaviorPrompt,
      attributes: { ...this.builderDraft.attributes },
      defensiveTrait,
      activeTrait,
      color,
      spriteSheetKey: sprite.key,
      spriteUrl: sprite.url,
      spriteUrls: sprite.spriteUrls,
    };
  }
}

function updateCogProfilePageInPlace(
  profilePage: HTMLElement,
  cog: CogSnapshot,
  snapshot: WorldSnapshot,
  draft: CogProfileDraft,
  gameConfig: GameConfig | undefined,
  pendingChoice: PendingManualChoice | undefined,
  mobileFeedExpanded: boolean,
  mobilePromptSuggestionStep: number,
  diaryVisibleRoomCount: number,
  controllerLogFilters: ControllerLogFilters,
): void {
  const nextProfilePage = renderProfilePageElement(
    cog,
    snapshot,
    draft,
    gameConfig,
    pendingChoice,
    mobileFeedExpanded,
    mobilePromptSuggestionStep,
    diaryVisibleRoomCount,
    controllerLogFilters,
  );
  if (!nextProfilePage) {
    return;
  }

  syncAttribute(profilePage, nextProfilePage, "aria-label");
  syncProfileHero(profilePage, nextProfilePage);
  for (const selector of PROFILE_PAGE_IN_PLACE_SELECTORS) {
    replaceProfilePagePart(profilePage, nextProfilePage, selector);
  }
}

function renderProfilePageElement(
  cog: CogSnapshot,
  snapshot: WorldSnapshot,
  draft: CogProfileDraft,
  gameConfig?: GameConfig,
  pendingChoice?: PendingManualChoice,
  mobileFeedExpanded = false,
  mobilePromptSuggestionStep = 0,
  diaryVisibleRoomCount = DIARY_INITIAL_ROOM_LIMIT,
  controllerLogFilters: ControllerLogFilters = DEFAULT_CONTROLLER_LOG_FILTERS,
): HTMLElement | undefined {
  const template = document.createElement("template");
  template.innerHTML = renderCogProfilePage(
    cog,
    snapshot,
    draft,
    gameConfig,
    pendingChoice,
    mobileFeedExpanded,
    mobilePromptSuggestionStep,
    diaryVisibleRoomCount,
    controllerLogFilters,
  ).trim();
  return template.content.querySelector<HTMLElement>(".cog-profile-page") ?? undefined;
}

function syncProfileHero(profilePage: HTMLElement, nextProfilePage: HTMLElement): void {
  const hero = profilePage.querySelector<HTMLElement>(".profile-hero");
  const nextHero = nextProfilePage.querySelector<HTMLElement>(".profile-hero");
  if (!hero || !nextHero) {
    return;
  }

  syncAttribute(hero, nextHero, "data-color");
  replaceProfilePagePart(hero, nextHero, ".profile-avatar");
  replaceProfilePagePart(hero, nextHero, ".profile-title-block");
  replaceProfilePagePart(hero, nextHero, ".profile-hero-prompt");
}

function replaceProfilePagePart(currentRoot: ParentNode, nextRoot: ParentNode, selector: string): void {
  const current = currentRoot.querySelector<HTMLElement>(selector);
  const next = nextRoot.querySelector<HTMLElement>(selector);
  if (!current || !next || containsActiveElement(current)) {
    return;
  }

  current.replaceWith(next);
}

function containsActiveElement(element: HTMLElement): boolean {
  const activeElement = document.activeElement;
  return activeElement instanceof Node && element.contains(activeElement);
}

function syncAttribute(current: HTMLElement, next: HTMLElement, name: string): void {
  const nextValue = next.getAttribute(name);
  if (nextValue === null) {
    current.removeAttribute(name);
    return;
  }

  current.setAttribute(name, nextValue);
}

export class LatestRequestGuard {
  private currentId = 0;

  next(): number {
    this.currentId += 1;
    return this.currentId;
  }

  isCurrent(id: number): boolean {
    return id === this.currentId;
  }
}

function compactBuilderError(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message.length > 140 ? `${error.message.slice(0, 137)}...` : error.message;
  }

  return "Avatar generation unavailable. Try again.";
}

function focusRestoreSelector(element: HTMLElement): string | undefined {
  if (element.dataset.builderField) {
    return `[data-builder-field="${cssAttributeValue(element.dataset.builderField)}"]`;
  }
  if (element.dataset.configKey) {
    return `[data-config-key="${cssAttributeValue(element.dataset.configKey)}"]`;
  }
  if (element.dataset.configSecondsKey) {
    return `[data-config-seconds-key="${cssAttributeValue(element.dataset.configSecondsKey)}"]`;
  }
  if (element.dataset.traitConfigId && element.dataset.traitConfigKey) {
    return [
      `[data-trait-config-id="${cssAttributeValue(element.dataset.traitConfigId)}"]`,
      `[data-trait-config-key="${cssAttributeValue(element.dataset.traitConfigKey)}"]`,
    ].join("");
  }
  if (element.dataset.settingsPresetChoice) {
    return `[data-settings-preset-choice="${cssAttributeValue(element.dataset.settingsPresetChoice)}"]`;
  }
  if (element.hasAttribute("data-settings-preset-name")) {
    return "[data-settings-preset-name]";
  }
  if (element.dataset.configTab) {
    return `[data-config-tab="${cssAttributeValue(element.dataset.configTab)}"]`;
  }
  if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement) {
    const controlSelector = genericControlFocusRestoreSelector(element);
    if (controlSelector) {
      return controlSelector;
    }
  }

  const actionSelector = actionFocusRestoreSelector(element);
  if (actionSelector) {
    return actionSelector;
  }

  const cogId = element.closest<HTMLElement>("[data-cog-id]")?.dataset.cogId;
  if (!cogId) {
    return undefined;
  }

  const cogScope = profileFocusScope(element, cogId);
  if (element.dataset.profileField) {
    return `${cogScope} [data-profile-field="${cssAttributeValue(element.dataset.profileField)}"]`;
  }
  if (element.dataset.profileAttribute) {
    return `${cogScope} [data-profile-attribute="${cssAttributeValue(element.dataset.profileAttribute)}"]`;
  }
  if (element.hasAttribute("data-profile-add-key")) {
    return `${cogScope} [data-profile-add-key]`;
  }
  if (element.hasAttribute("data-profile-add-value")) {
    return `${cogScope} [data-profile-add-value]`;
  }

  return undefined;
}

function genericControlFocusRestoreSelector(
  element: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement,
): string | undefined {
  if (element.id) {
    return `#${cssIdentifier(element.id)}`;
  }

  if (element.name) {
    const scope = controlFocusScope(element);
    const selector = `[name="${cssAttributeValue(element.name)}"]`;
    return scope ? `${scope} ${selector}` : selector;
  }

  const ariaLabel = element.getAttribute("aria-label");
  if (ariaLabel) {
    const scope = controlFocusScope(element);
    const selector = `[aria-label="${cssAttributeValue(ariaLabel)}"]`;
    return scope ? `${scope} ${selector}` : selector;
  }

  return undefined;
}

function controlFocusScope(element: HTMLElement): string | undefined {
  if (element.closest(".config-page")) {
    return ".config-page";
  }
  if (element.closest(".cog-builder-page")) {
    return ".cog-builder-page";
  }
  const cogId = element.closest<HTMLElement>("[data-cog-id]")?.dataset.cogId;
  return cogId ? profileFocusScope(element, cogId) : undefined;
}

function isCheckableInput(element: HTMLInputElement): boolean {
  return element.type === "checkbox" || element.type === "radio";
}

function isHudInteractiveTarget(target: EventTarget | null, root: HTMLElement): boolean {
  if (!(target instanceof Element) || !root.contains(target)) {
    return false;
  }

  return Boolean(target.closest("button, a[href], input, textarea, select, summary, details, [role='button'], [tabindex]"));
}

function actionFocusRestoreSelector(element: HTMLElement): string | undefined {
  if (element.closest(".profile-mobile-controller")) {
    return undefined;
  }

  const action = element.dataset.action;
  if (!action) {
    return undefined;
  }

  let selector = `[data-action="${cssAttributeValue(action)}"]`;
  selector += datasetSelectorPart("cog-id", element.dataset.cogId);
  selector += datasetSelectorPart("trait-kind", element.dataset.traitKind);
  selector += datasetSelectorPart("trait-value", element.dataset.traitValue);
  selector += datasetSelectorPart("builder-color", element.dataset.builderColor);
  selector += datasetSelectorPart("attribute-key", element.dataset.attributeKey);
  selector += datasetSelectorPart("sprite-index", element.dataset.spriteIndex);
  selector += datasetSelectorPart("choice-kind", element.dataset.choiceKind);
  selector += datasetSelectorPart("room-id", element.dataset.roomId);
  selector += datasetSelectorPart("target-id", element.dataset.targetId);
  selector += datasetSelectorPart("tactic", element.dataset.tactic);
  selector += datasetSelectorPart("intent", element.dataset.intent);
  selector += datasetSelectorPart("controller-log-filter", element.dataset.controllerLogFilter);

  const scope = actionFocusScope(element);
  return scope ? `${scope} ${selector}` : selector;
}

function actionFocusScope(element: HTMLElement): string | undefined {
  if (element.closest(".cog-builder-page")) {
    return ".cog-builder-page";
  }

  const cogId = element.closest<HTMLElement>("[data-cog-id]")?.dataset.cogId;
  if (!cogId || element.dataset.cogId) {
    return undefined;
  }

  return profileFocusScope(element, cogId);
}

function rosterChoiceAction(button: HTMLButtonElement): ManualCogChoiceAction | undefined {
  if (button.dataset.choiceKind === "room" && button.dataset.roomId) {
    return { type: "move", roomId: button.dataset.roomId };
  }

  if (button.dataset.choiceKind === "target" && button.dataset.targetId) {
    return {
      type: "debate",
      targetId: button.dataset.targetId,
      intent: `player steer: talk to ${button.dataset.targetLabel || "selected cog"}`,
    };
  }

  if (button.dataset.choiceKind === "tactic" && isDebateTactic(button.dataset.tactic)) {
    return { type: "chooseTactic", tactic: button.dataset.tactic, intent: `player steer: argue with ${button.dataset.tactic}` };
  }

  if (button.dataset.choiceKind === "intent" && button.dataset.intent) {
    return { type: "wait", intent: button.dataset.intent };
  }

  return undefined;
}

function manualChoiceSignature(cogId: string, action: ManualCogChoiceAction): string {
  if (action.type === "move") {
    return `${cogId}:move:${action.roomId}`;
  }

  if (action.type === "debate") {
    return `${cogId}:target:${action.targetId}`;
  }

  if (action.type === "chooseTactic") {
    return `${cogId}:tactic:${action.tactic}`;
  }

  return `${cogId}:intent:${action.intent ?? "wait"}`;
}

function rosterChoiceSignature(cogId: string, choice: RosterChoice): string {
  if (choice.kind === "room") {
    return manualChoiceSignature(cogId, { type: "move", roomId: choice.roomId });
  }

  if (choice.kind === "target") {
    return manualChoiceSignature(cogId, { type: "debate", targetId: choice.targetId });
  }

  return manualChoiceSignature(cogId, { type: "chooseTactic", tactic: choice.tactic });
}

function isDebateTactic(value: string | undefined): value is DebateTactic {
  return value === "reason" || value === "spin" || value === "passion";
}

function datasetSelectorPart(name: string, value: string | undefined): string {
  return value ? `[data-${name}="${cssAttributeValue(value)}"]` : "";
}

function isConfigTab(value: string | undefined): value is ConfigTab {
  return (
    value === "params" ||
    value === "timing" ||
    value === "traits" ||
    value === "achievements" ||
    value === "debates" ||
    value === "venue"
  );
}

function detailsRestoreSelector(element: HTMLDetailsElement): string | undefined {
  if (element.classList.contains("profile-section")) {
    return ".profile-section";
  }
  if (element.classList.contains("profile-controller-log")) {
    const profilePage = element.closest<HTMLElement>(".cog-profile-page[data-cog-id]");
    const profileCogId = profilePage?.dataset.cogId;
    return profileCogId
      ? `.cog-profile-page[data-cog-id="${cssAttributeValue(profileCogId)}"] .profile-controller-log`
      : ".profile-controller-log";
  }

  const diaryEntryId = element.dataset.diaryEntryId;
  if (diaryEntryId) {
    const profilePage = element.closest<HTMLElement>(".cog-profile-page[data-cog-id]");
    const profileCogId = profilePage?.dataset.cogId;
    return profileCogId
      ? `.cog-profile-page[data-cog-id="${cssAttributeValue(profileCogId)}"] ` +
          `.profile-diary-room-entry[data-diary-entry-id="${cssAttributeValue(diaryEntryId)}"]`
      : `.profile-diary-room-entry[data-diary-entry-id="${cssAttributeValue(diaryEntryId)}"]`;
  }

  const achievementAssignment = element.dataset.achievementAssignment;
  if (achievementAssignment) {
    const achievementSelector =
      `.profile-achievement-row[data-achievement-assignment="${cssAttributeValue(achievementAssignment)}"]`;
    const profilePage = element.closest<HTMLElement>(".cog-profile-page[data-cog-id]");
    const profileCogId = profilePage?.dataset.cogId;
    return profileCogId
      ? `.cog-profile-page[data-cog-id="${cssAttributeValue(profileCogId)}"] ${achievementSelector}`
      : achievementSelector;
  }

  const achievement = element.dataset.achievement;
  const achievementStatus = element.dataset.achievementStatus;
  if (achievement && achievementStatus) {
    const achievementSelector =
      `.profile-achievement-row[data-achievement="${cssAttributeValue(achievement)}"]` +
      `[data-achievement-status="${cssAttributeValue(achievementStatus)}"]`;
    const profilePage = element.closest<HTMLElement>(".cog-profile-page[data-cog-id]");
    const profileCogId = profilePage?.dataset.cogId;
    return profileCogId
      ? `.cog-profile-page[data-cog-id="${cssAttributeValue(profileCogId)}"] ${achievementSelector}`
      : achievementSelector;
  }

  const subsection = element.dataset.logSubsection;
  const tick = element.closest<HTMLElement>("[data-tick]")?.dataset.tick;
  if (!subsection || !tick) {
    return undefined;
  }

  const sectionSelector =
    `.log-tick-section[data-tick="${cssAttributeValue(tick)}"] ` +
    `.log-subsection[data-log-subsection="${cssAttributeValue(subsection)}"]`;
  const profilePage = element.closest<HTMLElement>(".cog-profile-page[data-cog-id]");
  const profileCogId = profilePage?.dataset.cogId;
  if (profileCogId) {
    return `.cog-profile-page[data-cog-id="${cssAttributeValue(profileCogId)}"] ${sectionSelector}`;
  }

  return `.log-panel ${sectionSelector}`;
}

function profileFocusScope(element: HTMLElement, cogId: string): string {
  const escapedCogId = cssAttributeValue(cogId);
  if (element.closest(".cog-profile-page")) {
    return `.cog-profile-page[data-cog-id="${escapedCogId}"]`;
  }

  return `.profile-section [data-cog-id="${escapedCogId}"]`;
}

function cssAttributeValue(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

export function scrollRosterCogTowardTop(root: ParentNode, cogId: string): boolean {
  const roster = root.querySelector<HTMLElement>(".cog-roster");
  const row = roster?.querySelector<HTMLElement>(`.cog-row-shell[data-cog-id="${cssAttributeValue(cogId)}"]`);
  if (!roster || !row) {
    return false;
  }

  const maxScrollTop = Math.max(0, roster.scrollHeight - roster.clientHeight);
  const rowTop = row.offsetTop - roster.offsetTop;
  const rowHeight = row.offsetHeight || 48;
  const rowBottom = rowTop + rowHeight;
  const visibleTop = roster.scrollTop;
  const visibleBottom = visibleTop + roster.clientHeight;
  if (rowTop >= visibleTop && rowBottom <= visibleBottom) {
    return true;
  }

  const targetScrollTop = rowTop < visibleTop ? rowTop : rowBottom - roster.clientHeight;
  roster.scrollTop = Math.max(0, Math.min(targetScrollTop, maxScrollTop));
  return true;
}

function cssIdentifier(value: string): string {
  return globalThis.CSS?.escape ? globalThis.CSS.escape(value) : value.replace(/[^a-zA-Z0-9_-]/g, "\\$&");
}

function renderProfileEditor(cog: CogSnapshot, draft: CogProfileDraft, density: "compact" | "page"): string {
  const promptRows = density === "page" ? 7 : 4;
  const saveAction = density === "page" ? ` data-action="save-profile"` : "";
  const submitAction = density === "page"
    ? `
      <div class="profile-form-actions">
        <button class="profile-send-button" type="submit">Send</button>
      </div>
    `
    : "";

  return `
    <form class="profile-form profile-form-${escapeHtml(density)}" data-cog-id="${escapeHtml(cog.id)}"${saveAction}>
      <label class="profile-field">
        <span>Guidance</span>
        <textarea
          aria-label="Guidance"
          data-profile-field="behaviorPrompt"
          name="behaviorPrompt"
          rows="${escapeHtml(String(promptRows))}"
        >${escapeHtml(draft.behaviorPrompt)}</textarea>
      </label>
      ${submitAction}
    </form>
  `;
}

export function renderCogProfilePage(
  cog: CogSnapshot,
  snapshot: WorldSnapshot,
  draft: CogProfileDraft,
  gameConfig?: GameConfig,
  pendingChoice?: PendingManualChoice,
  mobileFeedExpanded = false,
  mobilePromptSuggestionStep = 0,
  diaryVisibleRoomCount = DIARY_INITIAL_ROOM_LIMIT,
  controllerLogFilters: ControllerLogFilters = DEFAULT_CONTROLLER_LOG_FILTERS,
): string {
  const diaryEntries = buildDiaryRoomEntries(cog, snapshot);
  const logTickSections = groupLogByTick(cog.conversationLog);
  const filteredLogTickSections = filteredControllerLogSections(logTickSections, controllerLogFilters);
  const logSections = filteredLogTickSections
    .map(renderLogSection)
    .join("");
  const achievementCount = completedAchievementsForCog(cog).length;
  const activeAchievementCount = achievementAssignmentsForCog(cog).length;

  return `
    <section class="cog-profile-page" data-cog-id="${escapeHtml(cog.id)}" aria-label="${escapeHtml(cog.name)} profile page">
      <div class="profile-pull-refresh" aria-hidden="true">
        <span class="profile-pull-refresh-icon"></span>
      </div>
      <div class="cog-profile-scroll">
        ${renderMobileCogProfileController(
          cog,
          draft,
          snapshot,
          diaryEntries,
          gameConfig,
          pendingChoice,
          mobileFeedExpanded,
          mobilePromptSuggestionStep,
        )}
        <header class="profile-hero" data-color="${escapeHtml(cog.color)}">
          <div class="profile-identity">
            <div class="profile-avatar" data-color="${escapeHtml(cog.color)}" aria-hidden="true">
              ${renderProfileAvatar(cog)}
            </div>
            <div class="profile-title-block">
              <h1>${escapeHtml(cog.name)}</h1>
              <div class="profile-subtitle">
                <span class="profile-team-pill" data-color="${escapeHtml(cog.color)}">${escapeHtml(cog.color)} team</span>
                <span class="profile-location-pill">${escapeHtml(profileLocationLabel(cog, snapshot))}</span>
                <span class="profile-subtitle-traits" aria-label="Traits">${renderProfileTraitPills(cog)}</span>
              </div>
            </div>
          </div>
          <div class="profile-hero-prompt">
            <span>Guidance</span>
            <p>${escapeHtml(cog.behaviorPrompt || "No guidance set.")}</p>
          </div>
        </header>

        <section class="profile-stat-band" aria-label="Cog scorecard">
          ${renderProfileStat("Score", formatPersonalScore(cog.personalScore), "personal pts")}
          ${renderProfileStat("Debates", `${cog.stats.argumentsWon}-${cog.stats.argumentsLost}`, debateRecordMeta(cog))}
          ${renderProfileStat("Certainty", `${formatNumber(cog.certainty)}`, `${cog.color} team`)}
          ${renderProfileStat("Achievements", `${achievementCount}/${achievementCount + activeAchievementCount}`, "done/active")}
        </section>

        <div class="profile-page-grid">
          <div class="profile-page-column profile-achievement-column">
            <section class="profile-block profile-achievements-block" aria-label="Achievements">
              <div class="profile-block-header">
                <span>Achievements</span>
                <span>${escapeHtml(String((cog.completedAchievements ?? []).length))} done</span>
              </div>
              ${renderProfileAchievements(cog, snapshot)}
            </section>
          </div>

          <div class="profile-page-column profile-feed-column">
            <section class="profile-block profile-editor-block" aria-label="Send guidance">
              <div class="profile-block-header profile-guidance-header">
                <span>Send Guidance</span>
              </div>
              ${renderProfileEditor(cog, draft, "page")}
            </section>

            <section class="profile-block profile-diary-block" aria-label="Cog diary">
              <div class="profile-block-header">
                <span>Diary</span>
                <span>${escapeHtml(String(diaryEntries.length))}</span>
              </div>
              ${renderDiaryRoomFeed(diaryEntries, {
                cogId: cog.id,
                currentRoomId: cog.location?.roomId,
                visibleRoomCount: diaryVisibleRoomCount,
              })}
            </section>

          </div>

          <details class="profile-block profile-controller-log profile-page-wide" aria-label="Controller log" open>
            <summary class="profile-block-header">
              <span>Controller Log</span>
              <span>${escapeHtml(`${filteredLogTickSections.length}/${logTickSections.length} tactics`)}</span>
            </summary>
            ${renderControllerLogFilters(controllerLogFilters)}
            <div class="profile-log-thread">
              ${logSections || `<div class="profile-empty-state">No controller messages yet.</div>`}
            </div>
          </details>
        </div>
        <footer class="profile-abandon-footer" aria-label="Abandon cog">
          <button
            class="profile-abandon-button"
            data-action="abandon-cog"
            data-cog-id="${escapeHtml(cog.id)}"
            type="button"
          >Abandon</button>
        </footer>
      </div>
    </section>
  `;
}

function renderMobileCogProfileController(
  cog: CogSnapshot,
  draft: CogProfileDraft,
  snapshot: WorldSnapshot,
  diaryEntries: DiaryRoomEntry[],
  gameConfig: GameConfig | undefined,
  pendingChoice: PendingManualChoice | undefined,
  mobileFeedExpanded: boolean,
  mobilePromptSuggestionStep: number,
): string {
  const certainty = certaintyMeter(cog, gameConfig?.conversionThreshold ?? CONVERSION_THRESHOLD);
  const choices = rosterChoicesForCog(cog, snapshot, gameConfig);
  const place = rosterStatePlace(cog, snapshot);
  const achievementCount = completedAchievementsForCog(cog).length;
  const activeAchievementCount = achievementAssignmentsForCog(cog).length;

  return `
    <section class="profile-mobile-controller" data-color="${escapeHtml(cog.color)}" aria-label="${escapeHtml(cog.name)} phone controller">
      <header class="profile-mobile-status-header" data-color="${escapeHtml(cog.color)}">
        <div class="profile-mobile-identity">
          <div class="profile-mobile-avatar" data-color="${escapeHtml(cog.color)}" aria-hidden="true">
            ${renderProfileAvatar(cog)}
          </div>
          <div class="profile-mobile-title">
            <span class="profile-mobile-team" data-color="${escapeHtml(cog.color)}">${escapeHtml(cog.color)} team</span>
            <h1>${escapeHtml(cog.name)}</h1>
            <p>${escapeHtml(place)}</p>
          </div>
        </div>
        <div class="profile-mobile-score-strip" aria-label="${escapeHtml(cog.name)} status counters">
          ${renderMobileProfileStat("Score", formatPersonalScore(cog.personalScore), "pts")}
          ${renderMobileProfileStat("Debates", `${cog.stats.argumentsWon}-${cog.stats.argumentsLost}`, debateRecordMeta(cog))}
          ${renderMobileProfileStat("Flips", String(cog.stats.teamFlips), cog.stats.teamFlips === 1 ? "team" : "teams")}
          ${renderMobileProfileStat("Achievements", `${achievementCount}/${achievementCount + activeAchievementCount}`, "done/active")}
        </div>
        <div class="profile-mobile-risk-strip" aria-label="${escapeHtml(cog.name)} certainty">
          <div class="profile-mobile-risk-heading">
            <span>Certainty</span>
            <strong>${escapeHtml(mobileCertaintyLabel(cog, gameConfig))}</strong>
          </div>
          ${renderMobileCertaintyGauge(cog, certainty, gameConfig)}
        </div>
        ${renderMobileCurrentStatus(cog, pendingChoice)}
      </header>

      <div class="profile-mobile-body">
        ${renderMobileProfileGuidancePanel(cog, draft, snapshot)}
        ${renderMobileDiaryPanel(cog, diaryEntries, mobileFeedExpanded)}
      </div>
    </section>
  `;
}

function renderMobileDiaryPanel(cog: CogSnapshot, diaryEntries: DiaryRoomEntry[], expanded: boolean): string {
  const visibleRoomCount = expanded ? Math.max(DIARY_INITIAL_ROOM_LIMIT, diaryEntries.length) : DIARY_INITIAL_ROOM_LIMIT;
  const hasOverflow = diaryEntries.length > DIARY_INITIAL_ROOM_LIMIT;
  return `
    <section class="profile-mobile-panel profile-mobile-feed-panel" aria-label="${escapeHtml(`${cog.name} diary`)}">
      <div class="profile-mobile-panel-heading">
        <span></span>
        <strong>${escapeHtml("Diary")}</strong>
      </div>
      ${renderDiaryRoomFeed(diaryEntries, {
        cogId: cog.id,
        currentRoomId: cog.location?.roomId,
        visibleRoomCount,
      })}
      ${
        hasOverflow
          ? `<button
              aria-expanded="${expanded ? "true" : "false"}"
              class="profile-mobile-feed-toggle"
              data-action="toggle-mobile-actions"
              data-cog-id="${escapeHtml(cog.id)}"
              type="button"
            >${expanded ? "Collapse diary" : "Show all rooms"}</button>`
          : ""
      }
    </section>
  `;
}

function renderMobileCurrentStatus(cog: CogSnapshot, pendingChoice: PendingManualChoice | undefined): string {
  return `
    <div class="profile-mobile-current-strip" aria-label="${escapeHtml(cog.name)} profile context">
      ${renderMobileIntentRow(cog, pendingChoice)}
      ${renderMobileTraitRow(cog)}
    </div>
  `;
}

function renderMobileIntentRow(cog: CogSnapshot, pendingChoice: PendingManualChoice | undefined): string {
  return `
    <div class="profile-mobile-intent-line" aria-label="${escapeHtml(`${cog.name} current thoughts`)}">
      <span>Thoughts:</span>
      <p>${escapeHtml(mobileIntentText(cog, pendingChoice))}</p>
    </div>
  `;
}

function renderMobileTraitRow(cog: CogSnapshot): string {
  return `
    <div class="profile-mobile-trait-row" aria-label="Traits">
      ${renderMobileTraitBadge("defensiveTrait", cog.defensiveTrait)}
      ${renderMobileTraitBadge("activeTrait", cog.activeTrait)}
    </div>
  `;
}

function renderMobileTraitBadge(kind: TraitKind, value: string): string {
  return `
    <span
      aria-label="${escapeHtml(`${mobileTraitKindLabel(kind)} ${titleCase(value)}`)}"
      class="trait-badge trait-badge-readonly profile-mobile-trait-badge"
      data-trait-kind="${escapeHtml(kind)}"
      data-trait-value="${escapeHtml(value)}"
    >
      <span>${escapeHtml(titleCase(value))}</span>
    </span>
  `;
}

function mobileTraitKindLabel(kind: TraitKind): string {
  switch (kind) {
    case "defensiveTrait":
      return "Trait";
    case "activeTrait":
      return "Trait";
  }
}

function renderMobileProfileStat(label: string, value: string, meta: string): string {
  return `
    <div class="profile-mobile-stat">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <span>${escapeHtml(meta)}</span>
    </div>
  `;
}

function renderMobileProfileActionPanel(
  cog: CogSnapshot,
  snapshot: WorldSnapshot,
  choices: RosterChoice[],
  gameConfig: GameConfig | undefined,
  pendingChoice: PendingManualChoice | undefined,
): string {
  const isTacticChoice = choices.some(isRosterTacticChoice);
  const hasTargetChoice = choices.some(isRosterTargetChoice);
  const cooldownTicks = remainingRosterMoveCooldownTicks(cog, snapshot, gameConfig);
  const hasPendingChoice = Boolean(pendingChoice && choices.some((choice) => rosterChoiceSignature(cog.id, choice) === pendingChoice.signature));
  const tacticReady = canChooseRosterTactic(cog, snapshot);
  const actionLabel = isTacticChoice ? "Argument" : "Action";
  const title = isTacticChoice
    ? hasPendingChoice
      ? "Cue updated"
      : tacticReady
        ? "Shape argument"
        : "Shape argument"
    : hasPendingChoice
      ? "Action loaded"
      : hasTargetChoice
        ? "Talk or move"
      : choices.length > 0 && cooldownTicks > 0
        ? "Load next room"
        : choices.length > 0
          ? "Choose room"
          : "No action";
  const modeClass = isTacticChoice ? "is-tactic" : "is-room";
  const buttons = choices.length
    ? choices.map((choice, index) => renderMobileProfileChoiceButton(cog, choice, snapshot, index, pendingChoice)).join("")
    : renderMobileProfileActionPlaceholder(cog, snapshot, gameConfig);

  return `
    <section class="profile-mobile-panel profile-mobile-action-panel ${modeClass}" aria-label="${escapeHtml(actionLabel)} controls">
      <div class="profile-mobile-panel-heading">
        <span>${escapeHtml(actionLabel)}</span>
        <strong>${escapeHtml(title)}</strong>
      </div>
      <div class="profile-mobile-action-grid${choices.length ? "" : " is-empty"}">${buttons}</div>
    </section>
  `;
}

function renderMobileProfileGuidancePanel(cog: CogSnapshot, draft: CogProfileDraft, snapshot: WorldSnapshot): string {
  return `
    <section class="profile-mobile-guidance-panel" aria-label="${escapeHtml(`${cog.name} guidance`)}">
      <div class="profile-mobile-panel profile-mobile-guidance-card">
        <div class="profile-mobile-panel-heading">
          <span></span>
          <strong>Guidance</strong>
        </div>
        <form class="profile-mobile-prompt-form" data-action="save-profile" data-cog-id="${escapeHtml(cog.id)}">
          <textarea
            aria-label="Guidance"
            data-profile-field="behaviorPrompt"
            maxlength="1000"
            name="behaviorPrompt"
            placeholder="Guide how this Cog should approach the room."
            rows="5"
          >${escapeHtml(draft.behaviorPrompt)}</textarea>
          <div class="profile-mobile-prompt-footer">
            <div class="profile-mobile-prompt-action-row">
              <button class="profile-mobile-prompt-submit" type="submit">Send</button>
            </div>
          </div>
        </form>
      </div>
      ${renderMobileAchievementsPanel(cog, snapshot)}
    </section>
  `;
}

function renderMobileAchievementsPanel(cog: CogSnapshot, snapshot: WorldSnapshot): string {
  const activeAchievements = [...achievementAssignmentsForCog(cog)].sort((left, right) =>
    (left.timeoutTick - snapshot.tick) - (right.timeoutTick - snapshot.tick) ||
    left.assignedTick - right.assignedTick ||
    achievementKey(left).localeCompare(achievementKey(right))
  );
  const completedAchievements = completedAchievementsForCog(cog).slice(0, 2);
  const achievementRows = [
    ...activeAchievements.map((achievement) => renderMobileAchievementRow(achievement, snapshot, cog)),
    ...completedAchievements.map((achievement) => renderMobileCompletedAchievementRow(achievement)),
  ].join("");

  return `
    <section class="profile-mobile-achievements-panel" aria-label="${escapeHtml(`${cog.name} achievements`)}">
      <div class="profile-mobile-panel-heading">
        <strong>Achievements</strong>
      </div>
      <div class="profile-mobile-achievement-list" aria-label="Achievements">
        ${achievementRows || `<div class="profile-mobile-achievement-empty">No active achievements.</div>`}
      </div>
    </section>
  `;
}

function renderMobileAchievementRow(achievement: AchievementAssignment, snapshot: WorldSnapshot, cog: CogSnapshot): string {
  const rule = achievementRuleByAssignment(achievement);
  const remainingTicks = Math.max(0, achievement.timeoutTick - snapshot.tick);
  const totalTicks = Math.max(1, achievement.timeoutTick - achievement.assignedTick);
  const remainingSeconds = Math.ceil(remainingTicks * SIMULATION_TICK_SECONDS);
  const remainingPercent = clampPercentage((remainingTicks / totalTicks) * 100);
  const urgencyClass = remainingPercent <= 25 ? " is-low" : "";
  const progress = achievementProgress(achievement, snapshot, cog);
  const progressLabel = formatAchievementProgress(progress);
  return `
    <div class="profile-mobile-achievement-row" data-achievement="${escapeHtml(achievementKey(achievement))}">
      <strong>${escapeHtml(rule?.label ?? achievement.achievementId)}</strong>
      <div
        class="profile-mobile-achievement-time${urgencyClass}"
        aria-label="${escapeHtml(`${remainingSeconds} seconds left`)}"
        title="${escapeHtml(`${remainingSeconds}s left`)}"
      >
        <span class="profile-mobile-achievement-time-track" aria-hidden="true">
          <span
            class="profile-mobile-achievement-time-fill"
            style="width: ${escapeHtml(String(remainingPercent))}%"
          ></span>
        </span>
        <span class="profile-mobile-achievement-time-label">${escapeHtml(`${remainingSeconds}s remaining`)}</span>
        <span class="profile-mobile-achievement-progress" aria-label="${escapeHtml(`Progress ${progressLabel}`)}">${escapeHtml(progressLabel)}</span>
      </div>
      <p>${escapeHtml(rule?.condition ?? "Active achievement goal.")}</p>
    </div>
  `;
}

function renderMobileCompletedAchievementRow(achievement: CompletedAchievement): string {
  const rule = achievementRuleByAssignment(achievement);
  const label = rule?.label ?? achievement.achievementId;
  const description = rule?.description ?? "Completed achievement.";
  const progressLabel = formatAchievementProgress(completedAchievementProgress(achievement));
  return `
    <div class="profile-mobile-completed-row" data-achievement="${escapeHtml(achievementKey(achievement))}">
      <span class="profile-mobile-completed-copy">
        <span class="profile-mobile-completed-status">Completed:</span>
        <span class="profile-mobile-completed-name">${escapeHtml(label)}</span>
        <span class="profile-mobile-completed-description">${escapeHtml(description)}</span>
        <span class="profile-mobile-completed-progress">${escapeHtml(progressLabel)}</span>
      </span>
      <span class="profile-mobile-completed-score">
        <strong>+${escapeHtml(formatScore(achievement.points))}</strong>
      </span>
    </div>
  `;
}

function renderMobileProfileActionPlaceholder(
  cog: CogSnapshot,
  snapshot: WorldSnapshot,
  gameConfig: GameConfig | undefined,
): string {
  return `
    <div class="profile-mobile-action-placeholder">
      <strong>${escapeHtml(mobileProfileNoActionTitle(cog, snapshot, gameConfig))}</strong>
      <span>${escapeHtml(mobileProfileNoActionCopy(cog, snapshot, gameConfig))}</span>
    </div>
  `;
}

function renderMobileProfileChoiceButton(
  cog: CogSnapshot,
  choice: RosterChoice,
  snapshot: WorldSnapshot,
  index: number,
  pendingChoice: PendingManualChoice | undefined,
): string {
  const queuedClass = pendingChoice?.signature === rosterChoiceSignature(cog.id, choice) ? " is-queued" : "";
  if (choice.kind === "tactic") {
    return `
      <button
        aria-label="Select ${escapeHtml(choice.label)} for ${escapeHtml(cog.name)}"
        aria-pressed="${queuedClass ? "true" : "false"}"
        class="profile-mobile-action-button profile-mobile-action-button-tactic${queuedClass}"
        data-action="select-cog-choice"
        data-choice-kind="tactic"
        data-cog-id="${escapeHtml(cog.id)}"
        data-tactic="${escapeHtml(choice.tactic)}"
        type="button"
      >
        <span class="profile-mobile-tactic-icon" aria-hidden="true">${escapeHtml(choice.icon)}</span>
        <span class="profile-mobile-action-label">${escapeHtml(choice.label)}</span>
      </button>
    `;
  }

  if (choice.kind === "target") {
    return `
      <button
        aria-label="Have ${escapeHtml(cog.name)} talk to ${escapeHtml(choice.label)}"
        aria-pressed="${queuedClass ? "true" : "false"}"
        class="profile-mobile-action-button profile-mobile-action-button-target${queuedClass}"
        data-action="select-cog-choice"
        data-choice-kind="target"
        data-cog-id="${escapeHtml(cog.id)}"
        data-target-id="${escapeHtml(choice.targetId)}"
        data-target-label="${escapeHtml(choice.label)}"
        type="button"
      >
        <span class="profile-mobile-action-kicker">
          <span class="profile-mobile-target-dot" data-color="${escapeHtml(choice.color)}" aria-hidden="true"></span>
          <span>${queuedClass ? "loaded" : `${choice.color} ${formatNumber(choice.certainty)}`}</span>
        </span>
        <span class="profile-mobile-action-label">${escapeHtml(choice.label)}</span>
      </button>
    `;
  }

  const room = snapshot.venue?.rooms.find((candidate) => candidate.id === choice.roomId);
  const roomKind = room?.kind ?? "room";
  const relation = cog.location?.roomId === choice.roomId ? "hold" : "route";
  return `
    <button
      aria-label="Send ${escapeHtml(cog.name)} to ${escapeHtml(choice.label)}"
      aria-pressed="${queuedClass ? "true" : "false"}"
      class="profile-mobile-action-button${queuedClass}"
      data-action="select-cog-choice"
      data-choice-kind="room"
      data-cog-id="${escapeHtml(cog.id)}"
      data-room-kind="${escapeHtml(roomKind)}"
      data-room-id="${escapeHtml(choice.roomId)}"
      data-room-relation="${escapeHtml(relation)}"
      type="button"
    >
      <span class="profile-mobile-action-kicker">
        <span aria-hidden="true">${escapeHtml(String(index + 1).padStart(2, "0"))}</span>
        <span>${queuedClass ? "loaded" : escapeHtml(roomKindLabel(roomKind))}</span>
      </span>
      <span class="profile-mobile-action-label">${escapeHtml(choice.label)}</span>
    </button>
  `;
}

function roomKindLabel(kind: string): string {
  switch (kind) {
    case "bar":
      return "bar";
    case "entrance":
      return "entry";
    case "exhibit":
      return "art";
    case "lounge":
      return "lounge";
    case "stage":
      return "stage";
    case "table":
      return "seat";
    case "walkway":
      return "path";
    default:
      return kind || "room";
  }
}

function mobileProfileNoActionCopy(
  cog: CogSnapshot,
  snapshot: WorldSnapshot,
  gameConfig: GameConfig | undefined,
): string {
  if (cog.moving) {
    return "Route in progress. Controls unlock on arrival.";
  }

  if (cog.debate) {
    return "Waiting for the tactic choice window.";
  }

  const cooldownTicks = remainingRosterMoveCooldownTicks(cog, snapshot, gameConfig);
  if (cooldownTicks > 0) {
    return "Room movement is cooling down. Watch the board and get ready for the next opening.";
  }

  return "No open room moves right now. Stay close to the board and watch the room.";
}

function mobileProfileNoActionTitle(
  cog: CogSnapshot,
  snapshot: WorldSnapshot,
  gameConfig: GameConfig | undefined,
): string {
  if (cog.moving) {
    return "Moving";
  }

  if (cog.debate) {
    return "Argument warming up";
  }

  const cooldownTicks = remainingRosterMoveCooldownTicks(cog, snapshot, gameConfig);
  if (cooldownTicks > 0) {
    return "Cooling down";
  }

  return "Holding position";
}

function shouldPrunePendingWaitChoice(pending: PendingManualChoice, age: number): boolean {
  const pendingText = pending.action.type === "wait" ? playerSteerText(pending.action.intent) : undefined;
  if (!pendingText) {
    return age > 2500;
  }

  return false;
}

function mobileIntentText(cog: CogSnapshot, pendingChoice: PendingManualChoice | undefined): string {
  const pendingText = pendingChoice?.action.type === "wait" ? playerSteerText(pendingChoice.action.intent) : undefined;
  const steerText = playerSteerText(cog.intent);
  if (pendingText && steerText) {
    return "Reading the room for the next opening.";
  }

  if (steerText) {
    return steerText;
  }

  const intent = cog.intent?.trim();
  if (intent) {
    return sentenceCase(intent);
  }

  return "Reading the room for the next opening.";
}

function playerSteerText(intent: string | undefined): string | undefined {
  const value = intent?.trim();
  if (!value?.startsWith("player steer:")) {
    return undefined;
  }

  const text = value.slice("player steer:".length).trim();
  return text || undefined;
}

function nearbyCogChoices(
  cog: CogSnapshot,
  snapshot: WorldSnapshot,
  options: { sameTeam: boolean },
): CogSnapshot[] {
  return snapshot.cogs
    .filter((candidate) => candidate.id !== cog.id && (candidate.color === cog.color) === options.sameTeam)
    .filter((candidate) => !candidate.moving && !candidate.debate)
    .filter((candidate) => {
      if (snapshot.venue && cog.location && candidate.location) {
        return candidate.location.roomId === cog.location.roomId;
      }

      return Math.abs(candidate.position.x - cog.position.x) <= 2 && Math.abs(candidate.position.y - cog.position.y) <= 2;
    })
    .sort((left, right) => left.certainty - right.certainty);
}

function mobileCertaintyLabel(cog: CogSnapshot, gameConfig: GameConfig | undefined): string {
  const threshold = Math.max(1, gameConfig?.conversionThreshold ?? CONVERSION_THRESHOLD);
  return `${formatNumber(cog.certainty)}/${formatNumber(threshold)}`;
}

function renderMobileCertaintyGauge(
  cog: CogSnapshot,
  certainty: CertaintyMeter,
  gameConfig: GameConfig | undefined,
): string {
  const threshold = Math.max(1, gameConfig?.conversionThreshold ?? CONVERSION_THRESHOLD);
  return `
    <div
      class="profile-mobile-certainty-gauge"
      aria-label="${escapeHtml(`${cog.name} certainty ${formatNumber(cog.certainty)} of ${formatNumber(threshold)}`)}"
    >
      <div class="profile-mobile-certainty-track" aria-hidden="true">
        <span
          class="profile-mobile-certainty-fill"
          data-color="${escapeHtml(certainty.color)}"
          style="width: ${escapeHtml(String(certainty.value))}%"
        ></span>
      </div>
      <div class="profile-mobile-certainty-labels">
        <span>0</span>
        <span>${escapeHtml(cog.color)} team</span>
        <span>${escapeHtml(formatNumber(threshold))}</span>
      </div>
    </div>
  `;
}

export function renderProfileGoalScoreBreakdown(_cog: WorldSnapshot["cogs"][number]): string {
  return "";
}

export function renderProfileAchievements(
  cog: WorldSnapshot["cogs"][number],
  snapshot?: Pick<WorldSnapshot, "tick">,
): string {
  const active = achievementAssignmentsForCog(cog)
    .map((achievement) => {
      const rule = achievementRuleByAssignment(achievement);
      return renderProfileAchievementRow({
        assignmentId: achievement.assignmentId,
        description: rule?.description,
        label: rule?.label ?? achievement.achievementId,
        meta: formatAchievementTimeout(achievement, snapshot?.tick ?? 0),
        ruleKey: achievementKey(achievement),
        status: "current",
      });
    })
    .join("");
  const completed = completedAchievementsForCog(cog)
    .map((achievement) => {
      const rule = achievementRuleByAssignment(achievement);
      return renderProfileAchievementRow({
        assignmentId: achievement.assignmentId,
        description: rule?.description,
        label: rule?.label ?? achievement.achievementId,
        meta: `+${formatScore(achievement.points)}`,
        ruleKey: achievementKey(achievement),
        status: "completed",
      });
    })
    .join("");

  return `
    <div class="profile-achievement-list">
      <section>
        <h3>Current</h3>
        ${active || `<div class="profile-empty">No active achievements.</div>`}
      </section>
      <section>
        <h3>Completed</h3>
        ${completed || `<div class="profile-empty">No completed achievements.</div>`}
      </section>
    </div>
  `;
}

function formatAchievementTimeout(achievement: AchievementAssignment, currentTick: number): string {
  const remainingTicks = Math.max(0, achievement.timeoutTick - currentTick);
  return `in ${formatDurationSeconds(Math.ceil(remainingTicks * SIMULATION_TICK_SECONDS))}`;
}

function formatDurationSeconds(totalSeconds: number): string {
  const seconds = Math.max(0, Math.ceil(totalSeconds));
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  if (minutes > 0 && remainder > 0) {
    return `${minutes}m ${remainder}s`;
  }
  if (minutes > 0) {
    return `${minutes}m`;
  }
  return `${remainder}s`;
}

function renderProfileAchievementRow(options: {
  assignmentId: string;
  description: string | undefined;
  label: string;
  meta: string;
  ruleKey: string;
  status: "completed" | "current";
}): string {
  const completedClass = options.status === "completed" ? " is-completed" : "";
  const description = options.description ?? "No description available.";
  return `
    <details
      class="profile-achievement-row${completedClass}"
      data-achievement-assignment="${escapeHtml(options.assignmentId)}"
      data-achievement="${escapeHtml(options.ruleKey)}"
      data-achievement-status="${escapeHtml(options.status)}"
    >
      <summary class="profile-achievement-summary">
        <span class="profile-achievement-name">${escapeHtml(options.label)}</span>
        <span class="profile-achievement-meta">${escapeHtml(options.meta)}</span>
      </summary>
      <p class="profile-achievement-description">${escapeHtml(description)}</p>
    </details>
  `;
}

function achievementAssignmentsForCog(cog: WorldSnapshot["cogs"][number]): AchievementAssignment[] {
  return (cog as WorldSnapshot["cogs"][number] & { achievements?: AchievementAssignment[] }).achievements ?? [];
}

function completedAchievementsForCog(cog: WorldSnapshot["cogs"][number]): CompletedAchievement[] {
  return (cog as WorldSnapshot["cogs"][number] & { completedAchievements?: CompletedAchievement[] }).completedAchievements ?? [];
}

function failedAchievementsForCog(cog: WorldSnapshot["cogs"][number]): FailedAchievement[] {
  return (cog as WorldSnapshot["cogs"][number] & { failedAchievements?: FailedAchievement[] }).failedAchievements ?? [];
}

function achievementProgress(
  achievement: AchievementAssignment,
  snapshot: WorldSnapshot,
  cog: CogSnapshot,
): AchievementProgress {
  const events = achievementWindowEvents(achievement, snapshot);
  switch (achievement.achievementId) {
    case "debateThreeCogs":
      return countProgress(debateOpponentIdsForCog(events, cog.id).size, 3);
    case "winInRoom":
      return countProgress(
        debateWinsForCog(
          events,
          cog.id,
          (event) => debateRoomKind(snapshot, event) === (achievement.parameters?.roomKind ?? "bar"),
        ),
        1,
      );
    case "winFinalRound":
      return countProgress(maxWinningDebateRoundForCog(events, cog.id), 5);
    case "winAfterTwoLosses":
      return countProgress(cog.stats.argumentsLost >= 2 ? debateWinsForCog(events, cog.id) : 0, 1);
    case "beatTrait":
      return countProgress(
        debateWinsForCog(events, cog.id, (event) => opponentHasTrait(snapshot, event, cog.id, achievement.parameters?.trait)),
        1,
      );
    case "defeatOpponentTwice":
      return countProgress(
        debateWinsForCog(events, cog.id, (event) => debateOpponentId(event, cog.id) === achievement.parameters?.cogId),
        2,
      );
    case "witnessTeamWins":
      return countProgress(
        witnessedWinsForCog(events, cog.id, (event) => event.debate?.winnerColor === achievement.parameters?.team),
        achievementRoundsTarget(achievement),
      );
    case "witnessComeback":
    case "witnessConversion":
      return countProgress(achievement.achievementId === "witnessComeback" ? witnessedWinsForCog(events, cog.id, (event) => event.debate?.winnerColor === achievement.parameters?.team) : witnessedDebatesForCog(events, cog.id), 1);
    case "flipFlop":
      return countProgress(colorChangeEventsForCog(events, cog.id), 2);
    case "debateMarathon":
      return countProgress(maxDebateRoundForCog(events, cog.id), 5);
    case "comebackRound":
      return countProgress(cog.stats.argumentsLost > 0 ? debateWinsForCog(events, cog.id) : 0, 1);
    case "perfectDebate":
      return countProgress(cog.stats.argumentsLost === 0 ? cog.stats.argumentsWon : 0, 3);
    case "loseToTrait":
      return countProgress(debateLossesForCog(events, cog.id, (event) => winnerHasTrait(snapshot, event, achievement.parameters?.trait)), 1);
    case "sweepDebate":
      return countProgress(largestWinCountAgainstOneOpponent(events, cog.id), 3);
    case "winWithAllTactics":
      return countProgress(new Set(debateWinsForCog(events, cog.id).map((event) => debateTacticForCog(event, cog.id)).filter(Boolean)).size, 3);
    case "roomSpecialist":
      return countProgress(
        debateWinsForCog(events, cog.id, (event) => debateRoomKind(snapshot, event) === achievement.parameters?.roomKind),
        achievementRoundsTarget(achievement),
      );
    case "travelingDebater":
      return countProgress(new Set(debateWinsForCog(events, cog.id).map((event) => debateRoomKind(snapshot, event)).filter(Boolean)).size, 3);
    case "traitNemesis":
      return countProgress(
        debateLossesForCog(events, cog.id, (event) => winnerHasTrait(snapshot, event, achievement.parameters?.trait)),
        achievementRoundsTarget(achievement),
      );
    case "revengeRound":
      return countProgress(debateLossesForCog(events, cog.id, (event) => debateOpponentId(event, cog.id) === achievement.parameters?.cogId).length > 0 ? debateWinsForCog(events, cog.id, (event) => debateOpponentId(event, cog.id) === achievement.parameters?.cogId) : 0, 1);
    case "lowCertaintyWin":
      return countProgress(cog.certainty <= 25 ? debateWinsForCog(events, cog.id) : 0, 1);
    case "socialCircuit":
      return countProgress(Math.min(debateOpponentIdsForCog(events, cog.id).size, new Set(events.filter((event) => isDebateParticipant(event, cog.id)).map((event) => debateRoomKind(snapshot, event)).filter(Boolean)).size), 3);
    case "underdogWitness":
      return countProgress(witnessedWinsForCog(events, cog.id, (event) => event.debate?.winnerColor === smallerTeam(snapshot)), 3);
    case "drawBreaker":
      return countProgress(hasDrawBreaker(events, cog.id) ? 1 : 0, 1);
    case "denySweep":
      return countProgress(hasDenySweep(events, cog.id) ? 1 : 0, 1);
    case "convertOpponent":
      return countProgress(convertedOpponentsAfterDebate(events, cog.id).size, 1);
    case "finalRoundWitness":
      return countProgress(maxWitnessedDebateRoundForCog(events, cog.id), 5);
    case "winFromBehind":
      return countProgress(hasWinFromBehind(events, cog.id) ? 1 : 0, 1);
    case "sameTacticSweep":
      return countProgress(
        debateWinsForCog(events, cog.id, (event) => debateTacticForCog(event, cog.id) === achievement.parameters?.tactic),
        3,
      );
    case "counterComeback":
      return countProgress(hasCounterComeback(events, cog.id) ? 1 : 0, 1);
    case "roomComeback":
      return countProgress(
        hasRoomComeback(events, cog.id, achievement.parameters?.roomKind, (event) => debateRoomKind(snapshot, event)) ? 1 : 0,
        1,
      );
    case "traitHunter":
      return countProgress(
        debateWinsForCog(events, cog.id, (event) => opponentHasTrait(snapshot, event, cog.id, achievement.parameters?.trait)),
        achievementRoundsTarget(achievement),
      );
    case "conversionWitnessStreak":
      return countProgress(convertedDebatersFromWitnessedDebates(events, cog.id).size, 2);
  }

  return countProgress(0, achievementProgressTarget(achievement));
}

function completedAchievementProgress(achievement: CompletedAchievement): AchievementProgress {
  const target = achievementProgressTarget(achievement);
  return { current: target, target };
}

function achievementProgressTarget(achievement: Pick<AchievementAssignment, "achievementId" | "parameters">): number {
  switch (achievement.achievementId) {
    case "debateThreeCogs":
    case "perfectDebate":
      return 3;
    case "flipFlop":
      return 2;
    case "debateMarathon":
      return 5;
    case "witnessTeamWins":
    case "roomSpecialist":
    case "traitNemesis":
      return achievementRoundsTarget(achievement);
    case "winFinalRound":
      return 5;
    case "defeatOpponentTwice":
      return 2;
    case "sweepDebate":
    case "winWithAllTactics":
    case "travelingDebater":
    case "socialCircuit":
    case "underdogWitness":
      return 3;
    case "finalRoundWitness":
      return 5;
    case "sameTacticSweep":
      return 3;
    case "traitHunter":
      return achievementRoundsTarget(achievement);
    case "conversionWitnessStreak":
      return 2;
    default:
      return 1;
  }
}

function achievementRoundsTarget(achievement: Pick<AchievementAssignment, "parameters">): number {
  return achievement.parameters?.rounds ?? 3;
}

function countProgress(current: number | unknown[], target: number): AchievementProgress {
  const value = Array.isArray(current) ? current.length : current;
  return {
    current: Math.min(Math.max(0, Math.floor(value)), target),
    target,
  };
}

function formatAchievementProgress(progress: AchievementProgress): string {
  return `${formatNumber(progress.current)}/${formatNumber(progress.target)}`;
}

function achievementWindowEvents(achievement: AchievementAssignment, snapshot: WorldSnapshot): WorldEvent[] {
  return snapshot.recentEvents.filter(
    (event) => event.tick >= achievement.assignedTick && event.tick <= snapshot.tick,
  );
}

function colorChangeEventsForCog(events: WorldEvent[], cogId: string): WorldEvent[] {
  return events.filter((event) => event.type === "colorChange" && event.actorId === cogId);
}

function isDebateParticipant(event: WorldEvent, cogId: string): boolean {
  return Boolean(event.debate?.actions.some((action) => action.cogId === cogId));
}

function debateWinsForCog(
  events: WorldEvent[],
  cogId: string,
  predicate: (event: WorldEvent) => boolean = () => true,
): WorldEvent[] {
  return events.filter((event) => event.type === "debateExchange" && event.debate?.winnerCogId === cogId && predicate(event));
}

function debateLossesForCog(
  events: WorldEvent[],
  cogId: string,
  predicate: (event: WorldEvent) => boolean = () => true,
): WorldEvent[] {
  return events.filter(
    (event) => event.type === "debateExchange" && Boolean(event.debate?.winnerCogId) && event.debate?.winnerCogId !== cogId &&
      isDebateParticipant(event, cogId) && predicate(event),
  );
}

function witnessedWinsForCog(
  events: WorldEvent[],
  cogId: string,
  predicate: (event: WorldEvent) => boolean,
): WorldEvent[] {
  return events.filter(
    (event) => event.type === "debateExchange" && event.debate?.witnessCogIds?.includes(cogId) === true && predicate(event),
  );
}

function witnessedDebatesForCog(events: WorldEvent[], cogId: string): WorldEvent[] {
  return events.filter((event) => event.type === "debateExchange" && event.debate?.witnessCogIds?.includes(cogId) === true);
}

function debateOpponentIdsForCog(events: WorldEvent[], cogId: string): Set<string> {
  const opponentIds = new Set<string>();
  for (const event of events) {
    if (event.type !== "debateExchange" || !isDebateParticipant(event, cogId)) {
      continue;
    }
    for (const action of event.debate?.actions ?? []) {
      if (action.cogId !== cogId) {
        opponentIds.add(action.cogId);
      }
    }
  }
  return opponentIds;
}

function debateOpponentId(event: WorldEvent, cogId: string): string | undefined {
  return event.debate?.actions.find((action) => action.cogId !== cogId)?.cogId;
}

function maxDebateRoundForCog(events: WorldEvent[], cogId: string): number {
  return events.reduce(
    (maxRound, event) =>
      event.type === "debateExchange" && isDebateParticipant(event, cogId)
        ? Math.max(maxRound, event.debate?.round ?? 0)
        : maxRound,
    0,
  );
}

function maxWinningDebateRoundForCog(events: WorldEvent[], cogId: string): number {
  return debateWinsForCog(events, cogId).reduce((maxRound, event) => Math.max(maxRound, event.debate?.round ?? 0), 0);
}

function maxWitnessedDebateRoundForCog(events: WorldEvent[], cogId: string): number {
  return witnessedDebatesForCog(events, cogId).reduce((maxRound, event) => Math.max(maxRound, event.debate?.round ?? 0), 0);
}

function debateRoomKind(snapshot: WorldSnapshot, event: WorldEvent): string | undefined {
  if (event.debate?.roomKind) {
    return event.debate.roomKind;
  }
  const participantIds = event.debate?.actions.map((action) => action.cogId) ?? [];
  const participants = participantIds.flatMap((id) => snapshot.cogs.find((cog) => cog.id === id) ?? []);
  const roomId = participants[0]?.location?.roomId;
  if (!roomId || participants.some((cog) => cog.location?.roomId !== roomId)) {
    return undefined;
  }
  return snapshot.venue?.rooms.find((room) => room.id === roomId)?.kind;
}

function winnerHasTrait(snapshot: WorldSnapshot, event: WorldEvent, trait: AchievementParameters["trait"]): boolean {
  const winnerId = event.debate?.winnerCogId;
  const winner = winnerId ? snapshot.cogs.find((cog) => cog.id === winnerId) : undefined;
  return Boolean(trait && winner && (winner.activeTrait === trait || winner.defensiveTrait === trait));
}

function opponentHasTrait(snapshot: WorldSnapshot, event: WorldEvent, cogId: string, trait: AchievementParameters["trait"]): boolean {
  const opponent = snapshot.cogs.find((candidate) => candidate.id === debateOpponentId(event, cogId));
  return Boolean(trait && opponent && (opponent.activeTrait === trait || opponent.defensiveTrait === trait));
}

function largestWinCountAgainstOneOpponent(events: WorldEvent[], cogId: string): number {
  const counts = new Map<string, number>();
  for (const event of debateWinsForCog(events, cogId)) {
    const opponent = debateOpponentId(event, cogId);
    if (opponent) {
      counts.set(opponent, (counts.get(opponent) ?? 0) + 1);
    }
  }
  return Math.max(0, ...counts.values());
}

function smallerTeam(snapshot: WorldSnapshot): AchievementParameters["team"] | undefined {
  const [first, second] = TEAM_COLORS.map((color) => ({
    color,
    count: snapshot.cogs.filter((cog) => cog.color === color).length,
  })).sort((a, b) => a.count - b.count);
  return first && second && first.count < second.count ? first.color : undefined;
}

export function renderConfigPage(payload: ConfigPayload, activeTab: ConfigTab, snapshot?: WorldSnapshot): string {
  const achievementCounts = achievementCountsByRuleKey(snapshot);
  const timingParameters = payload.parameters.filter(isTimingParameter);
  const gameParameters = payload.parameters.filter((parameter) => !isTimingParameter(parameter));

  return `
    <section class="config-page" aria-label="Game config page">
      <div class="config-page-scroll">
        <header class="config-hero">
          <button class="profile-close-button" data-action="close-config" type="button">Close</button>
          <div>
            <h1>Config</h1>
            <p>Rules, timing, trait modifiers, and achievements.</p>
          </div>
        </header>

        ${renderSettingsPresetControls(payload)}

        <nav class="config-tabs" role="tablist" aria-label="Settings sections">
          ${renderConfigTabButton("params", "Params", activeTab)}
          ${renderConfigTabButton("timing", "Timing", activeTab)}
          ${renderConfigTabButton("traits", "Traits", activeTab)}
          ${renderConfigTabButton("achievements", "Achievements", activeTab)}
          ${renderConfigTabButton("debates", "Debates", activeTab)}
          ${renderConfigTabButton("venue", "Venue", activeTab)}
        </nav>

        <div class="config-tab-panels">
          <section
            class="config-block config-tab-panel"
            aria-label="Params"
            id="config-tabpanel-params"
            role="tabpanel"
            ${activeTab === "params" ? "" : "hidden"}
          >
            <div class="profile-block-header">
              <span>Game Parameters</span>
              <span>${escapeHtml(String(gameParameters.length))}</span>
            </div>
            <div class="config-parameter-list">
              ${gameParameters.map((parameter) => renderConfigParameter(parameter, payload.config)).join("")}
            </div>
          </section>

          <section
            class="config-block config-tab-panel"
            aria-label="Timing"
            id="config-tabpanel-timing"
            role="tabpanel"
            ${activeTab === "timing" ? "" : "hidden"}
          >
            <div class="profile-block-header">
              <span>Timing</span>
              <span>${escapeHtml(String(timingParameters.length))}</span>
            </div>
            <div class="config-parameter-list config-timing-list">
              ${timingParameters.map((parameter) => renderTimingConfigParameter(parameter, payload.config)).join("")}
            </div>
          </section>

          <section
            class="config-block config-tab-panel"
            aria-label="Traits"
            id="config-tabpanel-traits"
            role="tabpanel"
            ${activeTab === "traits" ? "" : "hidden"}
          >
            <div class="profile-block-header">
              <span>Traits</span>
              <span>${escapeHtml(String(payload.traits.length))}</span>
            </div>
            <div class="config-rule-list">
              ${payload.traits.map((trait) => renderTraitRule(trait, payload.config)).join("")}
            </div>
          </section>

          <section
            class="config-block config-tab-panel"
            aria-label="Achievements"
            id="config-tabpanel-achievements"
            role="tabpanel"
            ${activeTab === "achievements" ? "" : "hidden"}
          >
            <div class="profile-block-header">
              <span>Achievements</span>
              <span>${escapeHtml(String(payload.achievements.length))}</span>
            </div>
            <div class="config-rule-list">
              ${payload.achievements.map((rule) => renderAchievementRule(rule, achievementCounts.get(achievementKey(rule)))).join("")}
            </div>
          </section>

          <section
            class="config-block config-tab-panel"
            aria-label="Debates"
            id="config-tabpanel-debates"
            role="tabpanel"
            ${activeTab === "debates" ? "" : "hidden"}
          >
            <div class="profile-block-header">
              <span>Debates</span>
              <span>${escapeHtml(String(snapshot?.debateLog?.length ?? 0))}</span>
            </div>
            ${renderDebateLog(snapshot?.debateLog ?? [])}
          </section>

          <section
            class="config-block config-tab-panel config-venue-panel"
            aria-label="Venue"
            id="config-tabpanel-venue"
            role="tabpanel"
            ${activeTab === "venue" ? "" : "hidden"}
          >
            <div class="profile-block-header">
              <span>Venue</span>
              <span>Editor</span>
            </div>
            <div data-venue-editor-host></div>
          </section>
        </div>
      </div>
    </section>
  `;
}

function renderSettingsPresetControls(payload: ConfigPayload): string {
  const presets = payload.presets ?? [];
  if (presets.length === 0) {
    return "";
  }

  const currentSettingsDb = payload.settingsDb ?? presets[0]?.settingsDb ?? "";
  return `
    <section class="config-preset-bar" aria-label="Settings presets">
      <div class="config-preset-picker" role="group" aria-label="Settings DB">
        <span class="config-preset-label">Settings DB</span>
        <div class="config-preset-list">
          ${presets.map((preset) => renderSettingsPresetButton(preset, preset.settingsDb === currentSettingsDb)).join("")}
        </div>
      </div>
      <form class="config-preset-create" data-settings-preset-form>
        <input
          aria-label="New settings preset name"
          data-settings-preset-name
          name="settingsPresetName"
          placeholder="New preset name"
          type="text"
        />
        <button type="submit">Create</button>
      </form>
    </section>
  `;
}

function renderSettingsPresetButton(
  preset: NonNullable<ConfigPayload["presets"]>[number],
  selected: boolean,
): string {
  return `
    <button
      aria-pressed="${selected ? "true" : "false"}"
      class="config-preset-button${selected ? " is-selected" : ""}"
      data-settings-preset-choice="${escapeHtml(preset.settingsDb)}"
      type="button"
    >
      <span>${escapeHtml(preset.name)}</span>
      <small>${escapeHtml(preset.settingsDb)}</small>
    </button>
  `;
}

function renderConfigTabButton(tab: ConfigTab, label: string, activeTab: ConfigTab): string {
  const selected = tab === activeTab;
  return `
    <button
      aria-controls="config-tabpanel-${escapeHtml(tab)}"
      aria-selected="${selected ? "true" : "false"}"
      class="config-tab${selected ? " is-selected" : ""}"
      data-config-tab="${escapeHtml(tab)}"
      role="tab"
      type="button"
    >${escapeHtml(label)}</button>
  `;
}

function renderConfigParameter(parameter: RuleParameter, config: GameConfig): string {
  const value = config[parameter.key];
  return `
    <label class="config-parameter">
      <span class="config-parameter-copy">
        <strong>${escapeHtml(parameter.label)}</strong>
        <span>${escapeHtml(parameter.description)}</span>
      </span>
      <input
        data-config-key="${escapeHtml(parameter.key)}"
        max="${escapeHtml(String(parameter.max))}"
        min="${escapeHtml(String(parameter.min))}"
        step="${escapeHtml(String(parameter.step))}"
        type="number"
        value="${escapeHtml(String(value))}"
      />
    </label>
  `;
}

function renderTimingConfigParameter(parameter: RuleParameter & { key: TimingParameterKey }, config: GameConfig): string {
  const ticks = config[parameter.key];
  const seconds = ticksToSeconds(ticks);
  return `
    <label class="config-parameter config-timing-parameter">
      <span class="config-parameter-copy">
        <strong>${escapeHtml(timingParameterLabel(parameter.key))}</strong>
        <span>${escapeHtml(timingParameterDescription(parameter.key))}</span>
        <span class="config-parameter-meta">${escapeHtml(formatTickMeta(ticks))}</span>
      </span>
      <input
        aria-label="${escapeHtml(`${timingParameterLabel(parameter.key)} seconds`)}"
        data-config-seconds-key="${escapeHtml(parameter.key)}"
        max="${escapeHtml(formatSeconds(ticksToSeconds(parameter.max)))}"
        min="${escapeHtml(formatSeconds(ticksToSeconds(parameter.min)))}"
        step="${escapeHtml(formatSeconds(Math.max(SIMULATION_TICK_SECONDS * parameter.step, SIMULATION_TICK_SECONDS)))}"
        type="number"
        value="${escapeHtml(formatSeconds(seconds))}"
      />
    </label>
  `;
}

function renderTraitRule(rule: TraitRule, config: GameConfig): string {
  const parameters = rule.parameters?.length
    ? `<div class="config-trait-parameters">
        ${rule.parameters.map((parameter) => renderTraitParameter(rule, parameter, config)).join("")}
      </div>`
    : "";
  return `
    <article class="config-rule">
      <div class="config-rule-title">
        <strong>${escapeHtml(rule.label)}</strong>
        <span>Trait</span>
      </div>
      <p><strong>Player:</strong> ${escapeHtml(traitPlayerDescription(rule, config))}</p>
      <p><strong>Guidance:</strong> ${escapeHtml(traitPromptDescription(rule, config))}</p>
      ${parameters}
    </article>
  `;
}

function renderTraitParameter(rule: TraitRule, parameter: TraitParameter, config: GameConfig): string {
  const value = (config.traitConfig[rule.id] as Record<string, number>)[parameter.key] ?? 0;
  return `
    <label class="config-parameter config-trait-parameter">
      <span class="config-parameter-copy">
        <strong>${escapeHtml(parameter.label)}</strong>
        <span>${escapeHtml(parameter.description)}</span>
      </span>
      <input
        data-trait-config-id="${escapeHtml(rule.id)}"
        data-trait-config-key="${escapeHtml(parameter.key)}"
        max="${escapeHtml(String(parameter.max))}"
        min="${escapeHtml(String(parameter.min))}"
        step="${escapeHtml(String(parameter.step))}"
        type="number"
        value="${escapeHtml(String(value))}"
      />
    </label>
  `;
}

function renderAchievementRule(rule: AchievementRule, counts: AchievementCount | undefined): string {
  const timeoutSeconds = `${formatSeconds(ticksToSeconds(rule.timeoutTicks))}s`;
  const achievementCounts = counts ?? emptyAchievementCount(rule);
  return `
    <article class="config-rule config-achievement-rule">
      <div class="config-rule-title">
        <strong>${escapeHtml(rule.label)}</strong>
        <div class="config-achievement-meta" aria-label="Achievement timing and points">
          <span>${escapeHtml(timeoutSeconds)}</span>
          <span>${escapeHtml(String(rule.points))} pts</span>
        </div>
      </div>
      <p>${escapeHtml(rule.description)}</p>
      <div class="config-condition">${escapeHtml(rule.condition)}</div>
      <div class="config-achievement-counts" aria-label="Achievement counts">
        <span>assigned ${escapeHtml(String(achievementCounts.assigned))}</span>
        <span>completed ${escapeHtml(String(achievementCounts.completed))}</span>
        <span>current ${escapeHtml(String(achievementCounts.current))}</span>
        <span>expired ${escapeHtml(String(achievementCounts.expired))}</span>
      </div>
    </article>
  `;
}

function renderDebateLog(entries: DebateLogEntry[]): string {
  if (entries.length === 0) {
    return `<div class="profile-empty-state">No debates logged yet.</div>`;
  }

  return `
    <div class="config-debate-log">
      ${[...entries].reverse().map(renderDebateLogEntry).join("")}
    </div>
  `;
}

function renderDebateLogEntry(entry: DebateLogEntry): string {
  const conversions = entry.conversions.length
    ? entry.conversions.map(renderDebateConversion).join("")
    : `<span class="config-debate-muted">no color conversions</span>`;

  return `
    <article class="config-debate-entry">
      <div class="config-debate-heading">
        <div class="config-debate-title">
          <strong>${entry.actions.map((action) => escapeHtml(action.cogName)).join(" vs ")}</strong>
          <span>t${escapeHtml(String(entry.tick))}</span>
          <span>round ${escapeHtml(String(entry.round))}</span>
          <span>${escapeHtml(entry.outcome)}</span>
        </div>
        <div class="config-debate-actions">
          ${entry.actions.map(renderDebateLogAction).join("")}
        </div>
      </div>
      <div class="config-debate-changes">
        ${entry.changes.map(renderDebateChange).join("")}
      </div>
      <div class="config-debate-conversions">
        ${conversions}
      </div>
    </article>
  `;
}

function renderDebateLogAction(action: DebateLogEntry["actions"][number]): string {
  return `
    <span class="config-debate-play" data-team-color="${escapeHtml(action.color)}">
      <strong>${escapeHtml(action.cogName)}</strong>
      <span>${escapeHtml(action.tactic)}</span>
    </span>
  `;
}

function renderDebateChange(change: DebateLogEntry["changes"][number]): string {
  return `
    <span class="config-debate-change">
      <strong>${escapeHtml(change.cogName)}</strong>
      <span>${escapeHtml(change.role)}</span>
      <span>certainty ${escapeHtml(formatSignedNumber(change.certaintyDelta))}</span>
      <span>${escapeHtml(formatNumber(change.certaintyBefore))} -> ${escapeHtml(formatNumber(change.certaintyAfter))}</span>
    </span>
  `;
}

function renderDebateConversion(conversion: DebateLogEntry["conversions"][number]): string {
  return `
    <span class="config-debate-conversion">
      <strong>${escapeHtml(conversion.cogName)}</strong>
      <span>${escapeHtml(conversion.fromColor)} -> ${escapeHtml(conversion.toColor)}</span>
    </span>
  `;
}

function formatSignedNumber(value: number): string {
  return `${value >= 0 ? "+" : ""}${formatNumber(value)}`;
}

function titleCase(value: string): string {
  return `${value.slice(0, 1).toUpperCase()}${value.slice(1)}`;
}

function sentenceCase(value: string): string {
  const trimmed = value.trim();
  return `${trimmed.slice(0, 1).toUpperCase()}${trimmed.slice(1)}`;
}

function formatNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/\.?0+$/, "");
}

function formatScore(value: number): string {
  return String(Math.round(Number.isFinite(value) ? value : 0));
}

function formatPersonalScore(value: number): string {
  return formatScore(value * PERSONAL_SCORE_DISPLAY_MULTIPLIER);
}

function achievementCountsByRuleKey(snapshot: WorldSnapshot | undefined): Map<string, AchievementCount> {
  const countsByKey = new Map<string, AchievementCount>();
  const templateCounts = new Map<AchievementCount["achievementId"], AchievementCount>();
  for (const count of snapshot?.achievementCounts ?? []) {
    countsByKey.set(achievementKey(count), count);
    const current = templateCounts.get(count.achievementId) ?? {
      achievementId: count.achievementId,
      assigned: 0,
      completed: 0,
      current: 0,
      expired: 0,
    };
    current.assigned += count.assigned;
    current.completed += count.completed;
    current.current += count.current;
    current.expired += count.expired;
    templateCounts.set(count.achievementId, current);
  }
  for (const count of templateCounts.values()) {
    countsByKey.set(count.achievementId, count);
  }
  return countsByKey;
}

function emptyAchievementCount(rule: AchievementRule): AchievementCount {
  return {
    achievementId: rule.id,
    parameters: rule.parameters,
    assigned: 0,
    completed: 0,
    current: 0,
    expired: 0,
  };
}

function isTimingParameter(parameter: RuleParameter): parameter is RuleParameter & { key: TimingParameterKey } {
  return isTimingParameterKey(parameter.key);
}

function isTimingParameterKey(value: string | undefined): value is TimingParameterKey {
  return TIMING_PARAMETER_KEYS.includes(value as TimingParameterKey);
}

function ticksToSeconds(ticks: number): number {
  return ticks * SIMULATION_TICK_SECONDS;
}

function secondsToTicks(seconds: number, parameter: RuleParameter | undefined): number {
  const rawTicks = seconds / SIMULATION_TICK_SECONDS;
  const step = parameter?.step ?? 1;
  const steppedTicks = Math.round(rawTicks / step) * step;
  const min = parameter?.min ?? 0;
  const max = parameter?.max ?? Number.POSITIVE_INFINITY;

  return Math.max(min, Math.min(max, Math.round(steppedTicks)));
}

function formatSeconds(seconds: number): string {
  return Number.isInteger(seconds) ? String(seconds) : seconds.toFixed(3).replace(/\.?0+$/, "");
}

function formatTickMeta(ticks: number): string {
  return `${ticks} ticks at ${SIMULATION_STEPS_PER_SECOND} tps`;
}

function renderLlmTimeoutMeter(serverStatus: ServerStatus | undefined): string {
  const decisions = serverStatus?.llmMoveDecisions ?? 0;
  const timedOutMoves = serverStatus?.llmTimedOutMoves ?? 0;
  const percent = serverStatus?.llmTimedOutMovePercent ?? 0;
  return `
    <div
      aria-label="${escapeHtml(`LLM move timeouts ${percent}% (${timedOutMoves} of ${decisions})`)}"
      class="llm-timeout-meter"
    >
      <span>LLM move timeouts</span>
      <strong>${escapeHtml(String(percent))}%</strong>
      <span>${escapeHtml(String(timedOutMoves))} / ${escapeHtml(String(decisions))}</span>
    </div>
  `;
}

function renderShortcutsPanel(): string {
  const shortcuts: Array<[string, string]> = [
    ["F1", "Shortcuts"],
    ["Cmd-G", "Controls"],
    ["Cmd-R", "Roster"],
    ["Cmd-B", "QR code"],
    ["Cmd-D", "Disco"],
    ["Cmd-S", "Shuffle teams"],
    ["Space", "Play/pause"],
    ["W A S D", "Move selected cog"],
  ];

  return `
    <section class="shortcuts-panel" aria-label="Keyboard shortcuts">
      <div class="shortcuts-panel-title">Shortcuts</div>
      <dl class="shortcuts-list">
        ${shortcuts.map(([shortcut, label]) => `
          <div class="shortcuts-row">
            <dt><kbd>${escapeHtml(shortcut)}</kbd></dt>
            <dd>${escapeHtml(label)}</dd>
          </div>
        `).join("")}
      </dl>
    </section>
  `;
}

function timingParameterLabel(key: TimingParameterKey): string {
  switch (key) {
    case "debatePrepTicks":
      return "Debate prep";
    case "debateChoiceRevealTicks":
      return "Choice reveal";
    case "debateResultTicks":
      return "Result reveal";
    case "debateCooldownTicks":
      return "Repeat argument cooldown";
    case "roomMoveCooldownTicks":
      return "Room move cooldown";
  }
}

function timingParameterDescription(key: TimingParameterKey): string {
  switch (key) {
    case "debatePrepTicks":
      return "Seconds before tactic choices are revealed.";
    case "debateChoiceRevealTicks":
      return "Seconds tactic choices stay visible before highlighting the result.";
    case "debateResultTicks":
      return "Seconds the round result stays visible before the next prep phase.";
    case "debateCooldownTicks":
      return "Seconds before the same two cogs are allowed to argue again.";
    case "roomMoveCooldownTicks":
      return "Seconds after entering a room before a cog can leave while other cogs are present.";
  }
}

function renderProfileStat(label: string, value: string, meta: string): string {
  return `
    <div class="profile-stat">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <span>${escapeHtml(meta)}</span>
    </div>
  `;
}

function debateRecordMeta(cog: CogSnapshot): string {
  const total = cog.stats.argumentsWon + cog.stats.argumentsLost;
  if (total === 0) {
    return "no debates";
  }

  return `${Math.round((cog.stats.argumentsWon / total) * 100)}% win`;
}

function renderProfileTraitPills(cog: CogSnapshot): string {
  return `
    ${renderReadOnlyTraitBadge("defensiveTrait", cog.defensiveTrait)}
    ${renderReadOnlyTraitBadge("activeTrait", cog.activeTrait)}
  `;
}

function profileLocationLabel(cog: CogSnapshot, snapshot: WorldSnapshot): string {
  if (!cog.location) {
    return `${cog.position.x},${cog.position.y}`;
  }

  const spot = snapshot.venue?.spots.find(
    (candidate) => candidate.roomId === cog.location?.roomId && candidate.id === cog.location.spotId,
  );
  const room = venueLocationPartLabel(roomDisplayName(cog.location.roomId, snapshot));
  const spotName = venueLocationPartLabel(spot?.label ?? cog.location.spotId);
  return `${room} / ${spotName}`;
}

function venueLocationPartLabel(value: string): string {
  const cleaned = value.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  if (!cleaned) {
    return value;
  }

  return cleaned
    .split(" ")
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function renderProfileAvatar(cog: CogSnapshot): string {
  const spriteUrl = cogSpriteUrl(cog);
  if (spriteUrl) {
    return `<img alt="" src="${escapeHtml(spriteUrl)}" />`;
  }

  return escapeHtml(initials(cog.name));
}

function cogEvents(events: WorldEvent[], cogId: string): WorldEvent[] {
  return events
    .filter((event) => event.actorId === cogId || event.targetId === cogId)
    .slice()
    .sort((left, right) => right.tick - left.tick);
}

function mobileProfileActionEvents(cog: CogSnapshot, snapshot: WorldSnapshot, recentEvents: WorldEvent[]): WorldEvent[] {
  const actionEvents = conversationActionEvents(cog, snapshot, recentEvents);
  return [...recentEvents, ...actionEvents].sort((left, right) => right.tick - left.tick || right.id.localeCompare(left.id));
}

function conversationActionEvents(cog: CogSnapshot, snapshot: WorldSnapshot, recentEvents: WorldEvent[]): WorldEvent[] {
  return cog.conversationLog.flatMap((message) => {
    if (message.role !== "assistant") {
      return [];
    }

    const action = parseLogAction(message.content);
    if (!action || recentEvents.some((event) => event.tick === message.tick && event.actorId === cog.id)) {
      return [];
    }

    return [conversationActionEvent(cog, snapshot, message, action)];
  });
}

function conversationActionEvent(
  cog: CogSnapshot,
  snapshot: WorldSnapshot,
  message: CogConversationMessage,
  action: ParsedLogAction,
): WorldEvent {
  return {
    actorId: cog.id,
    id: `conversation-action-${message.id}`,
    message: conversationActionMessage(snapshot, action),
    tick: message.tick,
    type: conversationActionEventType(action),
  };
}

function conversationActionEventType(action: ParsedLogAction): WorldEvent["type"] {
  switch (action.type) {
    case "move":
      return "move";
    case "debate":
      return "debateStart";
    case "chooseTactic":
      return "debateExchange";
    case "wait":
      return "gameFlow";
  }
}

function conversationActionMessage(snapshot: WorldSnapshot, action: ParsedLogAction): string {
  const steerText = playerSteerText(action.intent);
  if (action.type === "wait") {
    return steerText ? `Cue loaded: ${steerText}` : action.intent ? `Wait: ${action.intent}` : "Waited.";
  }

  if (action.type === "move") {
    const destination = action.roomId ? venueRoomLabel(snapshot, action.roomId) : action.direction;
    return destination
      ? `Moved toward ${destination}${action.intent ? `: ${action.intent}` : ""}`
      : `Moved${action.intent ? `: ${action.intent}` : ""}`;
  }

  if (action.type === "debate") {
    const target = action.targetId ? cogNameById(snapshot, action.targetId) : undefined;
    return target ? `Started an argument with ${target}.` : "Started an argument.";
  }

  if (action.type === "chooseTactic") {
    return action.tactic ? `Chose ${action.tactic} for the argument.` : "Chose an argument tactic.";
  }

  return summarizeAction(action);
}

function venueRoomLabel(snapshot: WorldSnapshot, roomId: string): string {
  return snapshot.venue?.rooms.find((room) => room.id === roomId)?.label ?? roomId;
}

function cogNameById(snapshot: WorldSnapshot, cogId: string): string {
  return snapshot.cogs.find((cog) => cog.id === cogId)?.name ?? cogId;
}

export function buildDiaryRoomEntries(cog: CogSnapshot, snapshot: WorldSnapshot): DiaryRoomEntry[] {
  const historyEntries = diaryRoomEntriesFromHistory(cog, snapshot);
  if (historyEntries.length > 0) {
    appendRecentEventsToDiaryEntries(cog, snapshot, historyEntries);
    appendPersistentDebateLogEntries(cog, snapshot, historyEntries);
    return sortDiaryRoomEntries(historyEntries);
  }

  const entries: DiaryRoomEntry[] = [];
  let current: DiaryRoomEntry | undefined;

  for (const event of snapshot.recentEvents.slice().sort((left, right) => left.tick - right.tick)) {
    const roomId = diaryRoomIdForEvent(event, snapshot);
    const selectedArrival = event.actorId === cog.id && isDiaryArrivalEvent(event);
    const selectedDeparture = event.actorId === cog.id && isDiaryDepartureEvent(event);
    const selectedDebateParticipant = diaryDebateParticipantIds(event).includes(cog.id);
    const selectedDebateWitness = diaryDebateWitnessIds(event).includes(cog.id) && !selectedDebateParticipant;
    const selectedAchievement = event.actorId === cog.id && isDiaryAchievementEvent(event);
    const selectedReferenced =
      (event.actorId === cog.id && (isDiaryMoveEvent(event) || event.type === "colorChange")) ||
      selectedDebateParticipant ||
      selectedDebateWitness ||
      selectedAchievement;

    if (roomId && selectedArrival) {
      if (!current) {
        current = startDiaryRoomEntry(entries, cog.id, roomId, event, snapshot);
      } else if (current.roomId !== roomId) {
        closeDiaryRoomEntry(current, event.tick);
        current = startDiaryRoomEntry(entries, cog.id, roomId, event, snapshot);
      }
    } else if (roomId && !current && selectedReferenced) {
      current = startDiaryRoomEntry(entries, cog.id, roomId, event, snapshot);
    } else if (roomId && current && current.roomId !== roomId && selectedReferenced) {
      closeDiaryRoomEntry(current, event.tick);
      current = startDiaryRoomEntry(entries, cog.id, roomId, event, snapshot);
    }

    if (!current || !roomId || current.roomId !== roomId) {
      continue;
    }

    appendDiaryRoomEvent(current, event, cog.id, snapshot);

    if (selectedDeparture && diaryMoveLeavesRoom(event, current.roomId, snapshot)) {
      closeDiaryRoomEntry(current, event.tick);
      current = undefined;
    }
  }

  appendPersistentDebateLogEntries(cog, snapshot, entries);

  return sortDiaryRoomEntries(entries);
}

function diaryRoomEntriesFromHistory(cog: CogSnapshot, snapshot: WorldSnapshot): DiaryRoomEntry[] {
  const history = normalizedDiaryRoomHistory(cog, snapshot);
  return history.slice(-DIARY_INITIAL_ROOM_LIMIT).map((entry, index) => ({
    id: `${cog.id}-${entry.roomId}-${entry.enteredTick}-${index}`,
    roomId: entry.roomId,
    roomLabel: diaryRoomLabel(entry.roomId, snapshot),
    enterTick: entry.enteredTick,
    leaveTick: entry.leftTick,
    events: [],
    flips: [],
    achievements: [],
    debateResults: [],
    witnessedDebates: [],
    people: [],
    roomCogs: snapshot.cogs
      .filter((candidate) => candidate.location?.roomId === entry.roomId)
      .map(diaryCogRef),
  }));
}

function normalizedDiaryRoomHistory(cog: CogSnapshot, snapshot: WorldSnapshot): DiaryRoomHistoryEntry[] {
  if (!cog.roomHistory || cog.roomHistory.length === 0) {
    return [];
  }

  const history = [...(cog.roomHistory ?? [])]
    .filter(isValidCogRoomHistoryEntry)
    .sort((left, right) => left.enteredTick - right.enteredTick);
  const latest = history[history.length - 1];
  if (cog.location && (!latest || latest.roomId !== cog.location.roomId || latest.leftTick !== undefined)) {
    history.push({
      roomId: cog.location.roomId,
      spotId: cog.location.spotId,
      enteredTick: typeof cog.lastVenueMoveTick === "number" ? cog.lastVenueMoveTick : snapshot.tick,
    });
  }

  return history;
}

function appendRecentEventsToDiaryEntries(cog: CogSnapshot, snapshot: WorldSnapshot, entries: DiaryRoomEntry[]): void {
  for (const event of snapshot.recentEvents.slice().sort((left, right) => left.tick - right.tick)) {
    const roomId = diaryRoomIdForEvent(event, snapshot);
    if (!roomId) {
      continue;
    }

    const entry = entries.find(
      (candidate) =>
        candidate.roomId === roomId &&
        event.tick >= candidate.enterTick &&
        (candidate.leaveTick === undefined || event.tick <= candidate.leaveTick),
    );
    if (entry) {
      appendDiaryRoomEvent(entry, event, cog.id, snapshot);
    }
  }
}

function sortDiaryRoomEntries(entries: DiaryRoomEntry[]): DiaryRoomEntry[] {
  return entries.sort((left, right) => left.enterTick - right.enterTick).reverse();
}

function startDiaryRoomEntry(
  entries: DiaryRoomEntry[],
  cogId: string,
  roomId: string,
  event: WorldEvent,
  snapshot: WorldSnapshot,
): DiaryRoomEntry {
  const entry: DiaryRoomEntry = {
    id: `${cogId}-${roomId}-${event.tick}-${entries.length}`,
    roomId,
    roomLabel: diaryRoomLabel(roomId, snapshot),
    enterTick: event.tick,
    leaveTick: undefined,
    events: [],
    flips: [],
    achievements: [],
    debateResults: [],
    witnessedDebates: [],
    people: [],
    roomCogs: snapshot.cogs
      .filter((candidate) => candidate.location?.roomId === roomId)
      .map(diaryCogRef),
  };
  entries.push(entry);
  return entry;
}

function closeDiaryRoomEntry(entry: DiaryRoomEntry, tick: number): void {
  entry.leaveTick = entry.leaveTick === undefined ? tick : Math.max(entry.leaveTick, tick);
}

function appendDiaryRoomEvent(entry: DiaryRoomEntry, event: WorldEvent, cogId: string, snapshot: WorldSnapshot): void {
  if (isDiaryAchievementEvent(event)) {
    entry.achievements.push(event);
    entry.events.push({ event, kind: "achievement" });
    return;
  }

  if (event.type === "colorChange") {
    entry.flips.push(event);
    entry.events.push({ event, kind: "flip" });
    return;
  }

  if (event.type === "debateExchange") {
    if (diaryDebateParticipantIds(event).includes(cogId)) {
      entry.debateResults.push(event);
      entry.events.push({ event, kind: "debate" });
      return;
    }

    if (diaryDebateWitnessIds(event).includes(cogId)) {
      entry.witnessedDebates.push(event);
      entry.events.push({ event, kind: "witness" });
      return;
    }
    return;
  }

  if (isDiaryMoveEvent(event)) {
    const actor = event.actorId ? snapshot.cogs.find((candidate) => candidate.id === event.actorId) : undefined;
    entry.people.push(event);
    entry.events.push({ actor: actor ? diaryCogRef(actor) : undefined, event, kind: "person" });
  }
}

function diaryCogRef(cog: CogSnapshot): DiaryCogRef {
  return {
    id: cog.id,
    name: cog.name,
    color: cog.color,
    spriteSheetKey: cog.spriteSheetKey,
    spriteUrl: cog.spriteUrl,
    spriteUrls: cog.spriteUrls,
  };
}

function appendPersistentDebateLogEntries(cog: CogSnapshot, snapshot: WorldSnapshot, entries: DiaryRoomEntry[]): void {
  for (const debate of [...(snapshot.debateLog ?? [])].sort((left, right) => left.tick - right.tick)) {
    const participated = diaryDebateLogParticipantIds(debate).includes(cog.id);
    const witnessed = !participated && diaryDebateLogWitnessIds(debate).includes(cog.id);
    if (!participated && !witnessed) {
      continue;
    }

    const event = diaryEventFromDebateLog(debate);
    if (enrichDiaryDebateEvent(entries, event)) {
      continue;
    }

    const entry = diaryEntryForTick(entries, debate.tick);
    if (!entry) {
      continue;
    }

    if (participated) {
      entry.debateResults.push(event);
      entry.events.push({ event, kind: "debate" });
    } else {
      entry.witnessedDebates.push(event);
      entry.events.push({ event, kind: "witness" });
    }
  }
}

function diaryEntryForTick(entries: DiaryRoomEntry[], tick: number): DiaryRoomEntry | undefined {
  return entries.find((entry) => tick >= entry.enterTick && (entry.leaveTick === undefined || tick <= entry.leaveTick));
}

function diaryEventFromDebateLog(entry: DebateLogEntry): DiaryDebateEvent {
  const [first, second] = entry.actions;
  return {
    id: `diary-debate-${entry.id}`,
    tick: entry.tick,
    type: "debateExchange",
    actorId: first.cogId,
    targetId: second.cogId,
    message: diaryDebateLogMessage(entry),
    debate: {
      actions: entry.actions.map((action) => ({
        cogId: action.cogId,
        action: action.tactic,
      })) as NonNullable<WorldEvent["debate"]>["actions"],
      choicesRevealedAtTick: entry.tick,
      resultRevealedAtTick: entry.tick,
      expiresAtTick: entry.tick,
      outcome: entry.outcome,
      round: entry.round,
      winnerCogId: entry.winnerCogId,
      winnerColor: entry.winnerColor,
      witnessCogIds: diaryDebateLogWitnessIds(entry),
    },
    diaryDebateLog: entry,
  };
}

function diaryDebateLogMessage(entry: DebateLogEntry): string {
  const [first, second] = entry.actions;
  if (!entry.winnerCogId) {
    return `${first.cogName}'s ${titleCase(first.tactic)} tied ${second.cogName}'s ${titleCase(second.tactic)}.`;
  }

  const winner = entry.actions.find((action) => action.cogId === entry.winnerCogId) ?? first;
  const loser = winner.cogId === first.cogId ? second : first;
  return `${winner.cogName}'s ${titleCase(winner.tactic)} beat ${loser.cogName}'s ${titleCase(loser.tactic)}.`;
}

function enrichDiaryDebateEvent(entries: DiaryRoomEntry[], event: DiaryDebateEvent): boolean {
  for (const entry of entries) {
    let enriched = false;
    entry.events = entry.events.map((item) => {
      if ((item.kind === "debate" || item.kind === "witness") && diaryDebateEventsMatch(item.event, event)) {
        enriched = true;
        return { ...item, event };
      }

      return item;
    });

    if (!enriched) {
      continue;
    }

    entry.debateResults = entry.debateResults.map((existing) => diaryDebateEventsMatch(existing, event) ? event : existing);
    entry.witnessedDebates = entry.witnessedDebates.map((existing) => diaryDebateEventsMatch(existing, event) ? event : existing);
    return true;
  }

  return false;
}

function diaryDebateEventsMatch(left: WorldEvent, right: WorldEvent): boolean {
  if (left.id === right.id) {
    return true;
  }

  return left.tick === right.tick && left.debate?.round === right.debate?.round && diaryDebateActionKey(left) === diaryDebateActionKey(right);
}

function diaryDebateActionKey(event: WorldEvent): string {
  return (event.debate?.actions ?? [])
    .map((action) => `${action.cogId}:${action.action}`)
    .sort()
    .join("|");
}

function diaryRoomIdForEvent(event: WorldEvent, snapshot: WorldSnapshot): string | undefined {
  if (!event.position) {
    return undefined;
  }

  const exactSpot = snapshot.venue?.spots.find((spot) => sameDiaryPosition(spot.position, event.position));
  if (exactSpot) {
    return exactSpot.roomId;
  }

  const containingRoom = snapshot.venue?.rooms.find((room) => room.rect && diaryRectContains(room.rect, event.position));
  if (containingRoom) {
    return containingRoom.id;
  }

  return `position:${event.position.x},${event.position.y}`;
}

function diaryRoomLabel(roomId: string, snapshot: WorldSnapshot): string {
  if (roomId.startsWith("position:")) {
    return "Board";
  }

  return snapshot.venue?.rooms.find((room) => room.id === roomId)?.label ?? roomId;
}

function sameDiaryPosition(left: { x: number; y: number }, right: { x: number; y: number }): boolean {
  return Math.abs(left.x - right.x) < 0.001 && Math.abs(left.y - right.y) < 0.001;
}

function diaryRectContains(rect: { x: number; y: number; width: number; height: number }, position: { x: number; y: number }): boolean {
  return (
    position.x >= rect.x &&
    position.x <= rect.x + rect.width &&
    position.y >= rect.y &&
    position.y <= rect.y + rect.height
  );
}

function diaryDebateParticipantIds(event: WorldEvent): string[] {
  if (event.type !== "debateExchange") {
    return [];
  }

  const actionIds = event.debate?.actions.map((action) => action.cogId) ?? [];
  return Array.from(new Set([event.actorId, event.targetId, ...actionIds].filter((id): id is string => Boolean(id))));
}

function diaryDebateWitnessIds(event: WorldEvent): string[] {
  return event.type === "debateExchange" ? (event.debate?.witnessCogIds ?? []) : [];
}

function diaryDebateLogParticipantIds(entry: DebateLogEntry): string[] {
  return entry.actions.map((action) => action.cogId);
}

function diaryDebateLogWitnessIds(entry: DebateLogEntry): string[] {
  return entry.changes.filter((change) => change.role === "witness").map((change) => change.cogId);
}

function isDiaryMoveEvent(event: WorldEvent): boolean {
  return event.type === "move" && (isDiaryArrivalEvent(event) || isDiaryDepartureEvent(event));
}

function isDiaryAchievementEvent(event: WorldEvent): boolean {
  return event.type === "score" && /\bcompleted\b.+\bfor\s+\d+\s+points\b/i.test(event.message);
}

function isDiaryArrivalEvent(event: WorldEvent): boolean {
  return event.type === "move" && /\barrived at\b/i.test(event.message);
}

function isDiaryDepartureEvent(event: WorldEvent): boolean {
  return event.type === "move" && /\bstarted moving to\b/i.test(event.message);
}

function diaryMoveLeavesRoom(event: WorldEvent, roomId: string, snapshot: WorldSnapshot): boolean {
  const destinationRoomId = diaryMoveDestinationRoomId(event, snapshot);
  return destinationRoomId !== undefined && destinationRoomId !== roomId;
}

function diaryMoveDestinationRoomId(event: WorldEvent, snapshot: WorldSnapshot): string | undefined {
  const destinationLabel = diaryMoveDestinationLabel(event);
  if (!destinationLabel) {
    return undefined;
  }

  const matchingRoom = snapshot.venue?.rooms.find(
    (room) => destinationLabel === room.label || destinationLabel.startsWith(`${room.label} - `),
  );
  return matchingRoom?.id;
}

function diaryMoveDestinationLabel(event: WorldEvent): string | undefined {
  const match = event.message.match(/\b(?:started moving to|arrived at)\s+(.+)$/i);
  const destinationLabel = match?.[1]?.trim();
  return destinationLabel ? roomNameFromMoveDestination(destinationLabel) : undefined;
}

function renderEventFeed(events: WorldEvent[], emptyMessage: string): string {
  if (events.length === 0) {
    return `<div class="profile-empty-state">${escapeHtml(emptyMessage)}</div>`;
  }

  return `
    <div class="profile-event-list">
      ${events.map(renderEventItem).join("")}
    </div>
  `;
}

function renderEventItem(event: WorldEvent): string {
  const position = event.position ? `${event.position.x},${event.position.y}` : "board";

  return `
    <article class="profile-event-item" data-event-type="${escapeHtml(event.type)}">
      <div class="profile-event-marker" aria-hidden="true"></div>
      <div class="profile-event-copy">
        <div class="profile-event-meta">
          <span>t${escapeHtml(String(event.tick))}</span>
          <span>${escapeHtml(event.type)}</span>
          <span>${escapeHtml(position)}</span>
        </div>
        <p>${escapeHtml(event.message)}</p>
      </div>
    </article>
  `;
}

export function renderDiaryRoomFeed(
  entries: DiaryRoomEntry[],
  options: { cogId: string; currentRoomId: string | undefined; visibleRoomCount: number },
): string {
  if (entries.length === 0) {
    return `<div class="profile-empty-state">No diary entries yet.</div>`;
  }

  const visibleEntries = entries.slice(0, Math.max(1, options.visibleRoomCount));
  const currentEntryIndex = currentDiaryEntryIndex(visibleEntries, options.currentRoomId);
  const hiddenEntryCount = Math.max(0, entries.length - visibleEntries.length);
  const loadMoreCount = Math.min(DIARY_LOAD_MORE_ROOM_COUNT, hiddenEntryCount);
  const loadMoreButton = hiddenEntryCount > 0
    ? `
      <button
        class="profile-diary-load-more"
        data-action="load-more-diary-rooms"
        data-cog-id="${escapeHtml(options.cogId)}"
        type="button"
      >
        <span>Load ${escapeHtml(String(loadMoreCount))} more rooms</span>
        <small>${escapeHtml(String(hiddenEntryCount))} hidden</small>
      </button>
    `
    : "";

  return `
    <div class="profile-diary-room-list">
      ${visibleEntries.map((entry, index) => renderDiaryRoomEntry(entry, index === currentEntryIndex, options.cogId)).join("")}
      ${loadMoreButton}
    </div>
  `;
}

function renderDiaryRoomEntry(entry: DiaryRoomEntry, isCurrent: boolean, cogId: string): string {
  const openAttribute = isCurrent ? " open" : "";
  const currentBadge = isCurrent ? `<span class="profile-diary-current-badge">Current</span>` : "";

  return `
    <details
      class="profile-diary-room-entry"
      data-diary-entry-id="${escapeHtml(entry.id)}"
      ${isCurrent ? 'data-current-room="true"' : ""}
      data-room-id="${escapeHtml(entry.roomId)}"
      ${openAttribute}
    >
      <summary class="profile-diary-room-header">
        <span class="profile-diary-room-title">
          <strong>${escapeHtml(entry.roomLabel)}</strong>
          ${currentBadge}
        </span>
        ${renderDiarySummaryStats(entry)}
      </summary>
      ${renderDiaryRoomOccupants(entry)}
      ${renderDiaryMiniFeed(entry, cogId)}
    </details>
  `;
}

function renderDiaryRoomOccupants(entry: DiaryRoomEntry): string {
  const roomCogs = entry.roomCogs ?? [];
  if (roomCogs.length === 0) {
    return `<p class="profile-diary-room-occupants">no Cogs in room now</p>`;
  }

  return `
    <div class="profile-diary-room-occupants" aria-label="Cogs in room now">
      <span>now</span>
      ${roomCogs.map((cog) => `<strong data-color="${escapeHtml(cog.color)}">${escapeHtml(cog.name)}</strong>`).join("")}
    </div>
  `;
}

function currentDiaryEntryIndex(entries: DiaryRoomEntry[], currentRoomId: string | undefined): number {
  const currentRoomIndex = currentRoomId
    ? entries.findIndex((entry) => entry.roomId === currentRoomId && entry.leaveTick === undefined)
    : -1;
  return currentRoomIndex >= 0 ? currentRoomIndex : 0;
}

function renderDiarySummaryStats(entry: DiaryRoomEntry): string {
  const stats = [
    { label: "debates", value: entry.debateResults.length },
    { label: "witnessed", value: entry.witnessedDebates.length },
    { label: "achievements", value: entry.achievements?.length ?? 0 },
    { label: "converted", value: entry.flips.length },
  ].filter((stat) => stat.value > 0);
  const visibleStats = stats.length ? stats : [{ label: "events", value: entry.events.length }];

  return `
    <span class="profile-diary-summary-stats" aria-label="Room diary summary">
      ${visibleStats.map((stat) => `<span>${escapeHtml(String(stat.value))} ${escapeHtml(stat.label)}</span>`).join("")}
    </span>
  `;
}

function renderDiaryMiniFeed(entry: DiaryRoomEntry, cogId: string): string {
  const items = reverseChronologicalDiaryEvents(entry);
  if (items.length === 0) {
    return `<p class="profile-diary-empty-line">No room events yet.</p>`;
  }

  return `
    <ol class="profile-diary-mini-feed">
      ${items.map((item) => renderDiaryMiniFeedItem(item, cogId, entry)).join("")}
    </ol>
  `;
}

function reverseChronologicalDiaryEvents(entry: DiaryRoomEntry): DiaryEventItem[] {
  return entry.events.slice().sort((left, right) => {
    if (left.event.tick !== right.event.tick) {
      return right.event.tick - left.event.tick;
    }

    return diaryEventKindRank(left.kind) - diaryEventKindRank(right.kind) || left.event.id.localeCompare(right.event.id);
  });
}

function diaryEventKindRank(kind: DiaryEventKind): number {
  switch (kind) {
    case "person":
      return 0;
    case "debate":
      return 1;
    case "witness":
      return 2;
    case "achievement":
      return 3;
    case "flip":
      return 4;
  }
}

function renderDiaryMiniFeedItem(item: DiaryEventItem, cogId: string, entry: DiaryRoomEntry): string {
  const presentation = diaryEventPresentation(item.kind);
  const isDebateRow = item.kind === "debate" || item.kind === "witness";
  const label = item.kind === "flip" || item.kind === "achievement"
    ? `<span class="profile-diary-event-label">${escapeHtml(presentation.label)}</span>`
    : "";
  const speaker = diaryEventSpeaker(item, cogId);

  return `
    <li class="profile-diary-event" data-event-kind="${escapeHtml(item.kind)}">
      ${renderDiaryEventIcon(item, presentation)}
      ${isDebateRow ? "" : label}
      <p>
        <span class="profile-diary-chat-meta">[t${escapeHtml(String(item.event.tick))}]</span>
        <strong class="profile-diary-chat-speaker">${escapeHtml(speaker)}</strong>
        <span>${renderDiaryEventMessage(item, cogId, entry)}</span>
      </p>
    </li>
  `;
}

function renderDiaryEventMessage(item: DiaryEventItem, cogId: string, entry: DiaryRoomEntry): string {
  if (item.kind === "person") {
    return escapeHtml(diaryPersonMessage(item, entry));
  }

  if (item.kind === "debate" || item.kind === "witness") {
    const debateLog = item.event.diaryDebateLog;
    if (debateLog) {
      return renderDiaryDebateCertaintySummary(debateLog, cogId);
    }
  }

  return escapeHtml(item.event.message);
}

function diaryEventSpeaker(item: DiaryEventItem, cogId: string): string {
  if (item.kind === "achievement") {
    return "achievement";
  }
  if (item.kind === "flip") {
    return "conversion";
  }
  if (item.kind === "witness") {
    return "room";
  }
  const actorName = item.actor?.name;
  if (actorName) {
    return item.actor?.id === cogId ? "you" : actorName;
  }
  return "room";
}

function diaryPersonMessage(item: DiaryEventItem, entry: DiaryRoomEntry): string {
  const actorName = item.actor?.name ?? "A Cog";
  if (isDiaryArrivalEvent(item.event)) {
    return `${actorName} entered ${entry.roomLabel}.`;
  }
  if (isDiaryDepartureEvent(item.event)) {
    const destination = diaryMoveDestinationLabel(item.event);
    return destination ? `${actorName} exited toward ${destination}.` : `${actorName} exited.`;
  }
  return item.event.message;
}

function renderDiaryDebateCertaintySummary(entry: DebateLogEntry, cogId: string): string {
  const changes = entry.changes.filter(
    (change) => change.certaintyBefore !== change.certaintyAfter || change.colorBefore !== change.colorAfter,
  );
  const conversions = entry.conversions ?? [];
  if (changes.length === 0 && conversions.length === 0) {
    return escapeHtml(diaryDebateLogMessage(entry));
  }

  const changeText = changes
    .map((change, index) => {
      const separator = index > 0 ? `<span class="profile-diary-change-separator">, </span>` : "";
      return `${separator}${renderDiaryDebateCertaintyChange(change, cogId)}`;
    })
    .join("");
  const conversionText = conversions
    .map((conversion, index) => {
      const separator = changeText || index > 0 ? `<span class="profile-diary-change-separator">, </span>` : "";
      const name = conversion.cogId === cogId ? "You" : conversion.cogName;
      return `${separator}<span class="profile-diary-conversion">${escapeHtml(name)} converted ${escapeHtml(conversion.fromColor)}-&gt;${escapeHtml(conversion.toColor)}</span>`;
    })
    .join("");
  return `${changeText}${conversionText}`;
}

function renderDiaryDebateCertaintyChange(change: DebateLogEntry["changes"][number], cogId: string): string {
  const displayName = change.cogId === cogId ? "You" : change.cogName;
  return `
    <span class="profile-diary-certainty-entry">
      <strong class="profile-diary-cog-name" data-color="${escapeHtml(change.colorAfter)}">${escapeHtml(displayName)}</strong>
      <span class="profile-diary-certainty-change">(${escapeHtml(formatNumber(change.certaintyBefore))}-&gt;${escapeHtml(formatNumber(change.certaintyAfter))})</span>
    </span>
  `;
}

function renderDiaryEventIcon(item: DiaryEventItem, presentation: { icon: string; label: string }): string {
  if (item.kind === "debate" || item.kind === "witness") {
    return renderDiaryDebateTacticIcons(item.event, presentation.label);
  }

  if (item.kind === "flip") {
    return renderDiaryFlipColorCircle(item.event);
  }

  if (item.kind === "person") {
    return renderDiaryPersonIcons(item);
  }

  return `<span class="profile-diary-event-icon" aria-hidden="true">${escapeHtml(presentation.icon)}</span>`;
}

function renderDiaryPersonIcons(item: DiaryEventItem): string {
  const actor = item.actor;
  const label = actor ? `${actor.name} movement` : "Cog movement";
  const directionClass = isDiaryDepartureEvent(item.event)
    ? " profile-diary-direction-exit"
    : " profile-diary-direction-enter";

  return `
    <span class="profile-diary-event-icon profile-diary-event-person" aria-label="${escapeHtml(label)}">
      <span class="profile-diary-direction${directionClass}" aria-hidden="true"></span>
      ${renderDiaryCogAvatar(actor)}
    </span>
  `;
}

function renderDiaryCogAvatar(cog: DiaryCogRef | undefined): string {
  const color = cog?.color ?? "unknown";
  const spriteUrl = cog ? cogSpriteUrl(cog) : undefined;
  const image = spriteUrl
    ? `<img alt="" src="${escapeHtml(spriteUrl)}" />`
    : `<span>${escapeHtml(cog ? initials(cog.name) : "?")}</span>`;

  return `
    <span class="profile-diary-cog-avatar" data-color="${escapeHtml(color)}" aria-hidden="true">
      ${image}
    </span>
  `;
}

function renderDiaryDebateTacticIcons(event: WorldEvent, label: string): string {
  const actions = event.debate?.actions ?? [];
  if (actions.length !== 2) {
    return `<span class="profile-diary-event-icon" aria-label="${escapeHtml(label)}">${escapeHtml(diaryEventPresentation("debate").icon)}</span>`;
  }

  const winnerCogId = event.debate?.winnerCogId;
  return `
    <span class="profile-diary-event-icon profile-diary-event-tactics" aria-label="${escapeHtml(label)}">
      ${actions
        .map((action) => {
          const isWinner = winnerCogId !== undefined && action.cogId === winnerCogId;
          return `<span class="profile-diary-tactic-icon${isWinner ? " profile-diary-tactic-winner" : ""}" data-tactic="${escapeHtml(action.action)}" title="${escapeHtml(DEBATE_TACTIC_LABELS[action.action])}">${escapeHtml(DEBATE_TACTIC_ICONS[action.action])}</span>`;
        })
        .join("")}
    </span>
  `;
}

function renderDiaryFlipColorCircle(event: WorldEvent): string {
  const color = diaryFlipColor(event);
  const colorLabel = color ? `${color} team` : "new team color";
  return `
    <span class="profile-diary-event-icon profile-diary-event-color" aria-label="${escapeHtml(colorLabel)}">
      <span class="profile-diary-color-circle" data-color="${escapeHtml(color ?? "unknown")}"></span>
    </span>
  `;
}

function diaryFlipColor(event: WorldEvent): Color | undefined {
  const colorMatch = event.message.match(/\bto\s+(red|blue)\b/i);
  const color = colorMatch?.[1]?.toLowerCase();
  return TEAM_COLORS.find((candidate) => candidate === color);
}

function diaryEventPresentation(kind: DiaryEventKind): { icon: string; label: string } {
  switch (kind) {
    case "achievement":
      return { icon: "!", label: "Achievement" };
    case "flip":
      return { icon: ">", label: "Converted" };
    case "debate":
      return { icon: "#", label: "Debate" };
    case "witness":
      return { icon: "@", label: "Witness" };
    case "person":
      return { icon: "", label: "Cog" };
  }
}

export function renderGameFlowPanel(events: WorldEvent[]): string {
  const flowEvents = events.filter((event) => event.type === "gameFlow").slice(-GAME_FLOW_EVENT_LIMIT);
  const newestTick = flowEvents.at(-1)?.tick;
  const body = flowEvents.length
    ? `
      <ol class="game-flow-list">
        ${flowEvents.map(renderGameFlowItem).join("")}
      </ol>
    `
    : `<div class="game-flow-empty">waiting for tick</div>`;

  return `
    <section class="game-flow-panel" aria-label="Game flow">
      <div class="game-flow-header">
        <span>Game flow</span>
        <span>${newestTick === undefined ? "idle" : `t${escapeHtml(String(newestTick))}`}</span>
      </div>
      ${body}
    </section>
  `;
}

export function renderGameTicker(snapshot: WorldSnapshot): string {
  return renderGameTickerItems(gameTickerItems(snapshot));
}

function renderGameTickerItems(items: GameTickerItem[], offsetPx = 0): string {
  if (items.length === 0) {
    return "";
  }

  const tickerGroup = renderGameTickerGroup(items);
  return `
    <section class="game-ticker-panel" aria-label="${escapeHtml(gameTickerAriaLabel(items))}">
      <div class="game-ticker-window">
        <div class="game-ticker-track" style="transform: translate3d(${formatTickerOffset(offsetPx)}px, 0, 0)">
          <span class="game-ticker-group">${tickerGroup}</span>
        </div>
      </div>
    </section>
  `;
}

function formatTickerOffset(offsetPx: number): string {
  return Number.isFinite(offsetPx) ? (Math.round(offsetPx * 1000) / 1000).toString() : "0";
}

function browserWindow(): (Window & typeof globalThis) | undefined {
  return typeof window === "undefined" ? undefined : window;
}

function prefersReducedMotion(): boolean {
  return browserWindow()?.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

function gameTickerItems(snapshot: WorldSnapshot): GameTickerItem[] {
  const items = [
    ...arrivalTickerItems(snapshot),
    ...conversionTickerItems(snapshot),
    ...completedAchievementTickerItems(snapshot),
    ...majorityTickerItems(snapshot),
  ];

  return items
    .sort(compareGameTickerItemsDescending)
    .slice(0, GAME_TICKER_ITEM_LIMIT)
    .sort(compareGameTickerItemsAscending);
}

function arrivalTickerItems(snapshot: WorldSnapshot): GameTickerItem[] {
  return snapshot.recentEvents.flatMap((event) => {
    if (event.type !== "spawn" || !isRecentTickerTick(event.tick, snapshot.tick)) {
      return [];
    }

    const cog = event.actorId ? snapshot.cogs.find((candidate) => candidate.id === event.actorId) : undefined;
    const name = cog?.name ?? arrivalNameFromMessage(event.message) ?? event.actorId;
    if (!name) {
      return [];
    }

    return [{
      color: cog?.color,
      id: `arrival-${event.id}`,
      kind: "arrival" as const,
      name,
      tick: event.tick,
    }];
  });
}

function conversionTickerItems(snapshot: WorldSnapshot): GameTickerItem[] {
  return snapshot.recentEvents.flatMap((event) => {
    if (event.type !== "colorChange" || !isRecentTickerTick(event.tick, snapshot.tick)) {
      return [];
    }

    const change = colorChangeTickerInfo(event, snapshot);
    if (!change) {
      return [];
    }

    return [{
      color: change.to,
      id: `conversion-${event.id}`,
      kind: "conversion" as const,
      name: change.name,
      teamColor: change.to,
      tick: event.tick,
    }];
  });
}

function completedAchievementTickerItems(snapshot: WorldSnapshot): GameTickerItem[] {
  return snapshot.cogs.flatMap((cog) =>
    completedAchievementsForCog(cog).flatMap((achievement) => {
      if (!isRecentTickerTick(achievement.completedTick, snapshot.tick)) {
        return [];
      }

      return [{
        color: cog.color,
        id: `achievement-${cog.id}-${achievement.assignmentId}`,
        kind: "achievement" as const,
        label: achievementRuleByAssignment(achievement)?.label ?? achievement.achievementId,
        name: cog.name,
        tick: achievement.completedTick,
      }];
    }),
  );
}

function majorityTickerItems(snapshot: WorldSnapshot): GameTickerItem[] {
  const colorEvents = snapshot.recentEvents
    .flatMap((event) => {
      if (event.type !== "colorChange") {
        return [];
      }
      const colors = teamChangeColorsFromMessage(event.message);
      return colors ? [{ colors, event }] : [];
    })
    .sort((left, right) => left.event.tick - right.event.tick || left.event.id.localeCompare(right.event.id));
  if (colorEvents.length === 0) {
    return [];
  }

  const counts = populationCountsByColor(snapshot.cogs);
  for (const { colors } of colorEvents) {
    applyPopulationDelta(counts, colors.to, -1);
    applyPopulationDelta(counts, colors.from, 1);
  }

  const items: GameTickerItem[] = [];
  for (const { colors, event } of colorEvents) {
    const beforeMajority = strictMajorityColor(counts);
    applyPopulationDelta(counts, colors.from, -1);
    applyPopulationDelta(counts, colors.to, 1);
    const afterMajority = strictMajorityColor(counts);
    if (afterMajority && afterMajority !== beforeMajority && isRecentTickerTick(event.tick, snapshot.tick)) {
      items.push({
        id: `majority-${event.id}-${afterMajority}`,
        kind: "majority",
        teamColor: afterMajority,
        tick: event.tick,
      });
    }
  }

  return items;
}

function renderGameTickerGroup(items: GameTickerItem[]): string {
  return items
    .map((item, index) => {
      const separator = index < items.length - 1
        ? `<span class="game-ticker-separator" aria-hidden="true">.....</span>`
        : "";
      return `${renderGameTickerItem(item)}${separator}`;
    })
    .join("");
}

function renderGameTickerItem(item: GameTickerItem): string {
  if (item.kind === "arrival" && item.name) {
    return `
      <span class="game-ticker-item" data-ticker-kind="${escapeHtml(item.kind)}">
        ${renderTickerName(item.name, item.color)}
        <span class="game-ticker-event">arrived!</span>
      </span>
    `;
  }

  if (item.kind === "majority" && item.teamColor) {
    return `
      <span class="game-ticker-item" data-ticker-kind="${escapeHtml(item.kind)}">
        ${renderTickerTeam(item.teamColor)}
        <span class="game-ticker-event">reaches majority</span>
      </span>
    `;
  }

  if (item.kind === "achievement" && item.name && item.label) {
    return `
      <span class="game-ticker-item" data-ticker-kind="${escapeHtml(item.kind)}">
        ${renderTickerName(item.name, item.color)}
        <span class="game-ticker-event">achieves</span>
        <span class="game-ticker-achievement">${escapeHtml(item.label)}</span>
      </span>
    `;
  }

  if (item.kind === "conversion" && item.name && item.teamColor) {
    return `
      <span class="game-ticker-item" data-ticker-kind="${escapeHtml(item.kind)}">
        ${renderTickerName(item.name, item.color)}
        <span class="game-ticker-event">flipped to</span>
        ${renderTickerTeam(item.teamColor)}
      </span>
    `;
  }

  return "";
}

function renderTickerName(name: string, color: Color | undefined): string {
  const colorAttribute = color ? ` data-color="${escapeHtml(color)}"` : "";
  return `<span class="game-ticker-name"${colorAttribute}>${escapeHtml(name)}</span>`;
}

function renderTickerTeam(color: Color): string {
  return `<span class="game-ticker-team" data-color="${escapeHtml(color)}">${escapeHtml(titleCase(color))}</span>`;
}

function gameTickerAriaLabel(items: GameTickerItem[]): string {
  return items.map(gameTickerItemLabel).filter(Boolean).join(" ");
}

function gameTickerItemLabel(item: GameTickerItem): string {
  if (item.kind === "arrival" && item.name) {
    return `${item.name} arrived.`;
  }
  if (item.kind === "majority" && item.teamColor) {
    return `${titleCase(item.teamColor)} reaches majority.`;
  }
  if (item.kind === "achievement" && item.name && item.label) {
    return `${item.name} achieves ${item.label}.`;
  }
  if (item.kind === "conversion" && item.name && item.teamColor) {
    return `${item.name} flipped to ${titleCase(item.teamColor)}.`;
  }
  return "";
}

function colorChangeTickerInfo(
  event: WorldEvent,
  snapshot: WorldSnapshot,
): { from: Color; name: string; to: Color } | undefined {
  const colors = teamChangeColorsFromMessage(event.message);
  if (!colors || colors.from === colors.to) {
    return undefined;
  }

  const cog = event.actorId ? snapshot.cogs.find((candidate) => candidate.id === event.actorId) : undefined;
  const name = cog?.name ?? colorChangeNameFromMessage(event.message) ?? event.actorId;
  return name ? { ...colors, name } : undefined;
}

function arrivalNameFromMessage(message: string): string | undefined {
  const match = message.match(/^(.*?)\s+arrived!$/i);
  const name = match?.[1]?.trim();
  return name || undefined;
}

function colorChangeNameFromMessage(message: string): string | undefined {
  const match = message.match(/^(.*?)\s+(?:converted|flipped|shuffled)\s+from\s+(?:red|blue)\s+to\s+(?:red|blue)\b/i);
  const name = match?.[1]?.trim();
  return name || undefined;
}

function isRecentTickerTick(tick: number, currentTick: number): boolean {
  return tick <= currentTick && currentTick - tick < GAME_TICKER_VISIBLE_TICKS;
}

function compareGameTickerItemsAscending(left: GameTickerItem, right: GameTickerItem): number {
  return left.tick - right.tick || gameTickerKindRank(left.kind) - gameTickerKindRank(right.kind) || left.id.localeCompare(right.id);
}

function compareGameTickerItemsDescending(left: GameTickerItem, right: GameTickerItem): number {
  return right.tick - left.tick || gameTickerKindRank(left.kind) - gameTickerKindRank(right.kind) || left.id.localeCompare(right.id);
}

function gameTickerKindRank(kind: GameTickerItem["kind"]): number {
  switch (kind) {
    case "arrival":
      return 0;
    case "conversion":
      return 1;
    case "majority":
      return 2;
    case "achievement":
      return 3;
  }
}

function renderGameFlowItem(event: WorldEvent): string {
  return `
    <li class="game-flow-item">
      <span class="game-flow-tick">t${escapeHtml(String(event.tick))}</span>
      <span class="game-flow-message">${escapeHtml(event.message)}</span>
    </li>
  `;
}

function initials(name: string): string {
  const parts = name
    .trim()
    .split(/\s+/)
    .filter(Boolean);

  if (parts.length === 0) {
    return "?";
  }

  return parts
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

function cogSpriteUrl(cog: CogSnapshot): string | undefined {
  return spriteUrlForCog(cog) ?? staticCogSpriteUrls.get(cog.spriteSheetKey) ?? staticCogSpriteUrls.get("cog-default");
}

function sortedRosterCogs(cogs: CogSnapshot[], mode: RosterMode): CogSnapshot[] {
  const byScore = (left: CogSnapshot, right: CogSnapshot): number =>
    right.personalScore - left.personalScore || left.name.localeCompare(right.name);

  if (mode === "room") {
    return [...cogs].sort(
      (left, right) =>
        roomLabel(left).localeCompare(roomLabel(right)) ||
        byScore(left, right),
    );
  }

  return [...cogs].sort(byScore);
}

function renderRoomRoster(
  cogs: CogSnapshot[],
  snapshot: WorldSnapshot | undefined,
  selectedCogId: string | undefined,
  expandedCogId: string | undefined,
  gameConfig: GameConfig | undefined,
  discoMode: boolean,
): string {
  const sorted = sortedRosterCogs(cogs, "room");
  let currentRoom = "";
  return sorted
    .map((cog) => {
      const room = roomLabel(cog);
      const heading = room !== currentRoom
        ? `<div class="cog-room-heading">${escapeHtml(roomDisplayName(room, snapshot))}</div>`
        : "";
      currentRoom = room;
      return `${heading}${renderCogRosterRow(cog, { discoMode, expandedCogId, gameConfig, selectedCogId, snapshot })}`;
    })
    .join("");
}

type CogRosterRenderOptions = {
  discoMode: boolean;
  expandedCogId: string | undefined;
  gameConfig: GameConfig | undefined;
  selectedCogId: string | undefined;
  snapshot: WorldSnapshot | undefined;
};
type RosterChoice =
  | {
      kind: "room";
      roomId: string;
      label: string;
    }
  | {
      kind: "target";
      targetId: string;
      label: string;
      color: Color;
      certainty: number;
      spriteUrl?: string;
    }
  | {
      kind: "tactic";
      tactic: DebateTactic;
      label: string;
      icon: string;
    };

type MobileGuidanceChoice = {
  label: string;
  prompt: string;
};

const ROSTER_TACTIC_CHOICES: RosterChoice[] = [
  { kind: "tactic", tactic: "reason", label: DEBATE_TACTIC_LABELS.reason, icon: DEBATE_TACTIC_ICONS.reason },
  { kind: "tactic", tactic: "spin", label: DEBATE_TACTIC_LABELS.spin, icon: DEBATE_TACTIC_ICONS.spin },
  { kind: "tactic", tactic: "passion", label: DEBATE_TACTIC_LABELS.passion, icon: DEBATE_TACTIC_ICONS.passion },
];
const ROSTER_COMPLETED_OBJECTIVE_VISIBLE_TICKS = secondsToSimulationTicks(30);

function renderCogRosterRow(cog: CogSnapshot, options: CogRosterRenderOptions): string {
  const selectedClass = cog.id === options.selectedCogId ? " is-selected" : "";
  const discoClass = options.discoMode ? " is-disco" : "";
  const certainty = certaintyMeter(cog, options.gameConfig?.conversionThreshold ?? CONVERSION_THRESHOLD);
  const spriteUrl = cogSpriteUrl(cog);
  const choicePanel = cog.id === options.expandedCogId ? renderCogChoicePanel(cog, options.snapshot) : "";
  const rosterScore = formatPersonalScore(cog.personalScore);

  return `
    <div class="cog-row-shell" data-cog-id="${escapeHtml(cog.id)}">
      <button
        aria-expanded="${choicePanel ? "true" : "false"}"
        aria-pressed="${cog.id === options.selectedCogId}"
        class="cog-row${selectedClass}${discoClass}"
        data-action="select-cog"
        data-cog-id="${escapeHtml(cog.id)}"
        type="button"
      >
        <span class="cog-row-avatar${discoClass}" data-color="${escapeHtml(cog.color)}" aria-hidden="true">
          ${spriteUrl ? `<img alt="" src="${escapeHtml(spriteUrl)}" />` : escapeHtml(initials(cog.name))}
        </span>
        <span class="cog-row-body">
          <span class="cog-row-title">
            <span class="cog-name">${escapeHtml(cog.name)}</span>
            ${renderCogStats(cog)}
          </span>
          ${renderFlipGauge(cog.name, certainty, options.discoMode)}
          ${renderRosterAchievementSummary(cog, options.snapshot)}
        </span>
        <span class="cog-score" aria-label="${escapeHtml(cog.name)} score ${escapeHtml(rosterScore)} points">
          <strong>${escapeHtml(rosterScore)}</strong>
          <span>pts</span>
        </span>
      </button>
      ${choicePanel}
    </div>
  `;
}

function renderRosterAchievementSummary(cog: CogSnapshot, snapshot: WorldSnapshot | undefined): string {
  const lastCompleted = lastVisibleCompletedAchievement(cog, snapshot);
  if (!lastCompleted) {
    return "";
  }

  const label = achievementRuleByAssignment(lastCompleted)?.label ?? lastCompleted.achievementId;
  return `
    <span class="cog-row-achievements" aria-label="${escapeHtml(`${cog.name} last completed objective`)}">
      <span class="cog-row-achievement-line cog-row-achievement-line-completed">
        <span class="cog-row-achievement-status">Completed:</span>
        <span class="cog-row-achievement-names">${escapeHtml(label)}</span>
      </span>
    </span>
  `;
}

function lastVisibleCompletedAchievement(cog: CogSnapshot, snapshot: WorldSnapshot | undefined): CompletedAchievement | undefined {
  const completed = completedAchievementsForCog(cog)
    .filter((achievement) => isRosterCompletedAchievementVisible(achievement, snapshot));
  return completed.reduce<CompletedAchievement | undefined>((latest, achievement) => {
    if (!latest || achievement.completedTick >= latest.completedTick) {
      return achievement;
    }
    return latest;
  }, undefined);
}

function isRosterCompletedAchievementVisible(
  achievement: CompletedAchievement,
  snapshot: WorldSnapshot | undefined,
): boolean {
  if (!snapshot) {
    return true;
  }
  return snapshot.tick - achievement.completedTick < ROSTER_COMPLETED_OBJECTIVE_VISIBLE_TICKS;
}

function renderCogChoicePanel(cog: CogSnapshot, snapshot: WorldSnapshot | undefined): string {
  const details = renderRosterCogDetails(cog, snapshot);

  return `
    <div class="cog-choice-panel" data-cog-id="${escapeHtml(cog.id)}" aria-label="${escapeHtml(cog.name)} profile">
      ${renderRosterProfileQrCard(cog)}
      ${details}
      ${renderRosterKickAction(cog)}
    </div>
  `;
}

function renderRosterCogDetails(cog: CogSnapshot, snapshot: WorldSnapshot | undefined): string {
  return `
    <div class="cog-choice-details">
      <section class="cog-choice-section" aria-label="Traits">
        <h3>Traits</h3>
        <div class="cog-choice-badges">
          ${renderReadOnlyTraitBadge("defensiveTrait", cog.defensiveTrait)}
          ${renderReadOnlyTraitBadge("activeTrait", cog.activeTrait)}
        </div>
      </section>
      <section class="cog-choice-section" aria-label="Achievement goals">
        <h3>Achievement Goals</h3>
        ${renderRosterAchievementGoals(cog, snapshot)}
      </section>
    </div>
  `;
}

function renderRosterProfileQrCard(cog: CogSnapshot): string {
  const href = profileQrUrl(cog.id);
  return `
    <a
      aria-label="Open ${escapeHtml(cog.name)} profile and remember this cog"
      class="cog-choice-qr-card"
      data-action="open-profile-window"
      data-cog-id="${escapeHtml(cog.id)}"
      href="${escapeHtml(href)}"
      target="cogshambo-profile"
    >
      ${renderQrSvg(href, "cog-choice-qr-code")}
      <span class="cog-choice-qr-copy">
        <span>Profile</span>
        <strong>${escapeHtml(cog.name)}</strong>
      </span>
    </a>
  `;
}

function renderRosterKickAction(cog: CogSnapshot): string {
  return `
    <div class="cog-choice-actions">
      <button
        aria-label="Kick ${escapeHtml(cog.name)} home"
        class="cog-choice-kick-button"
        data-action="kick-cog"
        data-cog-id="${escapeHtml(cog.id)}"
        type="button"
      >Kick</button>
    </div>
  `;
}

function renderRosterAchievementGoals(cog: CogSnapshot, snapshot: WorldSnapshot | undefined): string {
  const active = achievementAssignmentsForCog(cog);
  if (!active.length) {
    return `<div class="cog-choice-muted">No active achievement goals.</div>`;
  }

  return `
    <div class="cog-choice-achievements">
      ${active
        .map((achievement) => {
          const rule = achievementRuleByAssignment(achievement);
          const remainingTicks = Math.max(0, achievement.timeoutTick - (snapshot?.tick ?? achievement.assignedTick));
          const label = rule?.label ?? achievement.achievementId;
          const condition = rule?.condition ?? "";
          return `
            <div
              class="cog-choice-achievement"
              data-achievement="${escapeHtml(achievementKey(achievement))}"
              title="${escapeHtml(condition)}"
            >
              <span>${escapeHtml(label)}</span>
              <span>${escapeHtml(String(Math.ceil(remainingTicks * SIMULATION_TICK_SECONDS)))}s</span>
            </div>
          `;
        })
        .join("")}
    </div>
  `;
}

function isRosterTacticChoice(choice: RosterChoice): choice is Extract<RosterChoice, { kind: "tactic" }> {
  return choice.kind === "tactic";
}

function isRosterTargetChoice(choice: RosterChoice): choice is Extract<RosterChoice, { kind: "target" }> {
  return choice.kind === "target";
}

function effectiveCogActivity(cog: CogSnapshot): string {
  if (cog.moving) {
    return "moving";
  }

  if (cog.debate) {
    return "debating";
  }

  return cog.activity ?? "idle";
}

function rosterStatePlace(cog: CogSnapshot, snapshot: WorldSnapshot | undefined): string {
  if (cog.moving) {
    return `to ${roomDisplayName(cog.moving.to.roomId, snapshot)}`;
  }

  if (cog.location) {
    return roomDisplayName(cog.location.roomId, snapshot);
  }

  return `${cog.position.x},${cog.position.y}`;
}

function rosterDebateTargetChoicesForCog(
  cog: CogSnapshot,
  snapshot: WorldSnapshot | undefined,
): Array<Extract<RosterChoice, { kind: "target" }>> {
  if (!snapshot || cog.moving || cog.debate || effectiveCogActivity(cog) !== "idle") {
    return [];
  }

  return snapshot.cogs
    .filter((candidate) => {
      if (
        candidate.id === cog.id ||
        candidate.color === cog.color ||
        candidate.moving ||
        candidate.debate ||
        effectiveCogActivity(candidate) !== "idle"
      ) {
        return false;
      }

      if (snapshot.venue && cog.location && candidate.location) {
        return (
          cog.location.roomId === candidate.location.roomId &&
          venueSpotIsSpeaker(venueSpotForLocation(snapshot, cog.location.spotId)) &&
          venueSpotIsSpeaker(venueSpotForLocation(snapshot, candidate.location.spotId))
        );
      }

      return Math.abs(candidate.position.x - cog.position.x) <= 1 && Math.abs(candidate.position.y - cog.position.y) <= 1;
    })
    .map((candidate) => ({
      kind: "target" as const,
      targetId: candidate.id,
      label: candidate.name,
      color: candidate.color,
      certainty: candidate.certainty,
    }));
}

function rosterChoicesForCog(
  cog: CogSnapshot,
  snapshot: WorldSnapshot | undefined,
  gameConfig: GameConfig | undefined,
): RosterChoice[] {
  if (cog.moving) {
    return [];
  }

  if (cog.debate) {
    return ROSTER_TACTIC_CHOICES;
  }

  return [...rosterDebateTargetChoicesForCog(cog, snapshot), ...rosterRoomChoicesForCog(cog, snapshot, gameConfig)];
}

function venueSpotForLocation(snapshot: WorldSnapshot, spotId: string) {
  return snapshot.venue?.spots.find((spot) => spot.id === spotId);
}

function canChooseRosterTactic(cog: CogSnapshot, snapshot: WorldSnapshot | undefined): boolean {
  return !cog.debate || (snapshot?.tick ?? 0) + 1 >= cog.debate.nextRoundTick;
}

function rosterRoomChoicesForCog(
  cog: CogSnapshot,
  snapshot: WorldSnapshot | undefined,
  gameConfig: GameConfig | undefined,
): RosterChoice[] {
  if (!snapshot?.venue || !cog.location || cog.debate || cog.moving || cog.movementCooldown > 0) {
    return [];
  }

  const venue = snapshot.venue;
  const currentRoom = venue.rooms.find((room) => room.id === cog.location?.roomId);
  if (!currentRoom) {
    return [];
  }

  const roomIds = uniqueStrings([currentRoom.id, ...currentRoom.neighborIds]);
  return roomIds.flatMap((roomId) => {
    const room = venue.rooms.find((candidate) => candidate.id === roomId);
    if (!room || !emptyRosterSpotInRoom(snapshot, roomId)) {
      return [];
    }

    return [{ kind: "room", roomId, label: room.label }];
  });
}

function remainingRosterMoveCooldownTicks(
  cog: CogSnapshot,
  snapshot: WorldSnapshot | undefined,
  gameConfig: GameConfig | undefined,
): number {
  const config = gameConfig ?? DEFAULT_GAME_CONFIG;
  if (typeof cog.lastVenueMoveTick !== "number" || config.roomMoveCooldownTicks <= 0) {
    return 0;
  }

  const cooldownTicks = config.roomMoveCooldownTicks;
  if (cooldownTicks <= 0) {
    return 0;
  }

  return Math.max(0, cooldownTicks - ((snapshot?.tick ?? 0) - cog.lastVenueMoveTick));
}

function emptyRosterSpotInRoom(snapshot: WorldSnapshot, roomId: string): boolean {
  return Boolean(snapshot.venue?.spots.some((spot) => spot.roomId === roomId && !isRosterSpotOccupied(snapshot, spot.id)));
}

function isRosterSpotOccupied(snapshot: WorldSnapshot, spotId: string): boolean {
  return snapshot.cogs.some(
    (cog) => cog.location?.spotId === spotId || cog.moving?.from.spotId === spotId || cog.moving?.to.spotId === spotId,
  );
}

function uniqueStrings(values: string[]): string[] {
  return Array.from(new Set(values));
}

function renderCogStats(cog: CogSnapshot): string {
  const completedCount = completedAchievementsForCog(cog).length;
  const expiredCount = failedAchievementsForCog(cog).length;

  return `
    <span
      class="cog-row-stats"
      aria-label="${escapeHtml(cog.name)} arguments ${escapeHtml(String(cog.stats.argumentsWon))} won, ${escapeHtml(String(cog.stats.argumentsLost))} lost, ${escapeHtml(String(cog.stats.teamFlips))} team flips, ${escapeHtml(String(completedCount))} completed achievements, ${escapeHtml(String(expiredCount))} expired achievements"
    >
      <span>W ${escapeHtml(String(cog.stats.argumentsWon))}</span>
      <span>L ${escapeHtml(String(cog.stats.argumentsLost))}</span>
      <span>F ${escapeHtml(String(cog.stats.teamFlips))}</span>
      <span>C ${escapeHtml(String(completedCount))}</span>
      <span>E ${escapeHtml(String(expiredCount))}</span>
    </span>
  `;
}

function roomLabel(cog: CogSnapshot): string {
  return cog.location?.roomId ?? "no-room";
}

function roomDisplayName(roomId: string, snapshot: WorldSnapshot | undefined): string {
  return snapshot?.venue?.rooms.find((room) => room.id === roomId)?.label ?? roomId;
}

function certaintyMeter(cog: CogSnapshot, conversionThreshold: number): CertaintyMeter {
  const threshold = Math.max(1, conversionThreshold);
  const value = Math.round(Math.min(100, Math.max(0, (cog.certainty / threshold) * 100)));

  return {
    color: cog.color,
    value,
  };
}

function renderFlipGauge(cogName: string, certainty: CertaintyMeter, discoMode = false): string {
  const discoClass = discoMode ? " is-disco" : "";

  return `
    <span class="cog-row-flip" aria-label="${escapeHtml(cogName)} certainty ${escapeHtml(String(certainty.value))}%">
      <span class="flip-gauge-track" aria-hidden="true">
        <span
          class="flip-gauge-fill${discoClass}"
          data-color="${escapeHtml(certainty.color)}"
          style="width: ${escapeHtml(String(certainty.value))}%"
        ></span>
      </span>
      <span class="flip-gauge-copy">
        <span>${escapeHtml(String(certainty.value))}%</span>
      </span>
    </span>
  `;
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, milliseconds);
  });
}

export function renderTeamsGauge(
  cogs: WorldSnapshot["cogs"],
  discoMode = false,
  recentEvents: WorldEvent[] = [],
  currentTick?: number,
): string {
  const counts = new Map<Color, number>(TEAM_COLORS.map((color) => [color, 0]));
  for (const cog of cogs) {
    counts.set(cog.color, (counts.get(cog.color) ?? 0) + 1);
  }
  const impacts = teamCountImpacts(recentEvents, currentTick);

  const teams = TEAM_COLORS.map((color) => ({
    color,
    count: counts.get(color) ?? 0,
    impact: impacts.get(color) ?? { delta: 0, ageTicks: 0 },
  }));
  const total = teams.reduce((sum, team) => sum + team.count, 0);
  const visibleTeams = total > 0 ? teams.filter((team) => team.count > 0) : [];

  return `
    <section class="teams-gauge-panel" aria-label="Teams gauge">
      <div class="teams-color-bar${discoMode ? " is-disco" : ""}" role="img" aria-label="${escapeHtml(discoMode ? "Disco mode: rainbow team bar, debates paused" : teamGaugeLabel(teams, total))}">
        ${
          discoMode
            ? `<span class="team-segment disco-rainbow" aria-hidden="true"></span>`
            : visibleTeams.length > 0
            ? visibleTeams
                .map((team) =>
                  renderTeamSegment(
                    team.color,
                    team.count,
                    total > 0 ? (team.count / total) * 100 : 0,
                    team.impact,
                  ),
                )
                .join("")
            : `<span class="team-segment is-empty" aria-hidden="true"></span>`
        }
      </div>
    </section>
  `;
}

export function renderDebateTacticLegend(): string {
  const ruleLabel = DEBATE_TACTIC_BEATS.map(
    ({ winner, loser }) => `${DEBATE_TACTIC_LABELS[winner]} beats ${DEBATE_TACTIC_LABELS[loser]}`,
  ).join("; ");

  return `
    <section class="tactic-legend-panel" aria-label="Debate tactic legend: ${escapeHtml(ruleLabel)}">
      <div class="tactic-triangle" aria-hidden="true">
        <svg class="tactic-cycle" viewBox="0 0 132 104" focusable="false" aria-hidden="true">
          <defs>
            <marker id="tactic-marker-reason-spin" class="tactic-marker-head tactic-marker-head-reason-spin" markerHeight="10" markerUnits="userSpaceOnUse" markerWidth="10" orient="auto" refX="8.8" refY="5" viewBox="0 0 10 10">
              <path d="M0 0 L10 5 L0 10 Z" />
            </marker>
            <marker id="tactic-marker-spin-passion" class="tactic-marker-head tactic-marker-head-spin-passion" markerHeight="10" markerUnits="userSpaceOnUse" markerWidth="10" orient="auto" refX="8.8" refY="5" viewBox="0 0 10 10">
              <path d="M0 0 L10 5 L0 10 Z" />
            </marker>
            <marker id="tactic-marker-passion-reason" class="tactic-marker-head tactic-marker-head-passion-reason" markerHeight="10" markerUnits="userSpaceOnUse" markerWidth="10" orient="auto" refX="8.8" refY="5" viewBox="0 0 10 10">
              <path d="M0 0 L10 5 L0 10 Z" />
            </marker>
          </defs>
          <path class="tactic-cycle-path tactic-cycle-reason-spin" marker-end="url(#tactic-marker-reason-spin)" d="M76 40 C82 46 85 53 87 59" />
          <path class="tactic-cycle-path tactic-cycle-spin-passion" marker-end="url(#tactic-marker-spin-passion)" d="M82 84 C72 88 63 88 55 84" />
          <path class="tactic-cycle-path tactic-cycle-passion-reason" marker-end="url(#tactic-marker-passion-reason)" d="M42 65 C45 57 49 50 54 44" />
        </svg>
        <svg class="tactic-softmax-mark" viewBox="0 0 529.22 537.47" focusable="false" aria-hidden="true">
          <path class="tactic-softmax-mark-navy" d="M435.79 167.09c1.39 14.72 2.28 35.15.07 59.18-2.76 30-8.41 91.42-53.06 144.85-12.71 15.21-31.5 37.17-64.27 50.75-20.1 8.33-39.62 11.14-57.08 11.14-27.21 0-48.87-6.89-58.14-10.18-24.28-8.71-46.26-13.88-64.82-17.03-9.81-1.67-17.2-2.89-27.51-3.37-5.3-.24-11.2-.58-17.52-.58-14.97 0-32.31 1.91-49.66 11.55-7.2 4-22.36 11.82-33.28 28.4-2.31 3.5-5.73 7.26-7.1 13.17-.77 3.33-.83 6.45-.55 9.17 10.18 16.5 31.9 25.1 70.31 39.79 40.58 15.52 76.46 23.08 103.36 27.2 39.62 6.07 70.21 6.29 88.85 6.35h2.08c51.31 0 88.85-5.96 96.74-7.26 21.15-3.46 50.65-8.45 86.8-22.39 39.52-15.24 66.61-25.68 76.25-50.69 1.5-3.88 4.63-13.43-2.86-55.07-7.57-42.15-18.12-73.19-19.67-77.68-20.91-60.73-31.37-91.09-47.15-120.59-7.16-13.38-14.37-25.43-21.82-36.72" />
          <path class="tactic-softmax-mark-slate" d="M405.8 126.38c-2.7 14.13-7.43 33.47-16.19 55.39-9.33 23.33-17.43 43.59-36.11 63.7-9.73 10.47-34.11 36.7-70.49 40.89-3.28.38-6.47.55-9.6.55-15.24 0-29.13-4.16-46.48-9.36-22.64-6.78-33.98-14.37-61.63-19.18-10.17-1.77-16.26-2.83-24.53-2.83h-.34s-62.3.23-108.91 65.12l-.55.77c-7.32 10.87-11.91 20.88-14.86 28.78-2.55 6.79-3.97 12.26-5.54 18.27-1.6 6.15-2.79 11.62-6.31 31.17-1.14 6.36-2.61 14.59-4.27 24.25 6.4-10.91 17.12-25.9 34.2-39.3 14.59-11.45 27.98-17.13 33.06-19.16 2.85-1.13 13.75-5.35 28.95-7.8 3.93-.63 12.18-1.8 23.2-1.8 8.13 0 17.77.63 28.3 2.58 6.67 1.23 16.61 3.13 28.41 8.15 4.01 1.7 11.21 5.03 18.85 9 4.92 2.56 8.37 4.53 14.18 7.14 4.9 2.21 9.03 3.76 11.78 4.74 0 0 19.23 6.36 40.24 6.98.99.03 1.96.04 2.91.04 5.34 0 9.68-.39 9.68-.39 6.6-.26 15.9-1.18 26.55-4.2 39.25-11.14 61.44-41.03 74.07-58.02 49.95-67.19 47.93-167.85 47.41-184.77-5.17-7.02-10.49-13.86-16.02-20.7" />
          <path class="tactic-softmax-mark-sky" d="M263.85 0h-.49c-9.56.13-18.97 3.98-51.45 33.34-34.1 30.83-48.96 48.06-48.96 48.06-45.84 53.13-68.77 79.69-92.48 121.49-30.3 53.41-44.91 100.09-51.23 123.02-.58 2.1-1.15 4.32-1.73 6.71 2.32-5.49 4.94-11.19 7.9-17.04 13.39-26.42 36.61-72.21 83.93-88.86 13.54-4.76 25.96-6.06 33.79-6.37 1.47-.06 2.91-.08 4.3-.08 27.39 0 38.73 10.82 72 18.83 15.27 3.67 31.78 7.88 49.5 7.88 9.36 0 19.06-1.17 29.1-4.22 36.49-11.06 56.44-41.33 63.25-51.53 15.36-23.02 19.95-45.23 21.9-55.14 2.47-12.57 3.14-23.85 3.04-33.14-6.32-7.35-12.92-14.91-19.87-22.86 0 0-17.39-19.89-51.98-49.48C282.51 3.39 272.5 0 263.85 0" />
        </svg>
        <span class="tactic-node tactic-node-reason" data-tactic="reason">${DEBATE_TACTIC_ICONS.reason}</span>
        <span class="tactic-node tactic-node-passion" data-tactic="passion">${DEBATE_TACTIC_ICONS.passion}</span>
        <span class="tactic-node tactic-node-spin" data-tactic="spin">${DEBATE_TACTIC_ICONS.spin}</span>
      </div>
    </section>
  `;
}

type TeamCountImpact = {
  delta: number;
  ageTicks: number;
};

function renderTeamSegment(color: Color, count: number, basisPercent: number, impact: TeamCountImpact): string {
  const deltaClass = teamDeltaClass(impact.delta);
  const impactStyle = impact.delta === 0
    ? ""
    : `; --team-impact-age-ms: -${simulationTicksToMs(Math.max(0, impact.ageTicks))}ms`;
  const arrowMarkup = impact.delta === 0
    ? ""
    : `<span class="team-segment-arrow" data-direction="${impact.delta > 0 ? "up" : "down"}"></span>`;

  return `
    <span
      class="team-segment${deltaClass}"
      data-color="${escapeHtml(color)}"
      style="flex-basis: ${escapeHtml(basisPercent.toFixed(3))}%${impactStyle}"
      aria-hidden="true"
    >
      <span class="team-segment-count">${escapeHtml(String(count))}</span>
      ${arrowMarkup}
    </span>
  `;
}

function teamGaugeLabel(teams: Array<{ color: Color; count: number }>, total: number): string {
  if (total === 0) {
    return "No cogs on teams";
  }

  return teams.map((team) => `${team.color} ${team.count}`).join(", ");
}

function populationCountsByColor(cogs: WorldSnapshot["cogs"]): Map<Color, number> {
  const counts = new Map<Color, number>(TEAM_COLORS.map((color) => [color, 0]));
  for (const cog of cogs) {
    counts.set(cog.color, (counts.get(cog.color) ?? 0) + 1);
  }
  return counts;
}

function applyPopulationDelta(counts: Map<Color, number>, color: Color, delta: number): void {
  counts.set(color, Math.max(0, (counts.get(color) ?? 0) + delta));
}

function strictMajorityColor(counts: Map<Color, number>): Color | undefined {
  const total = Array.from(counts.values()).reduce((sum, count) => sum + count, 0);
  if (total <= 0) {
    return undefined;
  }

  return TEAM_COLORS.find((color) => (counts.get(color) ?? 0) > total / 2);
}

function teamDeltaClass(delta: number): string {
  if (delta > 0) {
    return " is-gaining";
  }

  if (delta < 0) {
    return " is-losing";
  }

  return "";
}

function teamCountImpacts(recentEvents: WorldEvent[], currentTick: number | undefined): Map<Color, TeamCountImpact> {
  const impacts = new Map<Color, TeamCountImpact>(
    TEAM_COLORS.map((color) => [color, { delta: 0, ageTicks: Number.POSITIVE_INFINITY }]),
  );
  if (currentTick === undefined) {
    return impacts;
  }

  for (const event of recentEvents) {
    if (event.type !== "colorChange") {
      continue;
    }

    const age = currentTick - event.tick;
    if (age < 0 || age > TEAM_COUNT_IMPACT_TICKS) {
      continue;
    }

    const colors = teamChangeColorsFromMessage(event.message);
    if (!colors || colors.from === colors.to) {
      continue;
    }

    applyTeamCountImpact(impacts, colors.from, -1, age);
    applyTeamCountImpact(impacts, colors.to, 1, age);
  }

  for (const impact of impacts.values()) {
    if (impact.delta === 0) {
      impact.ageTicks = 0;
    }
  }

  return impacts;
}

function applyTeamCountImpact(impacts: Map<Color, TeamCountImpact>, color: Color, delta: number, ageTicks: number): void {
  const impact = impacts.get(color) ?? { delta: 0, ageTicks: Number.POSITIVE_INFINITY };
  impact.delta += delta;
  impact.ageTicks = Math.min(impact.ageTicks, ageTicks);
  impacts.set(color, impact);
}

function teamChangeColorsFromMessage(message: string): { from: Color; to: Color } | undefined {
  const match = message.match(/\bfrom (red|blue) to (red|blue)\b/i);
  const from = colorFromString(match?.[1]);
  const to = colorFromString(match?.[2]);
  return from && to ? { from, to } : undefined;
}

function colorFromString(value: string | undefined): Color | undefined {
  return value && TEAM_COLORS.includes(value.toLowerCase() as Color) ? (value.toLowerCase() as Color) : undefined;
}

function renderCertaintyGauge(
  cogName: string,
  certainty: number,
  color: Color,
): string {
  const value = Math.max(0, certainty);
  const roundedValue = Math.round(value);
  const width = clampPercentage(value);

  return `
    <span class="doubt-gauge-list" aria-label="${escapeHtml(cogName)} certainty">
      <span
        class="doubt-gauge"
        data-color="${escapeHtml(color)}"
        aria-label="${escapeHtml(cogName)} certainty ${escapeHtml(String(roundedValue))} of 100"
      >
        <span class="doubt-gauge-label">
          <span>${escapeHtml(color)}</span>
          <span>${escapeHtml(String(roundedValue))}</span>
        </span>
        <span class="doubt-gauge-track" aria-hidden="true">
          <span class="doubt-gauge-fill" style="width: ${escapeHtml(String(width))}%"></span>
        </span>
      </span>
    </span>
  `;
}

function clampPercentage(value: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }

  return Math.max(0, Math.min(100, Math.round(value)));
}

type ParsedLogAction = {
  choiceNumber?: number;
  type: CogAction["type"];
  direction?: string;
  intent?: string;
  roomId?: string;
  tactic?: string;
  targetId?: string;
  text?: string;
  thoughts?: string;
};

type LogTickSection = {
  tick: number;
  messages: CogConversationMessage[];
  action?: ParsedLogAction;
};

type LogSubsectionKey = "rules" | "identity" | "current" | "strategy" | "thoughts" | "actions";
type PromptSectionKey = Exclude<LogSubsectionKey, "thoughts">;
type ParsedPromptSections = Record<PromptSectionKey, string[]>;

const logActions: Array<{ type: CogAction["type"]; label: string }> = [
  { type: "wait", label: "Wait" },
  { type: "move", label: "Move" },
  { type: "debate", label: "Debate" },
  { type: "chooseTactic", label: "Tactic" },
];

function groupLogByTick(messages: CogConversationMessage[]): LogTickSection[] {
  const sections = new Map<number, LogTickSection>();

  for (const message of messages) {
    const section = sections.get(message.tick) ?? {
      tick: message.tick,
      messages: [],
    };
    section.messages.push(message);

    const action = message.role === "assistant" ? parseLogAction(message.content) : undefined;
    if (action) {
      section.action = action;
    }

    sections.set(message.tick, section);
  }

  return Array.from(sections.values()).sort((left, right) => right.tick - left.tick);
}

function isControllerLogFilterKey(value: string | undefined): value is ControllerLogFilterKey {
  return value === "debates" || value === "movement";
}

function renderControllerLogFilters(filters: ControllerLogFilters): string {
  return `
    <div class="controller-log-filters" aria-label="Controller log filters">
      ${renderControllerLogFilterButton("debates", "Debates", filters.debates)}
      ${renderControllerLogFilterButton("movement", "Movement", filters.movement)}
    </div>
  `;
}

function renderControllerLogFilterButton(filter: ControllerLogFilterKey, label: string, enabled: boolean): string {
  return `
    <button
      class="controller-log-filter${enabled ? " is-active" : ""}"
      data-action="toggle-controller-log-filter"
      data-controller-log-filter="${escapeHtml(filter)}"
      type="button"
      aria-pressed="${enabled ? "true" : "false"}"
    >${escapeHtml(label)}</button>
  `;
}

function filteredControllerLogSections(
  sections: LogTickSection[],
  filters: ControllerLogFilters,
): LogTickSection[] {
  return sections.filter((section) =>
    controllerLogSectionCategories(section).every((category) => category === "other" || filters[category]),
  );
}

function controllerLogSectionCategories(section: LogTickSection): Array<ControllerLogFilterKey | "other"> {
  const prompt = parsePromptSections(section.messages.find((message) => message.role === "user")?.content ?? "");
  const categories = new Set<ControllerLogFilterKey | "other">();
  const currentKind = parseCurrentState(prompt.current).kind;

  if (section.action?.type === "debate" || section.action?.type === "chooseTactic" || currentKind === "debating" || currentKind === "witnessing") {
    categories.add("debates");
  }
  if (section.action?.type === "move" || currentKind === "moving") {
    categories.add("movement");
  }
  if (categories.size === 0) {
    categories.add("other");
  }

  return Array.from(categories);
}

function renderLogSection(section: LogTickSection): string {
  const actionSummary = section.action ? summarizeAction(section.action) : "No action";
  const prompt = parsePromptSections(section.messages.find((message) => message.role === "user")?.content ?? "");
  const categories = controllerLogSectionCategories(section);

  return `
    <article
      class="log-tick-section"
      data-log-category="${escapeHtml(categories.join(" "))}"
      data-tick="${escapeHtml(String(section.tick))}"
    >
      <div class="log-tick-header">
        <span>t${escapeHtml(String(section.tick))}</span>
        <span>${escapeHtml(actionSummary)}</span>
      </div>
      <div class="log-subsections">
        ${renderLogSubsection("rules", "Instructions", renderInstructionsBlock(prompt.rules), { open: false })}
        ${renderLogSubsection("identity", "You Are", renderPromptOutline(prompt.identity, { richText: true }), { open: false })}
        ${renderLogSubsection("current", "Current State", renderCurrentState(prompt.current), { open: true })}
        ${renderLogSubsection("strategy", "Main Strategy", renderPromptOutline(prompt.strategy, { richText: true }), { open: false })}
        ${renderLogSubsection("thoughts", "LLM Thoughts", renderThoughts(section.action), { open: true })}
        ${renderLogSubsection("actions", "Pick an action", renderChoices(prompt.actions, section.action), { open: true })}
      </div>
    </article>
  `;
}

function renderLogSubsection(
  key: LogSubsectionKey,
  label: string,
  content: string,
  options: { open?: boolean } = {},
): string {
  const openAttribute = options.open ? " open" : "";

  return `
    <details class="log-subsection" data-log-subsection="${escapeHtml(key)}"${openAttribute}>
      <summary>
        <span>${escapeHtml(label)}</span>
      </summary>
      <div class="log-subsection-body">
        ${content}
      </div>
    </details>
  `;
}

function renderThoughts(action: ParsedLogAction | undefined): string {
  if (action?.thoughts) {
    return `<p class="log-thoughts">${escapeHtml(action.thoughts)}</p>`;
  }

  const controllerNote = action?.intent
    ? `<p class="log-controller-note">Controller note: ${escapeHtml(action.intent)}</p>`
    : "";
  return `<p class="log-thoughts">No LLM thoughts recorded.</p>${controllerNote}`;
}

function renderInstructionsBlock(lines: string[]): string {
  return `
    <div class="log-instructions-block">
      ${lines.map((line) => `<p>${renderHighlightedPromptLine(line)}</p>`).join("")}
    </div>
  `;
}

type CurrentStateKind = "debating" | "chilling" | "witnessing" | "moving";

type ParsedCurrentState = {
  audience: string | undefined;
  extraLines: string[];
  kind: CurrentStateKind;
  locationLine: string | undefined;
  room: string | undefined;
  teamSize: string | undefined;
};

function renderCurrentState(lines: string[]): string {
  const state = parseCurrentState(lines);

  switch (state.kind) {
    case "debating":
      return renderDebatingCurrentState(state);
    case "witnessing":
      return renderWitnessingCurrentState(state);
    case "moving":
      return renderMovingCurrentState(state);
    case "chilling":
      return renderChillingCurrentState(state);
  }
}

function renderDebatingCurrentState(state: ParsedCurrentState): string {
  const opponent = parseDebateOpponent(state.locationLine);
  return renderCurrentStateCard(state, {
    title: "Debating",
    summary: state.room ? `In ${state.room}` : "In a debate",
    facts: [
      ["Opponent", opponent ?? "Unknown"],
      ["Room", state.room],
      ["Nearby teams", state.teamSize],
      ["Nearby guests", state.audience],
    ],
  });
}

function renderChillingCurrentState(state: ParsedCurrentState): string {
  return renderCurrentStateNarrative(state, {
    title: "Chilling",
    summary: state.room ? `Open in ${state.room}` : "Available",
    lines: chillingNarrativeLines(state),
  });
}

function renderWitnessingCurrentState(state: ParsedCurrentState): string {
  const witnessed = parseWitnessedDebate(state.locationLine);
  return renderCurrentStateCard(state, {
    title: "Witnessing",
    summary: state.room ? `Watching in ${state.room}` : "Watching a debate",
    facts: [
      ["Debate", witnessed ?? "Same-room debate"],
      ["Room", state.room],
      ["Nearby teams", state.teamSize],
      ["Nearby guests", state.audience],
    ],
  });
}

function renderMovingCurrentState(state: ParsedCurrentState): string {
  const movement = parseMovement(state.locationLine);
  return renderCurrentStateCard(state, {
    title: "Moving",
    summary: movement?.destination ? `To ${movement.destination}` : "In transit",
    facts: [
      ["Destination", movement?.destination],
      ["Arrival", movement?.arriveTick ? `t${movement.arriveTick}` : undefined],
      ["Nearby teams", state.teamSize],
      ["Nearby guests", state.audience],
    ],
  });
}

function renderCurrentStateCard(
  state: ParsedCurrentState,
  config: { title: string; summary: string; facts: Array<[string, string | undefined]> },
): string {
  const facts = config.facts.filter(([, value]) => Boolean(value && value !== "none"));
  const extraLines = state.extraLines.filter((line) => line !== "No transcript yet.");

  return `
    <div class="log-current-state is-${escapeHtml(state.kind)}" data-current-state="${escapeHtml(state.kind)}">
      <div class="log-current-state-header">
        <span>${escapeHtml(config.title)}</span>
        <strong>${escapeHtml(config.summary)}</strong>
      </div>
      <div class="log-current-state-grid">
        ${facts.map(([label, value]) => renderCurrentStateFact(label, value ?? "")).join("")}
      </div>
      ${extraLines.length > 0 ? renderCurrentStateTranscript(extraLines) : ""}
    </div>
  `;
}

function renderCurrentStateNarrative(
  state: ParsedCurrentState,
  config: { title: string; summary: string; lines: string[] },
): string {
  const lines = config.lines.length > 0
    ? config.lines
    : [state.room ? `You are in ${state.room}.` : "You are available."];

  return `
    <div class="log-current-state is-${escapeHtml(state.kind)}" data-current-state="${escapeHtml(state.kind)}">
      <div class="log-current-state-header">
        <span>${escapeHtml(config.title)}</span>
        <strong>${escapeHtml(config.summary)}</strong>
      </div>
      <div class="log-current-state-story">
        ${lines.map((line) => `<p>${escapeHtml(line)}</p>`).join("")}
      </div>
    </div>
  `;
}

function chillingNarrativeLines(state: ParsedCurrentState): string[] {
  const currentRoom = state.room;
  const audience = parseAudienceGuests(state.audience);
  const lines: string[] = [];
  const lastRoomByActor = new Map<string, string>();
  let noticed = false;
  let youInCurrentRoom = false;

  const appendNoticedGuests = (): void => {
    if (noticed) {
      return;
    }

    noticed = true;
    for (const guest of audience.values()) {
      lines.push(`You noticed ${guest.display}.`);
    }
  };

  for (const line of state.extraLines.map((extraLine) => stripSentencePeriod(extraLine.trim()))) {
    if (!line || line === "No transcript yet." || /^asking\b/i.test(line)) {
      continue;
    }

    const arrival = parseNarrativeArrival(line);
    if (arrival) {
      const previousRoom = lastRoomByActor.get(arrival.actor);
      lastRoomByActor.set(arrival.actor, arrival.room);
      if (currentRoom && sameRoomName(arrival.room, currentRoom)) {
        if (arrival.actor === "You") {
          youInCurrentRoom = true;
          lines.push(`You entered ${arrival.room}${previousRoom ? ` from ${previousRoom}` : ""}.`);
          appendNoticedGuests();
        } else {
          lines.push(`${audience.get(arrival.actor)?.display ?? arrival.actor} entered${previousRoom ? ` from ${previousRoom}` : ""}.`);
        }
      }
      continue;
    }

    const departure = parseNarrativeDeparture(line);
    if (departure) {
      if (departure.actor === "You" && (!currentRoom || youInCurrentRoom || sameRoomName(lastRoomByActor.get("You"), currentRoom))) {
        lines.push("You decided to move on.");
        youInCurrentRoom = false;
      }
      continue;
    }

    const debateStart = narrativeDebateStartLine(line);
    if (debateStart) {
      lines.push(debateStart);
      continue;
    }

    const flip = narrativeFlipLine(line);
    if (flip) {
      lines.push(flip);
    }
  }

  if (!noticed) {
    appendNoticedGuests();
  }

  return lines;
}

function parseAudienceGuests(audience: string | undefined): Map<string, { display: string }> {
  const guests = new Map<string, { display: string }>();
  if (!audience || audience === "none") {
    return guests;
  }

  for (const guestText of audience.split(/\),\s*/)) {
    const normalized = guestText.endsWith(")") ? guestText : `${guestText})`;
    const match = normalized.match(/^(.+?)\s+\((Red|Blue)\s+(\d+)\)$/i);
    if (!match?.[1] || !match[2] || !match[3]) {
      continue;
    }

    const name = match[1].trim();
    guests.set(name, { display: `${name} (${titleCase(match[2])}, ${match[3]})` });
  }
  return guests;
}

function parseNarrativeArrival(line: string): { actor: string; room: string } | undefined {
  const match = line.match(/^(.+?) arrived at (.+)$/i);
  return match?.[1] && match[2]
    ? { actor: normalizeNarrativeActor(match[1]), room: roomNameFromMoveDestination(match[2]) }
    : undefined;
}

function parseNarrativeDeparture(line: string): { actor: string; destination: string } | undefined {
  const match = line.match(/^(.+?) started moving to (.+)$/i);
  return match?.[1] && match[2]
    ? { actor: normalizeNarrativeActor(match[1]), destination: roomNameFromMoveDestination(match[2]) }
    : undefined;
}

function normalizeNarrativeActor(actor: string): string {
  return actor.trim();
}

function roomNameFromMoveDestination(destination: string): string {
  return stripSentencePeriod(destination).replace(/\s+-\s+.+$/, "").trim();
}

function sameRoomName(left: string | undefined, right: string | undefined): boolean {
  return Boolean(left && right && left.toLowerCase() === right.toLowerCase());
}

function narrativeDebateStartLine(line: string): string | undefined {
  const match = line.match(/^(.+?) and (.+?) start(?:ed)? debating$/i);
  return match?.[1] && match[2] ? `${match[1]} and ${match[2]} started debating.` : undefined;
}

function narrativeFlipLine(line: string): string | undefined {
  const match = line.match(/^(.+?) (?:converted|shuffled) from \w+ to (red|blue)\b/i);
  return match?.[1] && match[2] ? `${match[1]} flipped to ${titleCase(match[2])}.` : undefined;
}

function renderCurrentStateFact(label: string, value: string): string {
  return `
    <div class="log-current-state-fact">
      <span>${escapeHtml(label)}</span>
      <p>${renderHighlightedPromptText(value)}</p>
    </div>
  `;
}

function renderCurrentStateTranscript(lines: string[]): string {
  return `
    <div class="log-current-state-transcript">
      <span>Transcript</span>
      ${lines.map((line) => `<p>${renderHighlightedPromptText(line)}</p>`).join("")}
    </div>
  `;
}

function parseCurrentState(lines: string[]): ParsedCurrentState {
  const teamSizeLine = lines.find((line) => line.startsWith("Nearby Team Size:"));
  const audienceLine = lines.find((line) => line.startsWith("Nearby guests:"));
  const movementLine = lines.find((line) => /^You're moving\b/i.test(line));
  const roomStateLine = lines.find((line) => /^You're in \[/i.test(line));
  const locationLine = movementLine ?? roomStateLine;
  const kind = currentStateKind(locationLine);
  const structuralLines = new Set([teamSizeLine, audienceLine, locationLine].filter((line): line is string => Boolean(line)));

  return {
    audience: audienceLine ? valueAfterLabel(audienceLine) : undefined,
    extraLines: lines.filter((line) => !structuralLines.has(line)),
    kind,
    locationLine,
    room: parseRoomName(locationLine),
    teamSize: teamSizeLine ? valueAfterLabel(teamSizeLine) : undefined,
  };
}

function currentStateKind(locationLine: string | undefined): CurrentStateKind {
  if (!locationLine) {
    return "chilling";
  }
  if (/^You're moving\b/i.test(locationLine)) {
    return "moving";
  }
  if (/\bwitnessing\b/i.test(locationLine)) {
    return "witnessing";
  }
  if (/\bdebating\b/i.test(locationLine)) {
    return "debating";
  }
  return "chilling";
}

function parseRoomName(line: string | undefined): string | undefined {
  return line?.match(/\[([^\]]+)\]/)?.[1];
}

function parseDebateOpponent(line: string | undefined): string | undefined {
  const opponent = line?.match(/\]\s+debating\s+(.+?)(?:\s+\(|\.?$)/i)?.[1];
  return opponent ? stripSentencePeriod(opponent) : undefined;
}

function parseWitnessedDebate(line: string | undefined): string | undefined {
  const debate = line?.match(/\]\s+witnessing\s+(.+?)\.?$/i)?.[1];
  return debate ? stripSentencePeriod(debate) : undefined;
}

function parseMovement(line: string | undefined): { arriveTick?: string; destination?: string } | undefined {
  if (!line) {
    return undefined;
  }

  const match = line.match(/\[([^\]]+)\](?:,\s+arriving\s+t(\d+))?/i);
  return match ? { arriveTick: match[2], destination: match[1] } : undefined;
}

function valueAfterLabel(line: string): string {
  const [, value = line] = line.split(/:(.*)/s);
  return stripSentencePeriod(value.trim());
}

function stripSentencePeriod(value: string): string {
  return value.endsWith(".") ? value.slice(0, -1) : value;
}

function renderChoices(lines: string[], action: ParsedLogAction | undefined): string {
  const normalizedLines = lines.map(normalizeRandomChoiceLine);
  const selectedIndex = selectedChoiceLineIndex(normalizedLines, action);
  const displayLines = normalizedLines.map(formatDisplayedActionChoice);
  return `
    <div class="log-choice-copy">
      ${renderPromptOutline(displayLines, {
        selectedLine: (_line, index) => selectedIndex === index,
      })}
    </div>
  `;
}

function formatDisplayedActionChoice(line: string): string {
  const moveMatch = line.match(/^(\d+\.\s+)Move to\s+(.+?)(?:\s+\([a-z0-9_-]+\))?$/i);
  if (moveMatch) {
    return `${moveMatch[1]}Move To: ${moveMatch[2]}`;
  }

  return line;
}

function normalizeRandomChoiceLine(line: string): string {
  const match = line.match(/^Random choice:\s*([A-Z])$/i);
  if (!match?.[1]) {
    return line;
  }

  return `Random choice: ${match[1].toUpperCase().charCodeAt(0) - 64}`;
}

function parsePromptSections(content: string): ParsedPromptSections {
  const sections: ParsedPromptSections = {
    rules: [],
    identity: [],
    current: [],
    strategy: [],
    actions: [],
  };
  const lines = content
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  if (parseStructuredPromptSections(lines, sections)) {
    return sectionsWithDefaults(sections);
  }

  for (const line of lines) {
    if (line.startsWith("State:") || line.startsWith("Certainty:") || line.startsWith("Doubt:")) {
      sections.identity.push(line);
    } else if (line.startsWith("Visible entities:") || line.startsWith("Visible terrain:") || line.startsWith("Recent events:")) {
      sections.current.push(line);
    } else if (line.startsWith("Your approach:") || line.startsWith("Main Strategy Prompt:")) {
      sections.strategy.push(line.replace(/^Your approach:\s*/, "").replace(/^Main Strategy Prompt:\s*/, ""));
    } else if (line.startsWith("Rules:")) {
      sections.rules.push(line);
    } else if (line.startsWith("Choose one action:")) {
      sections.actions.push(line);
    } else {
      sections.identity.push(line);
    }
  }

  return sectionsWithDefaults(sections);
}

function parseStructuredPromptSections(lines: string[], sections: ParsedPromptSections): boolean {
  const headingMap: Record<string, PromptSectionKey> = {
    "Game Rules": "rules",
    "Instructions:": "rules",
    "Identity and State": "identity",
    "You are:": "identity",
    "Your achievements are:": "identity",
    "Current State": "current",
    "Current State:": "current",
    "Main Strategy Prompt": "strategy",
    "Main Strategy Prompt:": "strategy",
    "Your approach:": "strategy",
    "Transcript:": "current",
    "Valid Actions": "actions",
    "Pick an action:": "actions",
  };
  let currentSection: PromptSectionKey | undefined;
  let foundHeading = false;

  for (const line of lines) {
    const heading = headingMap[line];
    if (heading) {
      currentSection = heading;
      foundHeading = true;
      continue;
    }

    if (!currentSection) {
      continue;
    }

    sections[currentSection].push(line.replace(/^- /, ""));
  }

  return foundHeading;
}

function sectionsWithDefaults(sections: ParsedPromptSections): ParsedPromptSections {
  if (sections.rules.length === 0) {
    sections.rules.push("No game rules recorded.");
  }
  if (sections.identity.length === 0) {
    sections.identity.push("No identity recorded.");
  }
  if (sections.current.length === 0) {
    sections.current.push("No current state recorded.");
  }
  if (sections.strategy.length === 0) {
    sections.strategy.push("No main strategy prompt recorded.");
  }
  if (sections.actions.length === 0) {
    sections.actions.push("No valid actions recorded.");
  }

  return sections;
}

type PromptOutlineOptions = {
  richText?: boolean;
  selectedLine?: (line: string, index: number) => boolean;
};

function renderPromptOutline(lines: string[], options: PromptOutlineOptions = {}): string {
  return `
    <div class="log-outline">
      ${lines.map((line, index) => renderPromptOutlineLine(line, Boolean(options.selectedLine?.(line, index)), Boolean(options.richText))).join("")}
    </div>
  `;
}

function renderPromptOutlineLine(line: string, selected: boolean, richText: boolean): string {
  const trimmed = line.trim();
  const nested = line.startsWith("  ") || trimmed.startsWith("-");
  const heading = trimmed.endsWith(":");
  const action = /^\d+\.\s/.test(trimmed);
  const className = [
    "log-outline-row",
    nested ? "is-nested" : "",
    heading ? "is-heading" : "",
    action ? "is-action" : "",
    selected ? "is-selected" : "",
  ].filter(Boolean).join(" ");
  const display = trimmed.replace(/^- /, "");
  const content = richText ? renderHighlightedPromptLine(display) : escapeHtml(display);

  return `<div class="${escapeHtml(className)}">${content}</div>`;
}

function renderHighlightedPromptLine(line: string): string {
  const trait = line.match(/^(\[[^\]]+\])(\s+-\s+)(.*)$/);
  if (trait) {
    return [
      `<strong class="log-emphasis log-emphasis-trait">${escapeHtml(trait[1] ?? "")}</strong>`,
      escapeHtml(trait[2] ?? ""),
      renderHighlightedPromptText(trait[3] ?? ""),
    ].join("");
  }

  const goal = line.match(/^([A-Z][A-Za-z0-9 ']+?)(?=[:[])(.*)$/);
  if (goal) {
    return [
      `<strong class="log-emphasis log-emphasis-goal">${escapeHtml((goal[1] ?? "").trim())}</strong>`,
      renderHighlightedPromptText(goal[2] ?? ""),
    ].join("");
  }

  return renderHighlightedPromptText(line);
}

function renderHighlightedPromptText(text: string): string {
  const highlightPattern = /\[[^\]]+\]|\b(?:Red|Blue)\b|\b(?:Reason|Spin|Passion|reason|spin|passion)\b|\b\d+(?:\.\d+)?%|\b\d+s\b/g;
  let html = "";
  let cursor = 0;
  for (const match of text.matchAll(highlightPattern)) {
    const token = match[0];
    const index = match.index ?? 0;
    html += escapeHtml(text.slice(cursor, index));
    html += renderPromptHighlightToken(token);
    cursor = index + token.length;
  }

  return html + escapeHtml(text.slice(cursor));
}

function renderPromptHighlightToken(token: string): string {
  if (/^\[[^\]]+\]$/.test(token)) {
    return `<strong class="log-emphasis log-emphasis-bracket">${escapeHtml(token)}</strong>`;
  }
  if (/^(?:Red|Blue)$/i.test(token)) {
    return `<strong class="log-emphasis log-emphasis-color" data-color="${escapeHtml(token.toLowerCase())}">${escapeHtml(token)}</strong>`;
  }
  if (/^(?:Reason|Spin|Passion)$/i.test(token)) {
    const tactic = token.toLowerCase() as DebateTactic;
    return `<strong class="log-emphasis log-emphasis-tactic" data-tactic="${escapeHtml(tactic)}"><span class="log-tactic-icon" aria-hidden="true">${escapeHtml(DEBATE_TACTIC_ICONS[tactic])}</span>${escapeHtml(token)}</strong>`;
  }
  return `<strong class="log-emphasis log-emphasis-number">${escapeHtml(token)}</strong>`;
}

function selectedChoiceLineIndex(lines: string[], action: ParsedLogAction | undefined): number | undefined {
  if (!action) {
    return undefined;
  }

  if (typeof action.choiceNumber === "number") {
    const choiceIndex = lines.findIndex((line) => choiceNumberForPromptLine(line) === action.choiceNumber);
    if (choiceIndex >= 0) {
      return choiceIndex;
    }
  }

  const matches = lines
    .map((line, index) => ({ index, line }))
    .filter(({ line }) => promptChoiceMatchesAction(line, action));
  return matches.length === 1 ? matches[0]?.index : undefined;
}

function choiceNumberForPromptLine(line: string): number | undefined {
  const match = line.trim().match(/^(\d+)\.\s/);
  return match?.[1] ? Number.parseInt(match[1], 10) : undefined;
}

function promptChoiceMatchesAction(line: string, action: ParsedLogAction): boolean {
  const label = line.trim().replace(/^\d+\.\s*/, "").toLowerCase();
  switch (action.type) {
    case "wait":
      return label === "wait";
    case "move":
      if (action.direction) {
        return label === `move ${action.direction}`;
      }
      return Boolean(action.roomId && label.includes(action.roomId.toLowerCase()));
    case "debate":
      return Boolean(action.targetId && label.includes(action.targetId.toLowerCase()));
    case "chooseTactic":
      return label === action.tactic;
    default:
      return false;
  }
}

function renderLineList(lines: string[]): string {
  return `
    <div class="log-line-list">
      ${lines.map((line) => `<div class="log-line">${escapeHtml(line)}</div>`).join("")}
    </div>
  `;
}

function renderFactGrid(lines: string[]): string {
  return `
    <div class="log-fact-grid">
      ${lines.map(renderFactCard).join("")}
    </div>
  `;
}

function renderFactCard(line: string): string {
  const [label, ...rest] = line.split(":");
  const value = rest.join(":").trim();

  return `
    <div class="log-fact-card">
      <span>${escapeHtml(value ? label : "State")}</span>
      <p>${escapeHtml(value || line)}</p>
    </div>
  `;
}

function renderTokenList(lines: string[]): string {
  const tokens = lines.flatMap(tokensFromPromptLine);
  if (tokens.length === 0) {
    return `<div class="log-token-list"><span class="log-token">none</span></div>`;
  }

  return `
    <div class="log-token-list">
      ${tokens.map((token) => `<span class="log-token">${escapeHtml(token)}</span>`).join("")}
    </div>
  `;
}

function tokensFromPromptLine(line: string): string[] {
  const [, value = line] = line.split(/:(.*)/s);
  return value
    .split(";")
    .map((token) => token.trim())
    .filter(Boolean);
}

function renderActionDetails(action: ParsedLogAction): string {
  const lines = [`action: ${action.type}`];
  if (action.direction) {
    lines.push(`direction: ${action.direction}`);
  }
  if (action.roomId) {
    lines.push(`room: ${action.roomId}`);
  }
  if (action.tactic) {
    lines.push(`tactic: ${action.tactic}`);
  }
  if (action.targetId) {
    lines.push(`target: ${action.targetId}`);
  }
  if (action.text) {
    lines.push(`text: ${action.text}`);
  }
  if (action.intent) {
    lines.push(`intent: ${action.intent}`);
  }

  return lines.join("\n");
}

function renderLogMessage(message: CogConversationMessage): string {
  return `
    <article class="log-message log-message-${escapeHtml(message.role)}">
      <div class="log-message-meta">
        <span>${escapeHtml(message.role)}</span>
      </div>
      <pre class="log-message-content">${escapeHtml(renderMessageContent(message))}</pre>
    </article>
  `;
}

function renderMessageContent(message: CogConversationMessage): string {
  if (message.role !== "assistant") {
    return message.content;
  }

  const action = parseLogAction(message.content);
  return action ? renderActionDetails(action) : message.content;
}

function parseLogAction(content: string): ParsedLogAction | undefined {
  let parsed: unknown;
  try {
    parsed = JSON.parse(content);
  } catch {
    return undefined;
  }

  if (!isRecord(parsed) || typeof parsed.type !== "string" || !isKnownActionType(parsed.type)) {
    return undefined;
  }

  const action: ParsedLogAction = {
    type: parsed.type,
  };
  if (typeof parsed.direction === "string") {
    action.direction = parsed.direction;
  }
  if (typeof parsed.roomId === "string") {
    action.roomId = parsed.roomId;
  }
  if (typeof parsed.choiceNumber === "number") {
    action.choiceNumber = parsed.choiceNumber;
  }
  if (typeof parsed.intent === "string") {
    action.intent = parsed.intent;
  }
  if (typeof parsed.thoughts === "string") {
    action.thoughts = parsed.thoughts;
  }
  if (typeof parsed.tactic === "string") {
    action.tactic = parsed.tactic;
  }
  if (typeof parsed.targetId === "string") {
    action.targetId = parsed.targetId;
  }
  if (typeof parsed.text === "string") {
    action.text = parsed.text;
  }

  return action;
}

function summarizeAction(action: ParsedLogAction): string {
  switch (action.type) {
    case "move":
      return action.direction ? `Move ${action.direction}` : "Move";
    case "debate":
      return action.targetId ? `Debate ${action.targetId}` : "Debate";
    case "chooseTactic":
      return action.tactic ? `Tactic ${action.tactic}` : "Tactic";
    case "wait":
      return "Wait";
    default:
      return action.type;
  }
}

const rolledCogNames = [
  "Ada",
  "Voss",
  "Mira",
  "Noor",
  "Quinn",
  "Sol",
  "Babbage",
  "Rhea",
  "Turing",
  "Lin",
  "Patch",
  "Vector",
  "Kip",
  "Juno",
  "Orbit",
] as const;

const rolledDescriptionArchetypes = [
  "round sky-blue Cog",
  "warm yellow cog-headed Cog",
  "soft lavender square Cog",
  "mint gear-shaped Cog",
  "compact copper Cog",
  "pearl-white round Cog",
  "teal gear-rim Cog",
  "golden mascot Cog",
  "violet square Cog",
  "seafoam toy Cog",
] as const;

const rolledDescriptionDetails = [
  "big dark eyes and a tiny smile",
  "bold brows and rosy cheeks",
  "wide eyes and a cheerful face",
  "dot eyes and pink cheeks",
  "a calm smile and bright eyes",
  "a simple face and soft blush",
  "a friendly face and rounded cheeks",
  "bright eyes and a neat little smile",
  "a cute face and dark ear caps",
  "a simple smile and toy-like shading",
] as const;

const rolledDescriptionSilhouettes = [
  "side ear caps and a small antenna",
  "a bright chest speaker",
  "a lightning-bolt chest plate",
  "a heart badge on its chest",
  "a pale round belly plate",
  "tiny bead-jointed limbs",
  "short boots and mitten hands",
  "a short cable tail",
  "a chunky gear silhouette",
  "a compact toy stance",
] as const;

const rolledDescriptionAccents = [
  "a simple chest emblem",
  "a rounded toy body",
  "tiny boots and a steady stance",
  "a clean mascot silhouette",
  "soft glossy highlights",
  "a small chest panel",
  "a simple round body",
  "a cute compact shape",
  "clean bright shading",
  "a bold friendly silhouette",
] as const;

function rollCogName(existingNames: string[]): string {
  const takenNames = new Set(existingNames.map((name) => name.trim().toLowerCase()).filter(Boolean));

  for (let attempt = 0; attempt < 12; attempt += 1) {
    const candidate = randomCogNameCandidate();
    if (!takenNames.has(candidate.toLowerCase())) {
      return candidate;
    }
  }

  return `${randomItem(rolledCogNames)}${Math.floor(10 + Math.random() * 90)}`;
}

function randomCogNameCandidate(): string {
  return randomItem(rolledCogNames);
}

function rollCogDescription(previous: DescriptionRollParts | undefined): { parts: DescriptionRollParts; text: string } {
  const parts = {
    archetype: randomItemExcept(rolledDescriptionArchetypes, previous?.archetype),
    detail: randomItemExcept(rolledDescriptionDetails, previous?.detail),
    silhouette: randomItemExcept(rolledDescriptionSilhouettes, previous?.silhouette),
    prop: randomItemExcept(rolledDescriptionAccents, previous?.prop),
    style: randomNumberExcept(5, previous?.style),
  };
  const variants = [
    `A ${parts.archetype} with ${parts.detail}, ${parts.silhouette}, and ${parts.prop}.`,
    `A ${parts.archetype} with ${parts.detail}; ${capitalizeSentence(parts.silhouette)}, with ${parts.prop}.`,
    `A ${parts.archetype}; ${capitalizeSentence(parts.silhouette)}, with ${parts.detail}.`,
    `A ${parts.archetype} showing ${parts.detail} and ${parts.prop}.`,
    `A ${parts.archetype} with ${parts.detail} and ${parts.silhouette}.`,
  ];

  const text = fitBuilderDescription(variants[parts.style] ?? variants[0]);

  return {
    parts,
    text,
  };
}

function capitalizeSentence(text: string): string {
  return `${text.slice(0, 1).toUpperCase()}${text.slice(1)}`;
}

function fitBuilderDescription(text: string): string {
  if (text.length <= BUILDER_APPEARANCE_MAX_LENGTH) {
    return text;
  }

  const clipped = text.slice(0, BUILDER_APPEARANCE_MAX_LENGTH - 1).replace(/[ ,;:.]+[^ ,;:.]*$/, "");
  return `${clipped.trimEnd()}.`;
}

function rollCogStrategy(): string {
  return randomItem(BUILDER_STRATEGY_PROMPTS);
}

function typedTextFrames(finalText: string, field: CogBuilderTextRollStep): TextRollFrame[] {
  const frames: TextRollFrame[] = [{ delay: 140, text: "" }];
  const typoIndexes = new Set<number>();
  const typoCandidates = Array.from(finalText)
    .map((character, index) => ({ character, index }))
    .filter(({ character, index }) => index > 1 && /[a-z]/i.test(character));
  const typoCount = finalText.length > 60 ? 2 : finalText.length > 8 ? 1 : 0;

  while (typoIndexes.size < typoCount && typoCandidates.length > 0) {
    const candidate = typoCandidates.splice(Math.floor(Math.random() * typoCandidates.length), 1)[0];
    if (candidate) {
      typoIndexes.add(candidate.index);
    }
  }

  let typed = "";
  for (let index = 0; index < finalText.length; index += 1) {
    const character = finalText[index] ?? "";
    if (typoIndexes.has(index)) {
      frames.push({ delay: 260, text: `${typed}${mistypedCharacter(character)}` });
      frames.push({ delay: 180, text: typed });
    }
    typed += character;
    frames.push({ delay: typingDelayForCharacter(character, field), text: typed });
  }

  return frames;
}

function typingDelayForCharacter(character: string, field: CogBuilderTextRollStep): number {
  const description = field === "appearance" || field === "strategy";
  if (character === " " || character === "\n") {
    return (description ? 56 : 120) + Math.floor(Math.random() * (description ? 38 : 70));
  }
  if (/[.,;:]/.test(character)) {
    return (description ? 170 : 230) + Math.floor(Math.random() * 90);
  }
  return (description ? 32 : 82) + Math.floor(Math.random() * (description ? 28 : 58));
}

function mistypedCharacter(character: string): string {
  const lowerCase = character.toLowerCase();
  const alphabet = "abcdefghijklmnopqrstuvwxyz";
  if (!alphabet.includes(lowerCase)) {
    return character;
  }

  let replacement = randomItem(alphabet.split(""));
  while (replacement === lowerCase) {
    replacement = randomItem(alphabet.split(""));
  }

  return character === lowerCase ? replacement : replacement.toUpperCase();
}

function arcadeTraitFrames<T extends string>(values: readonly T[], finalValue: T): T[] {
  if (values.length === 0) {
    return [finalValue];
  }

  const frames: T[] = [];
  const finalIndex = Math.max(0, values.indexOf(finalValue));
  const startIndex = Math.floor(Math.random() * values.length);
  const slowFrameCount = Math.max(2, Math.min(6, values.length));
  const tailStartIndex = (finalIndex - slowFrameCount + 1 + values.length * 3) % values.length;
  let fastFrameCount = Math.max(10, values.length * 2);
  while ((startIndex + fastFrameCount) % values.length !== tailStartIndex) {
    fastFrameCount += 1;
  }

  for (let index = 0; index < fastFrameCount; index += 1) {
    frames.push(values[(startIndex + index) % values.length] ?? finalValue);
  }

  for (let index = 0; index < slowFrameCount; index += 1) {
    frames.push(values[(tailStartIndex + index) % values.length] ?? finalValue);
  }

  return frames;
}

function arcadeTraitDelay(frameIndex: number, frameCount: number): number {
  const remaining = frameCount - frameIndex;
  if (remaining <= 1) {
    return 860;
  }
  if (remaining <= 2) {
    return 700;
  }
  if (remaining <= 3) {
    return 540;
  }
  if (remaining <= 4) {
    return 390;
  }
  if (remaining <= 6) {
    return 260;
  }
  if (remaining <= 8) {
    return 175;
  }
  return 100;
}

function arcadeTraitLandingDelay(): number {
  return 620;
}

function randomItemExcept<T extends string>(items: readonly T[], excluded: T | string | undefined): T {
  if (items.length <= 1 || !excluded) {
    return randomItem(items);
  }

  const eligible = items.filter((item) => item !== excluded);
  return randomItem(eligible.length ? eligible : items);
}

function randomNumberExcept(limit: number, excluded: number | undefined): number {
  if (limit <= 1) {
    return 0;
  }

  let value = Math.floor(Math.random() * limit);
  while (value === excluded) {
    value = Math.floor(Math.random() * limit);
  }
  return value;
}

function isKnownActionType(type: string): type is CogAction["type"] {
  return logActions.some((action) => action.type === type);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
