import type {
  CreateCogRequest,
  CreateCogResponse,
  GenerateCogSpritesResponse,
  PokeCogResponse,
  UpdateCogProfileRequest,
} from "../shared/protocol";
import type { GameConfig, GameConfigInput, RuleParameter } from "../shared/rules";
import { SIMULATION_TICK_SECONDS } from "../shared/timing";
import type { Color, Trait, WorldSnapshot } from "../shared/types";
import { COG_ID_COOKIE_CLAIM_PARAM, clearCogIdCookie, readCogIdCookie, setCogIdCookie } from "./cog-cookie";
import {
  BUILDER_APPEARANCE_MAX_LENGTH,
  BUILDER_STRATEGY_MAX_LENGTH,
  cogBuilderSteps,
  createBuilderPreviewDraft,
  createInitialBuilderDraft,
  parseBuilderColor,
  randomItem,
  renderCogBuilderPage,
  type CogBuilderCreateRequest,
  type CogBuilderDraft,
  type CogBuilderSpriteRequest,
  type CogBuilderStep,
  type CogSpriteOption,
} from "./ui/cog-builder";
import type { CogProfileUpdate } from "./ui/cog-profile";
import { isTrait, traits } from "./ui/cog-traits";
import { escapeHtml } from "./ui/html";
import {
  DIARY_INITIAL_ROOM_LIMIT,
  DIARY_LOAD_MORE_ROOM_COUNT,
  renderCogProfilePage,
  renderConfigPage,
  type ConfigPayload,
  type ConfigTab,
  type ControllerLogFilters,
} from "./ui/hud";
import { mountVenueEditor } from "./ui/venue-editor";

type BuilderCreatedMessage = {
  type: "cogshambo-builder-created";
  cogId: string;
  snapshot: WorldSnapshot;
};

export type StandaloneRoute =
  | { kind: "builder" }
  | { kind: "config" }
  | { kind: "profile"; cogId: string };

type CogSnapshot = WorldSnapshot["cogs"][number];

const PROFILE_WINDOW_TARGET = "cogshambo-profile";
const BUILDER_NAME_ROLLS = ["Ada", "Babbage", "Mira", "Sprocket", "Helix", "Orbit", "Relay", "Nova"];
const BUILDER_DESCRIPTION_ROLLS = [
  "A brass strategist with a teal lens and a habit of arguing from park history.",
  "A bright compact cog that listens first, then turns every debate toward useful evidence.",
  "A restless room scout with polished gears, careful timing, and a stubborn sense of fairness.",
];
const TIMING_PARAMETER_KEYS = [
  "debatePrepTicks",
  "debateChoiceRevealTicks",
  "debateResultTicks",
  "debateCooldownTicks",
  "roomMoveCooldownTicks",
] as const;
const PROFILE_PULL_REFRESH_START_PX = 12;
const PROFILE_PULL_REFRESH_TRIGGER_PX = 74;
const PROFILE_PULL_REFRESH_MAX_PX = 96;
const PROFILE_PULL_REFRESH_HOLD_PX = 58;

type TimingParameterKey = (typeof TIMING_PARAMETER_KEYS)[number];

export function standaloneRouteForLocation(location = window.location): StandaloneRoute | undefined {
  const pathname = trimTrailingSlash(location.pathname);
  if (pathname === "/builder") {
    return { kind: "builder" };
  }
  if (pathname === "/config") {
    return { kind: "config" };
  }
  if (pathname.startsWith("/profile/")) {
    const encodedCogId = pathname.slice("/profile/".length);
    if (encodedCogId) {
      return { kind: "profile", cogId: decodeURIComponent(encodedCogId) };
    }
  }

  return undefined;
}

export function mountStandaloneRoute(route: StandaloneRoute): void {
  switch (route.kind) {
    case "builder":
      mountBuilderRoute();
      return;
    case "config":
      mountConfigRoute();
      return;
    case "profile":
      mountProfileRoute(route.cogId);
      return;
  }
}

function mountBuilderRoute(): void {
  const root = standaloneRoot("builder");
  root.innerHTML = `<section class="cog-builder-page" aria-label="Cog builder"><p>Loading builder...</p></section>`;
  void routeReturningBuilderCog()
    .then((routed) => {
      if (!routed) {
        mountBuilderForm(root);
      }
    })
    .catch(() => {
      mountBuilderForm(root);
    });
}

async function routeReturningBuilderCog(): Promise<boolean> {
  const cogId = readCogIdCookie();
  if (!cogId) {
    return false;
  }

  const snapshot = await fetchJson<WorldSnapshot>("/api/world");
  const cog = snapshot.cogs.find((candidate) => candidate.id === cogId);
  if (!cog) {
    clearCogIdCookie();
    return false;
  }

  window.location.replace(`/profile/${encodeURIComponent(cog.id)}`);
  return true;
}

function mountBuilderForm(root: HTMLElement): void {
  const draft = createInitialBuilderDraft();
  const previewDraft = createBuilderPreviewDraft(draft);
  let step: CogBuilderStep = "intro";
  let creating = false;
  let generatingSprites = false;
  let spriteError: string | undefined;

  const render = () => {
    root.innerHTML = renderCogBuilderPage(draft, creating, generatingSprites, spriteError, step, undefined, undefined, previewDraft);
    bindBuilderEvents();
  };

  const submitBuilder = (color?: Color) => {
    if (creating) {
      return;
    }
    if (color) {
      draft.color = color;
      commitBuilderStep(draft, previewDraft, "side");
    }
    const request = builderRequest(draft);
    if (!request) {
      render();
      return;
    }
    creating = true;
    spriteError = undefined;
    render();
    void createBuilderCog(request)
      .catch((error: unknown) => {
        spriteError = compactError(error);
      })
      .finally(() => {
        creating = false;
        render();
      });
  };

  const bindBuilderEvents = () => {
    root.querySelector("[data-action='close-builder']")?.addEventListener("click", () => {
      closeOrHome();
    });
    root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("[data-builder-field]").forEach((field) => {
      field.addEventListener("input", () => {
        if (field.dataset.builderField === "name") {
          draft.name = field.value;
        } else if (field.dataset.builderField === "appearance") {
          draft.appearanceDescription = field.value.slice(0, BUILDER_APPEARANCE_MAX_LENGTH);
        } else if (field.dataset.builderField === "strategy") {
          draft.behaviorPrompt = field.value.slice(0, BUILDER_STRATEGY_MAX_LENGTH);
        }
        updateBuilderControlsDisabled(root, draft, step, generatingSprites);
      });
    });
    root.querySelectorAll<HTMLButtonElement>("[data-action='builder-next']").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.disabled || !canAdvanceBuilderStep(draft, step)) {
          return;
        }
        commitBuilderStep(draft, previewDraft, step);
        step = cogBuilderSteps[Math.min(cogBuilderSteps.indexOf(step) + 1, cogBuilderSteps.length - 1)] ?? "intro";
        render();
      });
    });
    root.querySelectorAll<HTMLButtonElement>("[data-action='builder-back']").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.disabled) {
          return;
        }
        step = cogBuilderSteps[Math.max(cogBuilderSteps.indexOf(step) - 1, 0)] ?? "intro";
        render();
      });
    });
    root.querySelectorAll<HTMLButtonElement>("[data-action='set-builder-trait']").forEach((button) => {
      button.addEventListener("click", () => {
        setBuilderTrait(draft, button.dataset.traitKind, button.dataset.traitValue);
        render();
      });
    });
    root.querySelectorAll<HTMLButtonElement>("[data-action='set-builder-side']").forEach((button) => {
      button.addEventListener("click", () => {
        const color = parseBuilderColor(button.dataset.builderColor);
        if (!color) {
          return;
        }
        submitBuilder(color);
      });
    });
    root.querySelectorAll<HTMLButtonElement>("[data-action='roll-builder-step']").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.disabled) {
          return;
        }
        void rollBuilderStep(draft, step, render);
      });
    });
    root.querySelectorAll<HTMLButtonElement>("[data-action='roll-builder-description']").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.disabled) {
          return;
        }
        draft.behaviorPrompt = randomItem(BUILDER_DESCRIPTION_ROLLS);
        render();
      });
    });
    root.querySelector("[data-action='regenerate-builder-sprites']")?.addEventListener("click", () => {
      draft.spriteRoll += 1;
      draft.customSpriteOpen = true;
      void regenerateBuilderSprites();
    });
    root.querySelector<HTMLButtonElement>("[data-action='open-builder-custom-sprite']")?.addEventListener("click", () => {
      draft.customSpriteOpen = true;
      render();
    });
    root.querySelectorAll<HTMLButtonElement>("[data-action='select-builder-sprite']").forEach((button) => {
      button.addEventListener("click", () => {
        const index = Number.parseInt(button.dataset.spriteIndex ?? "", 10);
        if (Number.isInteger(index) && draft.sprites[index]) {
          draft.selectedSpriteIndex = index;
          draft.customSpriteOpen = false;
          render();
        }
      });
    });
    root.querySelector<HTMLFormElement>("[data-action='create-builder-cog']")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const form = event.currentTarget as HTMLFormElement;
      if (!form.reportValidity()) {
        return;
      }
      submitBuilder();
    });
  };

  const regenerateBuilderSprites = async () => {
    const request = builderSpriteRequest(draft);
    if (!request) {
      return;
    }
    generatingSprites = true;
    spriteError = undefined;
    render();

    try {
      const sprites = await generateCogSprites(request);
      if (sprites.length) {
        draft.sprites = sprites;
        draft.selectedSpriteIndex = 0;
      } else {
        spriteError = "Sprite generation unavailable. Try again.";
      }
    } catch (error) {
      spriteError = compactError(error);
    } finally {
      generatingSprites = false;
      render();
    }
  };

  render();
}

function mountConfigRoute(): void {
  const root = standaloneRoot("config");
  let payload: ConfigPayload | undefined;
  let activeTab: ConfigTab = "params";
  let disposeVenueEditor: (() => void) | undefined;

  const render = () => {
    disposeVenueEditor?.();
    disposeVenueEditor = undefined;
    root.innerHTML = payload
      ? renderConfigPage(payload, activeTab)
      : `<section class="config-page" aria-label="Game config page"><div class="config-page-scroll"><p>Loading config...</p></div></section>`;
    bindConfigEvents();
    if (activeTab === "venue") {
      const host = root.querySelector<HTMLElement>("[data-venue-editor-host]");
      if (host) {
        disposeVenueEditor = mountVenueEditor(host, { embedded: true });
      }
    }
  };

  const bindConfigEvents = () => {
    root.querySelector("[data-action='close-config']")?.addEventListener("click", () => {
      closeOrHome();
    });
    root.querySelectorAll<HTMLButtonElement>("[data-config-tab]").forEach((button) => {
      button.addEventListener("click", () => {
        const tab = button.dataset.configTab;
        if (isConfigTab(tab)) {
          activeTab = tab;
          render();
        }
      });
    });
    root.querySelectorAll<HTMLInputElement>("[data-config-key]").forEach((input) => {
      input.addEventListener("change", () => {
        const key = input.dataset.configKey;
        if (!key || !Number.isFinite(input.valueAsNumber)) {
          return;
        }
        void saveGameConfig({ [key]: input.valueAsNumber } as GameConfigInput, { rerender: false });
      });
    });
    root.querySelectorAll<HTMLInputElement>("[data-config-seconds-key]").forEach((input) => {
      input.addEventListener("change", () => {
        const key = input.dataset.configSecondsKey;
        if (!isTimingParameterKey(key) || !Number.isFinite(input.valueAsNumber)) {
          return;
        }
        const parameter = payload?.parameters.find((candidate) => candidate.key === key);
        void saveGameConfig({ [key]: secondsToTicks(input.valueAsNumber, parameter) } as GameConfigInput, {
          rerender: false,
        });
      });
    });
    root.querySelectorAll<HTMLInputElement>("[data-trait-config-key]").forEach((input) => {
      input.addEventListener("change", () => {
        const traitId = input.dataset.traitConfigId;
        const key = input.dataset.traitConfigKey;
        if (!traitId || !key || !Number.isFinite(input.valueAsNumber)) {
          return;
        }
        void saveGameConfig({
          traitConfig: {
            [traitId]: {
              [key]: input.valueAsNumber,
            },
          },
        } as GameConfigInput, { rerender: false });
      });
    });
    root.querySelectorAll<HTMLButtonElement>("[data-settings-preset-choice]").forEach((button) => {
      button.addEventListener("click", () => {
        const settingsDb = button.dataset.settingsPresetChoice;
        if (settingsDb) {
          void selectSettingsPreset(settingsDb);
        }
      });
    });
    root.querySelector<HTMLSelectElement>("[data-settings-preset-select]")?.addEventListener("change", (event) => {
      const settingsDb = (event.currentTarget as HTMLSelectElement).value;
      if (settingsDb) {
        void selectSettingsPreset(settingsDb);
      }
    });
    root.querySelector<HTMLFormElement>("[data-settings-preset-form]")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const input = (event.currentTarget as HTMLFormElement).elements.namedItem("settingsPresetName");
      if (!(input instanceof HTMLInputElement)) {
        return;
      }
      const name = input.value.trim();
      if (name) {
        input.value = "";
        void createSettingsPreset(name);
      }
    });
  };

  const saveGameConfig = async (config: GameConfigInput, options: { rerender: boolean }) => {
    const nextPayload = await patchJson<ConfigPayload>("/api/config", config);
    payload = nextPayload;
    if (options.rerender) {
      render();
    }
  };

  const selectSettingsPreset = async (settingsDb: string) => {
    payload = await patchJson<ConfigPayload>("/api/config/current", { settingsDb });
    render();
  };

  const createSettingsPreset = async (name: string) => {
    payload = await postJson<ConfigPayload>("/api/config/presets", { name });
    render();
  };

  render();
  void fetchJson<ConfigPayload>("/api/config")
    .then((loadedPayload) => {
      payload = loadedPayload;
      render();
    })
    .catch((error: unknown) => {
      root.innerHTML = renderStandaloneError("Config load failed", error);
    });
}

function mountProfileRoute(cogId: string): void {
  const root = standaloneRoot("profile");
  const drafts = new Map<string, CogProfileUpdate>();
  const diaryRoomLimits = new Map<string, number>();
  const shouldClaimCog = profileRouteShouldClaimCog();
  let controllerLogFilters: ControllerLogFilters = { debates: true, movement: true };
  let controllerLogOpen = false;
  let pendingControllerLogRestoreState: ControllerLogRouteRestoreState | undefined;
  let snapshot: WorldSnapshot | undefined;
  let gameConfig: GameConfig | undefined;

  type ControllerLogRouteRestoreState = {
    focusedFilter?: keyof ControllerLogFilters;
    profileScrollLeft: number;
    profileScrollTop: number;
    threadScrollLeft: number;
    threadScrollTop: number;
  };

  const captureControllerLogRestoreState = (focusedFilterOverride?: string): ControllerLogRouteRestoreState => {
    const profileScroll = root.querySelector<HTMLElement>(".cog-profile-scroll");
    const thread = root.querySelector<HTMLElement>(".profile-log-thread");
    const activeElement = document.activeElement;
    const focusedFilter = focusedFilterOverride ?? (activeElement instanceof HTMLElement && root.contains(activeElement)
      ? activeElement.dataset.controllerLogFilter
      : undefined);

    return {
      focusedFilter: focusedFilter === "debates" || focusedFilter === "movement" ? focusedFilter : undefined,
      profileScrollLeft: profileScroll?.scrollLeft ?? 0,
      profileScrollTop: profileScroll?.scrollTop ?? 0,
      threadScrollLeft: thread?.scrollLeft ?? 0,
      threadScrollTop: thread?.scrollTop ?? 0,
    };
  };

  const restoreControllerLogState = (state: ControllerLogRouteRestoreState): void => {
    const profileScroll = root.querySelector<HTMLElement>(".cog-profile-scroll");
    const thread = root.querySelector<HTMLElement>(".profile-log-thread");
    const focusedFilter = state.focusedFilter
      ? root.querySelector<HTMLElement>(
          `[data-action='toggle-controller-log-filter'][data-controller-log-filter='${state.focusedFilter}']`,
        )
      : undefined;

    if (profileScroll) {
      profileScroll.scrollLeft = state.profileScrollLeft;
      profileScroll.scrollTop = state.profileScrollTop;
    }
    if (thread) {
      thread.scrollLeft = state.threadScrollLeft;
      thread.scrollTop = state.threadScrollTop;
    }
    focusedFilter?.focus({ preventScroll: true });
    if (profileScroll) {
      profileScroll.scrollLeft = state.profileScrollLeft;
      profileScroll.scrollTop = state.profileScrollTop;
    }
    if (thread) {
      thread.scrollLeft = state.threadScrollLeft;
      thread.scrollTop = state.threadScrollTop;
    }
  };

  const render = (restoreState = captureControllerLogRestoreState()) => {
    const cog = snapshot?.cogs.find((candidate) => candidate.id === cogId);
    if (!snapshot) {
      root.innerHTML = `<section class="cog-profile-page" aria-label="Cog profile page"><div class="cog-profile-scroll"><p>Loading profile...</p></div></section>`;
    } else if (!cog) {
      root.innerHTML = renderStandaloneError("Profile not found", new Error(cogId));
    } else {
      root.innerHTML = renderCogProfilePage(
        cog,
        snapshot,
        draftFor(cog),
        gameConfig,
        undefined,
        false,
        0,
        diaryRoomLimits.get(cog.id) ?? DIARY_INITIAL_ROOM_LIMIT,
        controllerLogFilters,
      );
    }
    const controllerLog = root.querySelector<HTMLDetailsElement>(".profile-controller-log");
    if (controllerLog) {
      controllerLog.open = controllerLogOpen;
    }
    restoreControllerLogState(restoreState);
    bindProfileEvents();
  };

  const bindProfileEvents = () => {
    root.querySelector<HTMLDetailsElement>(".profile-controller-log")?.addEventListener("toggle", (event) => {
      controllerLogOpen = (event.currentTarget as HTMLDetailsElement).open;
    });
    root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("[data-profile-field]").forEach((field) => {
      field.addEventListener("input", () => {
        const profileField = field.dataset.profileField;
        const draft = ensureDraft();
        if (!draft) {
          return;
        }
        if (profileField === "name") {
          draft.name = field.value;
        } else if (profileField === "behaviorPrompt") {
          draft.behaviorPrompt = field.value;
          const cog = currentCog();
          if (cog) {
            void saveProfile(cog, profileForSave(cog, draft, { includeIdentityDraft: true }), { rerender: false });
          }
        }
      });
    });
    root.querySelectorAll<HTMLInputElement>("[data-profile-attribute]").forEach((input) => {
      input.addEventListener("input", () => {
        const key = input.dataset.profileAttribute;
        const cog = currentCog();
        const draft = ensureDraft();
        if (!key || !cog || !draft) {
          return;
        }
        draft.attributes[key] = Number.isFinite(input.valueAsNumber) ? input.valueAsNumber : 0;
        void saveProfile(cog, profileForSave(cog, draft, { includeIdentityDraft: false }), { rerender: false });
      });
    });
    root.querySelectorAll<HTMLButtonElement>("[data-action='set-trait']").forEach((button) => {
      button.addEventListener("click", () => {
        const cog = currentCog();
        const draft = ensureDraft();
        if (!cog || !draft) {
          return;
        }
        setProfileTrait(draft, button.dataset.traitKind, button.dataset.traitValue);
        void saveProfile(cog, profileForSave(cog, draft, { includeIdentityDraft: false }), { rerender: true });
      });
    });
    root.querySelectorAll<HTMLButtonElement>("[data-action='remove-attribute']").forEach((button) => {
      button.addEventListener("click", () => {
        const key = button.dataset.attributeKey;
        const cog = currentCog();
        const draft = ensureDraft();
        if (!key || !cog || !draft) {
          return;
        }
        delete draft.attributes[key];
        void saveProfile(cog, profileForSave(cog, draft, { includeIdentityDraft: false }), { rerender: true });
      });
    });
    root.querySelectorAll<HTMLButtonElement>("[data-action='add-attribute']").forEach((button) => {
      button.addEventListener("click", () => {
        const form = button.closest<HTMLFormElement>("[data-cog-id]");
        const keyInput = form?.querySelector<HTMLInputElement>("[data-profile-add-key]");
        const valueInput = form?.querySelector<HTMLInputElement>("[data-profile-add-value]");
        const key = keyInput?.value.trim();
        const cog = currentCog();
        const draft = ensureDraft();
        if (!key || !cog || !draft) {
          keyInput?.focus();
          return;
        }
        draft.attributes[key] = valueInput && Number.isFinite(valueInput.valueAsNumber) ? valueInput.valueAsNumber : 0;
        void saveProfile(cog, profileForSave(cog, draft, { includeIdentityDraft: false }), { rerender: true });
      });
    });
    root.querySelectorAll<HTMLFormElement>("[data-action='save-profile']").forEach((form) => {
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        const cog = currentCog();
        const draft = ensureDraft();
        if (cog && draft) {
          void saveProfile(cog, profileForSave(cog, draft, { includeIdentityDraft: true }), { rerender: true });
        }
      });
    });
    root.querySelectorAll<HTMLButtonElement>("[data-action='load-more-diary-rooms']").forEach((button) => {
      button.addEventListener("click", () => {
        const id = button.dataset.cogId ?? cogId;
        diaryRoomLimits.set(id, (diaryRoomLimits.get(id) ?? DIARY_INITIAL_ROOM_LIMIT) + DIARY_LOAD_MORE_ROOM_COUNT);
        render();
      });
    });
    root.querySelectorAll<HTMLButtonElement>("[data-action='toggle-controller-log-filter']").forEach((button) => {
      const captureRestoreState = () => {
        pendingControllerLogRestoreState = captureControllerLogRestoreState(button.dataset.controllerLogFilter);
      };
      button.addEventListener("pointerdown", captureRestoreState);
      button.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          captureRestoreState();
        }
      });
      button.addEventListener("click", () => {
        const filter = button.dataset.controllerLogFilter;
        if (filter !== "debates" && filter !== "movement") {
          return;
        }

        const restoreState = pendingControllerLogRestoreState ?? captureControllerLogRestoreState(filter);
        pendingControllerLogRestoreState = undefined;
        controllerLogOpen = true;
        controllerLogFilters = {
          ...controllerLogFilters,
          [filter]: !controllerLogFilters[filter],
        };
        render(restoreState);
      });
    });
    root.querySelectorAll<HTMLButtonElement>("[data-action='fill-cog-prompt']").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        const form = button.closest<HTMLFormElement>("[data-action='submit-cog-prompt']");
        const input = form?.elements.namedItem("mobileCogPrompt");
        const prompt = button.dataset.prompt?.trim();
        if (prompt && input instanceof HTMLTextAreaElement) {
          input.value = prompt;
          input.focus();
          input.setSelectionRange(input.value.length, input.value.length);
        }
      });
    });
    root.querySelectorAll<HTMLFormElement>("[data-action='submit-cog-prompt']").forEach((form) => {
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        const input = form.elements.namedItem("mobileCogPrompt");
        if (input instanceof HTMLTextAreaElement) {
          input.value = "";
          input.blur();
        }
      });
    });
    root.querySelectorAll<HTMLButtonElement>("[data-action='poke-cog']").forEach((button) => {
      button.addEventListener("click", () => {
        const id = button.dataset.cogId ?? cogId;
        if (!id || button.disabled) {
          return;
        }

        button.disabled = true;
        void postJson<PokeCogResponse>(`/api/cogs/${encodeURIComponent(id)}/poke`, {})
          .then((body) => {
            snapshot = body.snapshot;
            render();
          })
          .catch((error: unknown) => {
            button.disabled = false;
            root.innerHTML = renderStandaloneError("Poke failed", error);
          });
      });
    });
    root.querySelectorAll<HTMLButtonElement>("[data-action='toggle-mobile-actions']").forEach((button) => {
      button.addEventListener("click", () => {
        button.setAttribute("aria-expanded", button.getAttribute("aria-expanded") === "true" ? "false" : "true");
      });
    });
    root.querySelectorAll<HTMLButtonElement>("[data-action='abandon-cog']").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.disabled) {
          return;
        }

        button.disabled = true;
        clearCogIdCookie();
        window.location.href = "/builder";
      });
    });
  };

  const currentCog = () => snapshot?.cogs.find((candidate) => candidate.id === cogId);
  const ensureDraft = () => {
    const cog = currentCog();
    return cog ? draftFor(cog) : undefined;
  };

  const draftFor = (cog: CogSnapshot): CogProfileUpdate => {
    const existing = drafts.get(cog.id);
    if (existing) {
      return existing;
    }
    const draft: CogProfileUpdate = {
      name: cog.name,
      behaviorPrompt: cog.behaviorPrompt ?? "",
      attributes: { ...cog.attributes },
      defensiveTrait: cog.defensiveTrait,
      activeTrait: cog.activeTrait,
    };
    drafts.set(cog.id, draft);
    return draft;
  };

  const saveProfile = async (
    cog: CogSnapshot,
    profile: UpdateCogProfileRequest,
    options: { rerender: boolean },
  ) => {
    const body = await patchJson<{ snapshot?: WorldSnapshot }>(`/api/cogs/${encodeURIComponent(cog.id)}/profile`, profile);
    if (body.snapshot) {
      snapshot = body.snapshot;
    }
    if (options.rerender) {
      render();
    }
  };

  let profileRefreshPromise: Promise<void> | undefined;
  const refreshProfileRoute = (restoreState = captureControllerLogRestoreState()): Promise<void> => {
    profileRefreshPromise ??= Promise.all([fetchJson<WorldSnapshot>("/api/world"), fetchJson<ConfigPayload>("/api/config")])
      .then(([loadedSnapshot, configPayload]) => {
        snapshot = loadedSnapshot;
        gameConfig = configPayload.config;
        if (shouldClaimCog && loadedSnapshot.cogs.some((candidate) => candidate.id === cogId)) {
          setCogIdCookie(cogId);
        }
        render(restoreState);
      })
      .finally(() => {
        profileRefreshPromise = undefined;
      });

    return profileRefreshPromise;
  };

  bindProfilePullRefresh(root, () =>
    refreshProfileRoute().catch((error: unknown) => {
      root.innerHTML = renderStandaloneError("Profile refresh failed", error);
      throw error;
    }),
  );
  render();
  void refreshProfileRoute()
    .catch((error: unknown) => {
      root.innerHTML = renderStandaloneError("Profile load failed", error);
    });
}

function profileRouteShouldClaimCog(location = window.location): boolean {
  return new URL(location.href).searchParams.get(COG_ID_COOKIE_CLAIM_PARAM) === "1";
}

type ProfilePullRefreshGesture = {
  distance: number;
  page: HTMLElement;
  pointerId: number;
  pulling: boolean;
  scroll: HTMLElement;
  startX: number;
  startY: number;
};

function bindProfilePullRefresh(root: HTMLElement, refreshProfile: () => Promise<void>): void {
  let gesture: ProfilePullRefreshGesture | undefined;
  let refreshing = false;

  root.addEventListener("pointerdown", (event) => {
    if (refreshing || (event.pointerType === "mouse" && event.button !== 0)) {
      return;
    }
    if (!(event.target instanceof Element) || isProfilePullRefreshInteractiveTarget(event.target)) {
      return;
    }

    const scroll = event.target.closest<HTMLElement>(".cog-profile-scroll");
    const page = event.target.closest<HTMLElement>(".cog-profile-page");
    if (!scroll || !page || !root.contains(scroll) || scroll.scrollTop > 0) {
      return;
    }

    gesture = {
      distance: 0,
      page,
      pointerId: event.pointerId,
      pulling: false,
      scroll,
      startX: event.clientX,
      startY: event.clientY,
    };
  });

  root.addEventListener("pointermove", (event) => {
    if (!gesture || event.pointerId !== gesture.pointerId || refreshing) {
      return;
    }

    const deltaY = event.clientY - gesture.startY;
    const deltaX = Math.abs(event.clientX - gesture.startX);
    if (!gesture.pulling) {
      if (deltaY <= 0 || deltaX > deltaY || deltaY < PROFILE_PULL_REFRESH_START_PX || gesture.scroll.scrollTop > 0) {
        return;
      }
      gesture.pulling = true;
      try {
        root.setPointerCapture(event.pointerId);
      } catch {
        // Synthetic pointer events do not always create an active capture target.
      }
    }

    event.preventDefault();
    gesture.distance = Math.min(PROFILE_PULL_REFRESH_MAX_PX, Math.max(0, deltaY * 0.72));
    setProfilePullRefreshState(gesture.page, gesture.distance);
  }, { passive: false });

  const finishGesture = (event: PointerEvent) => {
    if (!gesture || event.pointerId !== gesture.pointerId) {
      return;
    }

    const finished = gesture;
    gesture = undefined;
    if (!finished.pulling || finished.distance < PROFILE_PULL_REFRESH_TRIGGER_PX) {
      resetProfilePullRefreshState(finished.page);
      return;
    }

    refreshing = true;
    finished.page.dataset.pullRefreshState = "refreshing";
    finished.page.style.setProperty("--profile-pull-distance", `${PROFILE_PULL_REFRESH_HOLD_PX}px`);
    void refreshProfile()
      .finally(() => {
        refreshing = false;
        resetProfilePullRefreshState(finished.page);
      })
      .catch(() => undefined);
  };

  root.addEventListener("pointerup", finishGesture);
  root.addEventListener("pointercancel", finishGesture);
}

function isProfilePullRefreshInteractiveTarget(target: Element): boolean {
  return Boolean(target.closest("a, button, input, select, summary, textarea, [contenteditable='true']"));
}

function setProfilePullRefreshState(page: HTMLElement, distance: number): void {
  page.dataset.pullRefreshState = distance >= PROFILE_PULL_REFRESH_TRIGGER_PX ? "ready" : "pulling";
  page.style.setProperty("--profile-pull-distance", `${Math.round(distance)}px`);
}

function resetProfilePullRefreshState(page: HTMLElement): void {
  page.style.removeProperty("--profile-pull-distance");
  delete page.dataset.pullRefreshState;
}

function standaloneRoot(kind: StandaloneRoute["kind"]): HTMLElement {
  const app = document.querySelector<HTMLElement>("#app");
  if (!app) {
    throw new Error("Missing #app");
  }
  app.classList.add("standalone-screen-root");
  app.dataset.route = kind;
  app.replaceChildren();
  return app;
}

function trimTrailingSlash(pathname: string): string {
  return pathname.length > 1 && pathname.endsWith("/") ? pathname.slice(0, -1) : pathname;
}

function closeOrHome(): void {
  if (window.opener) {
    window.close();
    window.setTimeout(() => {
      if (!window.closed) {
        window.location.href = "/";
      }
    }, 100);
    return;
  }
  window.location.href = "/";
}

function updateBuilderControlsDisabled(
  root: HTMLElement,
  draft: CogBuilderDraft,
  step: CogBuilderStep,
  generatingSprites: boolean,
): void {
  const nextButton = root.querySelector<HTMLButtonElement>("[data-action='builder-next']");
  if (nextButton) {
    nextButton.disabled = !canAdvanceBuilderStep(draft, step) || generatingSprites;
  }
  const generateButton = root.querySelector<HTMLButtonElement>("[data-action='regenerate-builder-sprites']");
  if (generateButton) {
    generateButton.disabled = !builderSpriteRequest(draft) || generatingSprites;
  }
}

function canAdvanceBuilderStep(draft: CogBuilderDraft, step: CogBuilderStep): boolean {
  const selectedSprite = draft.sprites[draft.selectedSpriteIndex] ?? draft.sprites[0];
  switch (step) {
    case "name":
      return draft.name.trim().length > 0;
    case "defensiveTrait":
      return Boolean(draft.defensiveTrait);
    case "activeTrait":
      return Boolean(draft.activeTrait);
    case "appearance":
      return Boolean(selectedSprite);
    case "strategy":
      return (
        draft.behaviorPrompt.trim().length > 0 &&
        draft.behaviorPrompt.trim().length <= BUILDER_STRATEGY_MAX_LENGTH
      );
    case "side":
      return (
        Boolean(selectedSprite) &&
        draft.name.trim().length > 0 &&
        draft.behaviorPrompt.trim().length > 0 &&
        draft.behaviorPrompt.trim().length <= BUILDER_STRATEGY_MAX_LENGTH &&
        Boolean(draft.defensiveTrait && draft.activeTrait && draft.color)
      );
    case "intro":
      return true;
  }
}

function commitBuilderStep(draft: CogBuilderDraft, previewDraft: CogBuilderDraft, step: CogBuilderStep): void {
  switch (step) {
    case "name":
      previewDraft.name = draft.name;
      return;
    case "defensiveTrait":
      previewDraft.defensiveTrait = draft.defensiveTrait;
      return;
    case "activeTrait":
      previewDraft.activeTrait = draft.activeTrait;
      return;
    case "appearance":
      previewDraft.appearanceDescription = draft.appearanceDescription;
      previewDraft.sprites = draft.sprites;
      previewDraft.selectedSpriteIndex = draft.selectedSpriteIndex;
      return;
    case "strategy":
      previewDraft.behaviorPrompt = draft.behaviorPrompt;
      return;
    case "side":
      previewDraft.color = draft.color;
      return;
    case "intro":
      return;
  }
}

async function rollBuilderStep(draft: CogBuilderDraft, step: CogBuilderStep, render: () => void): Promise<void> {
  switch (step) {
    case "name":
      draft.name = randomItem(BUILDER_NAME_ROLLS);
      render();
      return;
    case "defensiveTrait":
      draft.defensiveTrait = randomItem(traits);
      render();
      return;
    case "activeTrait":
      draft.activeTrait = randomItem(traits);
      render();
      return;
    case "appearance":
    case "strategy":
    case "side":
    case "intro":
      return;
  }
}

function setBuilderTrait(draft: CogBuilderDraft, kind: string | undefined, value: string | undefined): void {
  if (!kind || !value) {
    return;
  }
  if (kind === "defensiveTrait" && isTrait(value)) {
    draft.defensiveTrait = value;
  } else if (kind === "activeTrait" && isTrait(value)) {
    draft.activeTrait = value;
  }
}

function builderSpriteRequest(draft: CogBuilderDraft): CogBuilderSpriteRequest | undefined {
  const { activeTrait, defensiveTrait } = draft;
  if (!activeTrait || !defensiveTrait) {
    return undefined;
  }
  return {
    name: draft.name.trim(),
    description: draft.appearanceDescription.trim(),
    defensiveTrait,
    activeTrait,
    spriteRoll: draft.spriteRoll,
    count: 1,
  };
}

function builderRequest(draft: CogBuilderDraft): CogBuilderCreateRequest | undefined {
  const name = draft.name.trim();
  const behaviorPrompt = draft.behaviorPrompt.trim();
  const { activeTrait, defensiveTrait, color } = draft;
  const sprite = draft.sprites[draft.selectedSpriteIndex];
  if (!name || !behaviorPrompt || !sprite || !activeTrait || !defensiveTrait || !color) {
    return undefined;
  }
  return {
    name,
    behaviorPrompt,
    attributes: { ...draft.attributes },
    defensiveTrait,
    activeTrait,
    color,
    spriteSheetKey: sprite.key,
    spriteUrl: sprite.url,
    spriteUrls: sprite.spriteUrls,
  };
}

async function createBuilderCog(request: CogBuilderCreateRequest): Promise<void> {
  if (!isTrait(request.defensiveTrait) || !isTrait(request.activeTrait)) {
    throw new Error("Builder trait is not available for new cogs");
  }
  const payload: CreateCogRequest = {
    ...request,
    defensiveTrait: request.defensiveTrait,
    activeTrait: request.activeTrait,
    controllerId: "llm",
    color: request.color,
  };
  const body = await postJson<CreateCogResponse>("/api/cogs", payload);
  setCogIdCookie(body.cogId);
  notifyBuilderCreated(body.cogId, body.snapshot);
}

async function generateCogSprites(request: CogBuilderSpriteRequest): Promise<CogSpriteOption[]> {
  const body = await postJson<GenerateCogSpritesResponse>("/api/cog-sprites", request);
  return body.sprites;
}

function notifyBuilderCreated(cogId: string, snapshot: WorldSnapshot): void {
  if (window.opener) {
    window.opener.postMessage(
      {
        type: "cogshambo-builder-created",
        cogId,
        snapshot,
      } satisfies BuilderCreatedMessage,
      window.location.origin,
    );
    window.setTimeout(() => window.close(), 0);
    return;
  }

  window.location.href = `/profile/${encodeURIComponent(cogId)}`;
}

function profileForSave(
  cog: CogSnapshot,
  draft: CogProfileUpdate,
  options: { includeIdentityDraft: boolean },
): CogProfileUpdate {
  return {
    name: options.includeIdentityDraft ? draft.name : cog.name,
    behaviorPrompt: options.includeIdentityDraft ? draft.behaviorPrompt : cog.behaviorPrompt ?? draft.behaviorPrompt,
    attributes: { ...draft.attributes },
    defensiveTrait: cog.defensiveTrait === "zealot" ? "zealot" : draft.defensiveTrait,
    activeTrait: draft.activeTrait,
  };
}

function setProfileTrait(draft: CogProfileUpdate, kind: string | undefined, value: string | undefined): void {
  if (!kind || !value) {
    return;
  }
  if (kind === "defensiveTrait" && isTrait(value)) {
    draft.defensiveTrait = value as Trait;
  } else if (kind === "activeTrait" && isTrait(value)) {
    draft.activeTrait = value as Trait;
  }
}

function isConfigTab(value: string | undefined): value is ConfigTab {
  return value === "params" ||
    value === "timing" ||
    value === "traits" ||
    value === "achievements" ||
    value === "debates" ||
    value === "venue";
}

function isTimingParameterKey(value: string | undefined): value is TimingParameterKey {
  return TIMING_PARAMETER_KEYS.includes(value as TimingParameterKey);
}

function secondsToTicks(seconds: number, parameter: RuleParameter | undefined): number {
  const rawTicks = seconds / SIMULATION_TICK_SECONDS;
  const step = parameter?.step ?? 1;
  const steppedTicks = Math.round(rawTicks / step) * step;
  const min = parameter?.min ?? 0;
  const max = parameter?.max ?? Number.POSITIVE_INFINITY;
  return Math.max(min, Math.min(max, Math.round(steppedTicks)));
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await failureDetail(response));
  }
  return (await response.json()) as T;
}

async function postJson<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(await failureDetail(response));
  }
  return (await response.json()) as T;
}

async function patchJson<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(await failureDetail(response));
  }
  return (await response.json()) as T;
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
      return `${fallback} ${body.error}${detail}`;
    }
  } catch {
    // Fall back to the HTTP status.
  }
  return fallback;
}

function compactError(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message.length > 100 ? `${error.message.slice(0, 97)}...` : error.message;
  }
  return "network error";
}

function renderStandaloneError(title: string, error: unknown): string {
  return `
    <section class="config-page" aria-label="${escapeHtml(title)}">
      <div class="config-page-scroll">
        <header class="config-hero">
          <button class="profile-close-button" data-action="close-config" type="button">Close</button>
          <div>
            <h1>${escapeHtml(title)}</h1>
            <p>${escapeHtml(compactError(error))}</p>
          </div>
        </header>
      </div>
    </section>
  `;
}
