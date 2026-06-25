import { TRAIT_RULES } from "../../shared/rules";
import type { GeneratedCogSprite } from "../../shared/protocol";
import type { Color, PersonalGoal, SelectableTrait, SpriteColorUrls } from "../../shared/types";
import type { CogProfileUpdate } from "./cog-profile";
import { traits } from "./cog-traits";
import { escapeHtml } from "./html";

export type CogSpriteOption = GeneratedCogSprite;

export type CogBuilderSpriteRequest = {
  name: string;
  description: string;
  defensiveTrait: SelectableTrait;
  activeTrait: SelectableTrait;
  spriteRoll: number;
  count: number;
};

export type CogBuilderCreateRequest = Omit<CogProfileUpdate, "personalGoal"> & {
  color: Color;
  spriteSheetKey: string;
  spriteUrl: string;
  spriteUrls?: SpriteColorUrls;
};

export type CogBuilderDraft = Omit<CogProfileUpdate, "defensiveTrait" | "activeTrait" | "personalGoal"> & {
  appearanceDescription: string;
  defensiveTrait: SelectableTrait | undefined;
  activeTrait: SelectableTrait | undefined;
  personalGoal?: PersonalGoal;
  color: Color | undefined;
  customSpriteOpen?: boolean;
  selectedSpriteIndex: number;
  spriteRoll: number;
  sprites: CogSpriteOption[];
  traitChoiceSeed: number;
};

export type CogBuilderTraitKind = "defensiveTrait" | "activeTrait";

export type CogBuilderTraitRoll = {
  kind: CogBuilderTraitKind;
  value: string;
};

export type CogBuilderTextRollStep = "name" | "appearance" | "strategy";

export const cogBuilderSteps = [
  "intro",
  "name",
  "defensiveTrait",
  "activeTrait",
  "appearance",
  "strategy",
  "side",
] as const;

export type CogBuilderStep = (typeof cogBuilderSteps)[number];

const DEMO_SPRITE_URL = "/assets/cogshambo/sprite-sheets/cog-mira/frames/cog-mira-01.png";
export const BUILDER_APPEARANCE_MAX_LENGTH = 112;
export const BUILDER_DESCRIPTION_MAX_LENGTH = BUILDER_APPEARANCE_MAX_LENGTH;
export const BUILDER_STRATEGY_MAX_LENGTH = 1000;
const BUILDER_PRESET_SPRITE_ASSET_VERSION = "nano-banana-starters-20260515";

const BUILDER_STARTER_SPRITES: readonly CogSpriteOption[] = [
  starterSprite("cog-ada", "Avatar 1"),
  starterSprite("cog-babbage", "Avatar 2"),
  starterSprite("cog-mira", "Avatar 3"),
  starterSprite("cog-default", "Avatar 4"),
  starterSprite("cog-kip", "Avatar 5"),
  starterSprite("cog-relay", "Avatar 6"),
  starterSprite("cog-nova", "Avatar 7"),
  starterSprite("cog-sprocket", "Avatar 8"),
  starterSprite("cog-spark", "Avatar 9"),
  starterSprite("cog-toggle", "Avatar 10"),
];

const STEP_TITLES: Record<CogBuilderStep, string> = {
  intro: "Build a Cog",
  name: "Name your Cog",
  appearance: "Choose an avatar",
  defensiveTrait: "Choose trait 1",
  activeTrait: "Choose trait 2",
  strategy: "Define the Strategy",
  side: "Pick a Side",
};

const STEP_SUBTITLES: Record<CogBuilderStep, string> = {
  intro: "Name it, pick traits, shape its look, define its strategy, then pick a side.",
  name: "Give your Cog a name the room will remember.",
  appearance: "Keep it broad: shell, lens face, shape, and overall vibe.",
  defensiveTrait: "Pick one. Tap a trait to see what it does.",
  activeTrait: "Pick one. Tap a trait to see what it does.",
  strategy: "Write the main strategy prompt. You can keep editing this from the profile.",
  side: "Choose which team this Cog will fight for. This submits your Cog.",
};

export function createInitialBuilderDraft(): CogBuilderDraft {
  const sprites = starterBuilderSprites();

  return {
    name: randomItem(builderForenames),
    behaviorPrompt: randomItem(BUILDER_STRATEGY_PROMPTS),
    appearanceDescription: randomItem(builderAppearanceDescriptions),
    attributes: { energy: 5, focus: 5 },
    defensiveTrait: randomItem(traits),
    activeTrait: randomItem(traits),
    personalGoal: undefined,
    color: undefined,
    customSpriteOpen: false,
    selectedSpriteIndex: randomSpriteIndex(sprites),
    spriteRoll: 0,
    sprites,
    traitChoiceSeed: Math.floor(Math.random() * 1_000_000),
  };
}

export function createBuilderPreviewDraft(draft: CogBuilderDraft): CogBuilderDraft {
  return {
    ...draft,
    appearanceDescription: "",
    behaviorPrompt: "",
    attributes: { ...draft.attributes },
    sprites: draft.sprites.map((sprite) => ({
      ...sprite,
      ...(sprite.spriteUrls ? { spriteUrls: { ...sprite.spriteUrls } } : {}),
    })),
  };
}

export function renderCogBuilderPage(
  draft: CogBuilderDraft,
  creating: boolean,
  generatingSprites = false,
  spriteGenerationError: string | undefined = undefined,
  step: CogBuilderStep = "intro",
  rollingTrait: CogBuilderTraitRoll | undefined = undefined,
  typingStep: CogBuilderTextRollStep | undefined = undefined,
  previewDraft: CogBuilderDraft = draft,
): string {
  const selectedSprite = draft.sprites[draft.selectedSpriteIndex] ?? draft.sprites[0];
  const currentStep = cogBuilderSteps.includes(step) ? step : "intro";
  const stepIndex = cogBuilderSteps.indexOf(currentStep);
  const progress = Math.round((stepIndex / (cogBuilderSteps.length - 1)) * 100);
  const stepBusy = isBuilderStepBusy(currentStep, typingStep, rollingTrait);
  const canAdvance = !stepBusy && canAdvanceFromStep(draft, currentStep, selectedSprite);
  const spriteStatus = renderSpriteStatus(generatingSprites, spriteGenerationError);
  const displayPreviewDraft = createLiveTraitPreviewDraft(draft, previewDraft);

  return `
    <section class="cog-builder-page builder-wizard-page" aria-label="Cog Builder wizard">
      <form class="cog-builder-shell builder-wizard-shell" data-action="create-builder-cog">
        <button class="builder-close-icon" data-action="close-builder" type="button" aria-label="Close builder">Close</button>
        <div class="builder-step-counter">Step ${stepIndex + 1} of ${cogBuilderSteps.length}</div>
        <div class="builder-progress-track" aria-label="Builder progress">
          <span style="width: ${progress}%"></span>
        </div>
        <header class="builder-header">
          <div>
            <h1>${escapeHtml(STEP_TITLES[currentStep])}</h1>
          </div>
        </header>

        <div class="builder-wizard-stage" data-builder-step="${escapeHtml(currentStep)}">
          ${renderStepContent(
            draft,
            displayPreviewDraft,
            currentStep,
            selectedSprite,
            generatingSprites,
            spriteStatus,
            creating,
            rollingTrait,
            typingStep,
          )}
        </div>

        ${renderStepFooter(currentStep, canAdvance, generatingSprites, stepBusy)}
      </form>
    </section>
  `;
}

function createLiveTraitPreviewDraft(draft: CogBuilderDraft, previewDraft: CogBuilderDraft): CogBuilderDraft {
  return {
    ...previewDraft,
    defensiveTrait: draft.defensiveTrait,
    activeTrait: draft.activeTrait,
    color: draft.color,
  };
}

export function randomItem<T>(items: readonly T[]): T {
  const fallback = items[0];
  if (fallback === undefined) {
    throw new Error("Cannot pick a random item from an empty list");
  }

  return items[Math.floor(Math.random() * items.length)] ?? fallback;
}

export function sanitizeCogForename(value: string): string {
  return value
    .trim()
    .split(/\s+/)[0]
    ?.replace(/[^\p{L}\p{N}'-]/gu, "")
    .slice(0, 40) || "";
}

export function parseBuilderColor(value: string | undefined): Color | undefined {
  return value === "blue" || value === "red" ? value : undefined;
}

const builderForenames = [
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

const builderAppearanceDescriptions = [
  "A round sky-blue Cog with big eyes, side ear caps, a tiny antenna, and a bright speaker dial on its chest.",
  "A warm yellow cog-headed Cog with bold brows, rosy cheeks, and a lightning-bolt chest plate.",
  "A soft lavender square Cog with big eyes, rosy cheeks, a heart badge, and a short cable tail.",
  "A mint gear-shaped Cog with dot eyes, rosy cheeks, and a pale round belly plate.",
  "A compact toy Cog with a simple smile, side ear caps, and one clear chest emblem.",
] as const;

export const BUILDER_STRATEGY_PROMPTS = [
  "Prefer to use Reason unless the opponent keeps resorting to Passion. Hang out near the Main Stage.",
  "Start with Spin against Reason-heavy rivals, then switch to Passion if they get defensive. Hang out near the Sofa Nook.",
  "Use Passion to challenge hesitant opponents, but pivot to Reason when they repeat themselves. Hang out near the Conference Corner.",
  "Open with Reason, watch the last tactic they used, and only counter when they show a pattern. Hang out near the Lobby Entry.",
  "Use Spin when the room is crowded and Passion when a rival looks isolated. Hang out near the Center Cluster A.",
  "Prefer Reason in close debates, and avoid chasing opponents through empty rooms. Hang out near the Projection Wall Pair.",
  "Use Spin to unsettle confident rivals, and move on after two quiet ticks. Hang out near the Lobby Bar Queue.",
  "Use Passion against Spin, and back up teammates who just lost certainty. Hang out near the Back Lounge Left.",
  "Prefer Reason against Passion, and look for debates with shaky opponents. Hang out near the Exhibit Entry.",
  "Use Spin unless the opponent answers with Reason, then switch to Passion. Hang out near the Green Room.",
] as const;

function renderStepContent(
  draft: CogBuilderDraft,
  previewDraft: CogBuilderDraft,
  step: CogBuilderStep,
  selectedSprite: CogSpriteOption | undefined,
  generatingSprites: boolean,
  spriteStatus: string,
  creating: boolean,
  rollingTrait: CogBuilderTraitRoll | undefined,
  typingStep: CogBuilderTextRollStep | undefined,
): string {
  switch (step) {
    case "intro":
      return `
        ${renderBuilderAvatar(selectedSprite, "Demo Cog avatar")}
        ${renderBuilderStepPrompt(step)}
      `;
    case "name":
      return `
        ${renderBuilderAvatar(selectedSprite, "Cog preview")}
        ${renderBuilderStepPrompt(step)}
        <label class="builder-step-field${typingStep === "name" ? " is-typing" : ""}">
          <span>Name</span>
          <input
            aria-label="Cog name"
            autocomplete="off"
            data-builder-field="name"
            maxlength="40"
            name="name"
            pattern="[^\\s]+"
            placeholder="Ada"
            required
            type="text"
            value="${escapeHtml(draft.name)}"
          />
        </label>
      `;
    case "appearance":
      return `
        ${renderBuilderProfileAside(previewDraft, selectedSprite)}
        ${renderBuilderStepPrompt(step)}
        <section class="builder-avatar-step" aria-label="Cog avatar builder">
          <div class="builder-sprite-grid">
            ${draft.sprites.map((sprite, index) => renderBuilderSpriteOption(sprite, index, index === draft.selectedSpriteIndex)).join("")}
            ${renderBuilderCustomSpriteOption(Boolean(draft.customSpriteOpen), generatingSprites)}
          </div>
          ${draft.customSpriteOpen ? renderBuilderCustomSpriteControls(draft, generatingSprites, spriteStatus, typingStep) : ""}
        </section>
      `;
    case "defensiveTrait":
      return `
        ${renderBuilderProfileAside(previewDraft, selectedSprite)}
        ${renderBuilderStepPrompt(step)}
        ${renderBuilderTraitChoices("Trait 1", "defensiveTrait", traits, draft.defensiveTrait, rollingTrait, draft.traitChoiceSeed)}
      `;
    case "activeTrait":
      return `
        ${renderBuilderProfileAside(previewDraft, selectedSprite)}
        ${renderBuilderStepPrompt(step)}
        ${renderBuilderTraitChoices("Trait 2", "activeTrait", traits, draft.activeTrait, rollingTrait, draft.traitChoiceSeed)}
      `;
    case "strategy":
      return `
        ${renderBuilderProfileAside(previewDraft, selectedSprite)}
        ${renderBuilderStepPrompt(step)}
        <label class="builder-step-field builder-strategy-field${typingStep === "strategy" ? " is-typing" : ""}">
          <span>Main Strategy</span>
          <textarea
            aria-label="Cog main strategy"
            data-builder-field="strategy"
            maxlength="${BUILDER_STRATEGY_MAX_LENGTH}"
            name="strategy"
            placeholder="Prefer to use Reason unless the opponent keeps resorting to Passion. Hang out near the Main Stage."
            required
            rows="6"
          >${escapeHtml(draft.behaviorPrompt)}</textarea>
        </label>
      `;
    case "side":
      return `
        ${renderBuilderStepPrompt(step)}
        ${renderBuilderSideChoices(draft.color, creating)}
      `;
  }
}

function renderStepFooter(
  step: CogBuilderStep,
  canAdvance: boolean,
  generatingSprites: boolean,
  stepBusy: boolean,
): string {
  if (step === "side") {
    return `
      <footer class="builder-step-footer">
        <button class="builder-secondary-button" data-action="builder-back" type="button">Back</button>
      </footer>
    `;
  }

  const primaryLabel = step === "intro" ? "Begin" : "Continue";
  const disabled = !canAdvance || generatingSprites ? " disabled" : "";
  const backButton = step === "intro"
    ? ""
    : `<button class="builder-secondary-button" data-action="builder-back" type="button">Back</button>`;
  const rollButton = canRollBuilderStep(step) ? renderBuilderRollButton(step, generatingSprites || stepBusy) : "";
  const footerClass = rollButton ? " has-roll" : "";
  const introCopy = step === "intro" ? renderBuilderIntroFooterCopy() : "";

  return `
    <footer class="builder-step-footer${footerClass}">
      ${introCopy}
      ${backButton}
      <button class="builder-next-button" data-action="builder-next" type="button"${disabled}>${primaryLabel}</button>
      ${rollButton}
    </footer>
  `;
}

function renderBuilderIntroFooterCopy(): string {
  return `
    <div class="builder-intro-copy">
      <strong>Ready for the argument pit?</strong>
      <span>Create a social player for the room display<br />and control it from here.</span>
    </div>
  `;
}

function canRollBuilderStep(step: CogBuilderStep): boolean {
  return step !== "intro" && step !== "side";
}

function renderBuilderRollButton(step: CogBuilderStep, generatingSprites: boolean): string {
  const label = step === "appearance" ? "Roll a look prompt" : "Roll a suggestion";

  return `
    <button
      aria-label="${escapeHtml(label)}"
      class="builder-roll-button"
      data-action="roll-builder-step"
      title="${escapeHtml(label)}"
      type="button"
      ${generatingSprites ? "disabled" : ""}
    >
      ${renderBuilderDie()}
    </button>
  `;
}

function renderBuilderDie(): string {
  return `
    <span class="builder-die" aria-hidden="true">
      <span></span><span></span><span></span><span></span><span></span>
    </span>
  `;
}

function renderBuilderAvatar(selectedSprite: CogSpriteOption | undefined, alt: string): string {
  const imageUrl = selectedSprite ? spritePreviewUrl(selectedSprite) : DEMO_SPRITE_URL;

  return `
    <div class="builder-avatar-orbit" aria-label="${escapeHtml(alt)}">
      <img alt="${escapeHtml(alt)}" src="${escapeHtml(imageUrl)}" />
    </div>
  `;
}

function renderBuilderStepPrompt(step: CogBuilderStep): string {
  return `<p class="builder-step-prompt">${escapeHtml(STEP_SUBTITLES[step])}</p>`;
}

function renderBuilderProfileAside(
  draft: CogBuilderDraft,
  selectedSprite: CogSpriteOption | undefined,
): string {
  const description = previewBuilderDescription(draft.appearanceDescription);
  const descriptionMarkup = description ? `<p>${escapeHtml(description)}</p>` : "";

  return `
    <aside class="builder-profile-aside" aria-label="Current Cog draft">
      <span class="builder-draft-name">${escapeHtml(draft.name.trim() || "NAME")}</span>
      ${renderBuilderAvatar(selectedSprite, "Cog preview")}
      ${descriptionMarkup}
      ${renderBuilderTraitPreview(draft)}
    </aside>
  `;
}

function renderBuilderTraitPreview(draft: CogBuilderDraft): string {
  const rows: Array<{ kind: CogBuilderTraitKind; label: string; value: string | undefined }> = [
    { kind: "defensiveTrait", label: "Trait 1", value: draft.defensiveTrait },
    { kind: "activeTrait", label: "Trait 2", value: draft.activeTrait },
  ];
  const visibleRows = rows.filter((row) => row.value);

  if (visibleRows.length === 0) {
    return "";
  }

  return `
    <div class="builder-profile-traits" aria-label="Selected traits">
      ${visibleRows
        .map((row) => {
          return `
            <span class="builder-profile-trait">
              <em>${escapeHtml(row.label)}</em>
              <strong>${escapeHtml(traitDisplayLabel(row.kind, row.value ?? ""))}</strong>
            </span>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderBuilderTraitChoices<T extends string>(
  label: string,
  kind: CogBuilderTraitKind,
  values: readonly T[],
  selectedValue: T | undefined,
  rollingTrait: CogBuilderTraitRoll | undefined = undefined,
  seed = 0,
): string {
  const rollingValue = rollingTrait?.kind === kind ? rollingTrait.value : undefined;
  const visibleValues = builderTraitChoiceValues(kind, values, selectedValue, seed);

  return `
    <section class="builder-choice-stack" aria-label="${escapeHtml(label)} choices">
      <span class="builder-choice-label">${escapeHtml(label)}</span>
      ${visibleValues.map((value) => renderBuilderTraitChoice(kind, value, value === selectedValue, value === rollingValue)).join("")}
    </section>
  `;
}

function renderBuilderCustomSpriteOption(open: boolean, generatingSprites: boolean): string {
  const openClass = open ? " is-custom-open" : "";
  return `
    <button
      aria-busy="${generatingSprites}"
      aria-label="Custom"
      aria-pressed="${open}"
      class="builder-sprite-option builder-sprite-option-custom${openClass}${generatingSprites ? " is-generating" : ""}"
      data-action="open-builder-custom-sprite"
      type="button"
      ${generatingSprites ? "disabled" : ""}
    >
      <strong>Custom</strong>
      <span>${escapeHtml(generatingSprites ? "Generating..." : "Describe + generate")}</span>
    </button>
  `;
}

function renderBuilderCustomSpriteControls(
  draft: CogBuilderDraft,
  generatingSprites: boolean,
  spriteStatus: string,
  typingStep: CogBuilderTextRollStep | undefined,
): string {
  return `
    <div class="builder-custom-sprite-panel">
      <label class="builder-step-field builder-appearance-field${typingStep === "appearance" ? " is-typing" : ""}">
        <span>Describe the look</span>
        <textarea
          aria-label="Cog appearance"
          data-builder-field="appearance"
          maxlength="${BUILDER_APPEARANCE_MAX_LENGTH}"
          name="appearance"
          placeholder="A round sky-blue Cog with big eyes, side ear caps, and a bright chest speaker."
          rows="5"
        >${escapeHtml(draft.appearanceDescription)}</textarea>
      </label>
      ${spriteStatus}
      <button
        aria-busy="${generatingSprites}"
        class="builder-custom-sprite-generate"
        data-action="regenerate-builder-sprites"
        type="button"
        ${generatingSprites ? "disabled" : ""}
      >
        ${escapeHtml(generatingSprites ? "Generating..." : "Generate custom sprite")}
      </button>
    </div>
  `;
}

function renderBuilderTraitChoice(
  kind: CogBuilderTraitKind,
  value: string,
  selected: boolean,
  rolling: boolean,
): string {
  const rule = TRAIT_RULES.find((candidate) => candidate.id === value);
  const selectedClass = selected ? " is-selected" : "";
  const rollingClass = rolling ? " is-rolling" : "";

  return `
    <button
      aria-pressed="${selected}"
      class="builder-choice-button${selectedClass}${rollingClass}"
      data-action="set-builder-trait"
      data-trait-kind="${escapeHtml(kind)}"
      data-trait-value="${escapeHtml(value)}"
      type="button"
    >
      <strong>${escapeHtml(rule?.label ?? titleCase(value))}</strong>
      <span>${escapeHtml(rule?.description ?? value)}</span>
    </button>
  `;
}

const BUILDER_SIDES: ReadonlyArray<{
  color: Color;
  title: string;
  teamName: string;
  lines: readonly string[];
  closer: string;
}> = [
  {
    color: "blue",
    title: "The Blue Team",
    teamName: "Team Zander",
    lines: [
      "We stand for optimism and possibility, and the power to create anything we dream of.",
      "Reality is what we make of it, and we can build it together.",
    ],
    closer: "We're also right.",
  },
  {
    color: "red",
    title: "The Red Team",
    teamName: "Team Takedown",
    lines: [
      "Truth, self reliance, and the clarity that comes when you stop trying to be comfortable.",
      "To find truth, let go of what you thought you knew.",
    ],
    closer: "We're also hotter.",
  },
];

function renderBuilderSideChoices(selectedColor: Color | undefined, creating: boolean): string {
  return `
    <section class="builder-side-grid" aria-label="Pick a Side">
      ${BUILDER_SIDES.map((side) => renderBuilderSideChoice(side, side.color === selectedColor, creating)).join("")}
    </section>
  `;
}

function renderBuilderSideChoice(side: (typeof BUILDER_SIDES)[number], selected: boolean, creating: boolean): string {
  const selectedClass = selected ? " is-selected" : "";
  const disabled = creating ? " disabled" : "";

  return `
    <button
      aria-pressed="${selected}"
      aria-label="${escapeHtml(creating && selected ? `Creating ${side.title} Cog` : `Join ${side.title}`)}"
      class="builder-side-card${selectedClass} is-${escapeHtml(side.color)}"
      data-action="set-builder-side"
      data-builder-color="${escapeHtml(side.color)}"
      ${disabled}
      type="button"
    >
      <strong>${escapeHtml(side.title)}</strong>
      <span>${escapeHtml(side.teamName)}</span>
      ${side.lines.map((line) => `<p>${escapeHtml(line)}</p>`).join("")}
      <em>${escapeHtml(creating && selected ? "Creating..." : side.closer)}</em>
    </button>
  `;
}

function renderBuilderSpriteOption(sprite: CogSpriteOption, index: number, selected: boolean): string {
  const selectedClass = selected ? " is-selected" : "";

  return `
    <button
      aria-pressed="${selected}"
      aria-label="Avatar option ${escapeHtml(String(index + 1))}"
      class="builder-sprite-option${selectedClass}"
      data-action="select-builder-sprite"
      data-sprite-index="${escapeHtml(String(index))}"
      type="button"
    >
      <img alt="" src="${escapeHtml(spritePreviewUrl(sprite))}" />
    </button>
  `;
}

function renderSpriteStatus(generatingSprites: boolean, spriteGenerationError: string | undefined): string {
  if (generatingSprites) {
    return `<span class="builder-sprite-status">Generating avatar...</span>`;
  }
  if (spriteGenerationError) {
    return `<span class="builder-sprite-status is-error">${escapeHtml(spriteGenerationError)}</span>`;
  }
  return "";
}

function canAdvanceFromStep(
  draft: CogBuilderDraft,
  step: CogBuilderStep,
  selectedSprite: CogSpriteOption | undefined,
): boolean {
  switch (step) {
    case "name":
      return sanitizeCogForename(draft.name).length > 0;
    case "appearance":
      return Boolean(selectedSprite);
    case "strategy":
      return (
        draft.behaviorPrompt.trim().length > 0 &&
        draft.behaviorPrompt.trim().length <= BUILDER_STRATEGY_MAX_LENGTH
      );
    case "defensiveTrait":
      return Boolean(draft.defensiveTrait);
    case "activeTrait":
      return Boolean(draft.activeTrait);
    case "side":
      return (
        Boolean(selectedSprite) &&
        sanitizeCogForename(draft.name).length > 0 &&
        draft.behaviorPrompt.trim().length > 0 &&
        draft.behaviorPrompt.trim().length <= BUILDER_STRATEGY_MAX_LENGTH &&
        Boolean(draft.defensiveTrait && draft.activeTrait && draft.color)
      );
    default:
      return true;
  }
}

function spritePreviewUrl(sprite: CogSpriteOption): string {
  return sprite.url;
}

function starterBuilderSprites(): CogSpriteOption[] {
  return BUILDER_STARTER_SPRITES.map((sprite) => ({
    ...sprite,
    ...(sprite.spriteUrls ? { spriteUrls: { ...sprite.spriteUrls } } : {}),
  }));
}

function randomSpriteIndex(sprites: readonly CogSpriteOption[]): number {
  return Math.max(0, Math.min(sprites.length - 1, Math.floor(Math.random() * sprites.length)));
}

function starterSprite(key: string, label: string): CogSpriteOption {
  const frameKey = key.startsWith("cog-") ? `${key}-01` : key;
  const baseUrl = `/assets/cogshambo/sprite-sheets/${spriteFolderForKey(key)}/frames/${frameKey}.png`;
  return {
    key,
    label,
    url: versionedPresetSpriteUrl(baseUrl),
  };
}

function spriteFolderForKey(key: string): string {
  return key.startsWith("builder-cog-jhrbpn") ? "builder-cog-jhrbpn" : key;
}

function versionedPresetSpriteUrl(url: string): string {
  return `${url}?v=${BUILDER_PRESET_SPRITE_ASSET_VERSION}`;
}

function previewBuilderDescription(description: string): string {
  const trimmed = description.trim();
  if (trimmed.length <= BUILDER_DESCRIPTION_MAX_LENGTH) {
    return trimmed;
  }

  return `${trimmed.slice(0, BUILDER_DESCRIPTION_MAX_LENGTH - 1).trimEnd()}.`;
}

function titleCase(value: string): string {
  return value
    .split(/[-_]/)
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function traitKindStep(kind: CogBuilderTraitKind | undefined): CogBuilderStep | undefined {
  return kind;
}

function isBuilderStepBusy(
  step: CogBuilderStep,
  typingStep: CogBuilderTextRollStep | undefined,
  rollingTrait: CogBuilderTraitRoll | undefined,
): boolean {
  return typingStep === step || traitKindStep(rollingTrait?.kind) === step;
}

function canRequestBuilderSprites(draft: CogBuilderDraft): boolean {
  const description = draft.appearanceDescription.trim();
  return (
    sanitizeCogForename(draft.name).length > 0 &&
    description.length > 0 &&
    description.length <= BUILDER_DESCRIPTION_MAX_LENGTH &&
    Boolean(draft.defensiveTrait && draft.activeTrait)
  );
}

function traitDisplayLabel(kind: CogBuilderTraitKind, value: string): string {
  const rule = TRAIT_RULES.find((candidate) => candidate.id === value);

  return rule?.label ?? titleCase(value);
}

function builderTraitChoiceValues<T extends string>(
  kind: CogBuilderTraitKind,
  values: readonly T[],
  selectedValue: T | undefined,
  seed: number,
): T[] {
  if (values.length <= 10) {
    return [...values];
  }

  const shuffled = seededShuffle(values, seed + stringSeed(kind));
  const choices = shuffled.slice(0, 10);
  if (selectedValue && !choices.includes(selectedValue)) {
    choices[choices.length - 1] = selectedValue;
  }
  return choices;
}

function seededShuffle<T>(values: readonly T[], seed: number): T[] {
  const shuffled = [...values];
  let state = seed || 1;
  for (let index = shuffled.length - 1; index > 0; index -= 1) {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    const swapIndex = state % (index + 1);
    [shuffled[index], shuffled[swapIndex]] = [shuffled[swapIndex] as T, shuffled[index] as T];
  }
  return shuffled;
}

function stringSeed(value: string): number {
  let hash = 2166136261;
  for (const character of value) {
    hash ^= character.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}
