import { afterEach, describe, expect, it } from "vitest";

import { Hud, type ConfigPayload, type HudActions } from "../../src/client/ui/hud";
import { ACHIEVEMENT_RULES, DEFAULT_GAME_CONFIG, RULE_PARAMETERS, TRAIT_RULES } from "../../src/shared/rules";

const originalDocument = globalThis.document;
const originalElement = globalThis.Element;
const originalHTMLElement = globalThis.HTMLElement;
const originalHTMLInputElement = globalThis.HTMLInputElement;
const originalHTMLTextAreaElement = globalThis.HTMLTextAreaElement;
const originalHTMLSelectElement = globalThis.HTMLSelectElement;
const originalNode = globalThis.Node;

type SettingsTab = "params" | "timing" | "traits" | "achievements" | "debates" | "venue";

type SettingsRestoreTarget = {
  label: string;
  selector: string;
  tab: SettingsTab;
  type: "button" | "input";
};
type BuilderRestoreTarget = {
  label: string;
  selector: string;
  type: "button" | "textarea";
};

class FakeNodeShim {}
class FakeElementShim extends FakeNodeShim {}
class FakeHTMLElementShim extends FakeElementShim {}
class FakeHTMLInputElementShim extends FakeHTMLElementShim {}
class FakeHTMLTextAreaElementShim extends FakeHTMLElementShim {}
class FakeHTMLSelectElementShim extends FakeHTMLElementShim {}

const settingsRestoreTargets: SettingsRestoreTarget[] = [
  { label: "params", selector: '[data-config-key="debateDoubt"]', tab: "params", type: "input" },
  { label: "timing", selector: '[data-config-seconds-key="debatePrepTicks"]', tab: "timing", type: "input" },
  {
    label: "traits",
    selector: '[data-trait-config-id="contrarian"][data-trait-config-key="overwhelmingTeamThreshold"]',
    tab: "traits",
    type: "input",
  },
  { label: "achievements", selector: '[data-config-tab="achievements"]', tab: "achievements", type: "button" },
  { label: "debates", selector: '[data-config-tab="debates"]', tab: "debates", type: "button" },
  { label: "venue", selector: '[data-config-tab="venue"]', tab: "venue", type: "button" },
];

const builderRestoreTargets: BuilderRestoreTarget[] = [
  { label: "appearance", selector: '[data-builder-field="appearance"]', type: "textarea" },
  { label: "appearance roll", selector: '[data-action="roll-builder-step"]', type: "button" },
];

describe("settings render restore", () => {
  afterEach(() => {
    globalThis.document = originalDocument;
    globalThis.Element = originalElement;
    globalThis.HTMLElement = originalHTMLElement;
    globalThis.HTMLInputElement = originalHTMLInputElement;
    globalThis.HTMLTextAreaElement = originalHTMLTextAreaElement;
    globalThis.HTMLSelectElement = originalHTMLSelectElement;
    globalThis.Node = originalNode;
  });

  it.each(settingsRestoreTargets)("keeps $label settings scroll, state, and focus while updates refresh the HUD", (target) => {
    installSettingsRestoreDom();
    const element = new FakeSettingsRoot(target);
    const hud = new Hud(element as unknown as HTMLElement, stubActions);
    hud.update({ connectionStatus: "connected", gameConfig: configPayload() });
    hud.openConfigPage();
    (hud as unknown as { configTab: SettingsTab }).configTab = target.tab;
    hud.render();

    const focused = element.focusable;
    expect(focused).toBeDefined();
    if (focused instanceof HTMLInputElement) {
      focused.value = "unsaved draft";
      focused.selectionStart = 3;
      focused.selectionEnd = 9;
    }
    focused?.focus({ preventScroll: true });
    element.scrollContainer.scrollTop = 384;
    element.scrollContainer.scrollLeft = 17;

    hud.update({ notice: `refresh ${target.label}` });

    expect(element.innerHTML).toContain(`data-config-tab="${target.tab}"`);
    expect(element.innerHTML).toContain(`aria-selected="true"`);
    expect(globalThis.document.activeElement).toBe(element.focusable);
    expect(element.scrollContainer.scrollTop).toBe(384);
    expect(element.scrollContainer.scrollLeft).toBe(17);
    if (element.focusable instanceof HTMLInputElement) {
      expect(element.focusable.value).toBe("unsaved draft");
      expect(element.focusable.selectionStart).toBe(3);
      expect(element.focusable.selectionEnd).toBe(9);
    }
  });

  it.each(builderRestoreTargets)("keeps builder $label scroll, state, and focus while updates refresh the HUD", (target) => {
    installSettingsRestoreDom();
    const element = new FakeBuilderRoot(target);
    const hud = new Hud(element as unknown as HTMLElement, stubActions);
    hud.openBuilderPage();
    Object.assign(hud as unknown as {
      builderDraft: {
        activeTrait: string;
        appearanceDescription: string;
        behaviorPrompt: string;
        defensiveTrait: string;
        name: string;
      };
      builderStep: string;
    }, {
      builderStep: "appearance",
    });
    const builder = hud as unknown as {
      builderDraft: {
        activeTrait: string;
        appearanceDescription: string;
        behaviorPrompt: string;
        defensiveTrait: string;
        name: string;
      };
    };
    builder.builderDraft.name = "Helix";
    builder.builderDraft.appearanceDescription = "A brass passionate cog with a teal glass eye.";
    builder.builderDraft.defensiveTrait = "stubborn";
    builder.builderDraft.activeTrait = "passionate";
    hud.render();

    const focused = element.focusable;
    expect(focused).toBeDefined();
    if (focused instanceof HTMLTextAreaElement) {
      focused.value = "unsaved builder draft";
      focused.selectionStart = 4;
      focused.selectionEnd = 11;
    }
    focused?.focus({ preventScroll: true });
    element.shellScroll.scrollTop = 220;
    element.shellScroll.scrollLeft = 13;
    element.stageScroll.scrollTop = 44;
    element.stageScroll.scrollLeft = 5;

    hud.update({ notice: `refresh builder ${target.label}` });

    expect(element.innerHTML).toContain('data-builder-step="appearance"');
    expect(globalThis.document.activeElement).toBe(element.focusable);
    expect(element.shellScroll.scrollTop).toBe(220);
    expect(element.shellScroll.scrollLeft).toBe(13);
    expect(element.stageScroll.scrollTop).toBe(44);
    expect(element.stageScroll.scrollLeft).toBe(5);
    if (element.focusable instanceof HTMLTextAreaElement) {
      expect(element.focusable.value).toBe("unsaved builder draft");
      expect(element.focusable.selectionStart).toBe(4);
      expect(element.focusable.selectionEnd).toBe(11);
    }
  });
});

function configPayload(): ConfigPayload {
  return {
    achievements: ACHIEVEMENT_RULES,
    config: DEFAULT_GAME_CONFIG,
    goals: [],
    parameters: RULE_PARAMETERS,
    traits: TRAIT_RULES,
  };
}

function installSettingsRestoreDom(): void {
  globalThis.Node = FakeNodeShim as typeof Node;
  globalThis.Element = FakeElementShim as typeof Element;
  globalThis.HTMLElement = FakeHTMLElementShim as typeof HTMLElement;
  globalThis.HTMLInputElement = FakeHTMLInputElementShim as typeof HTMLInputElement;
  globalThis.HTMLTextAreaElement = FakeHTMLTextAreaElementShim as typeof HTMLTextAreaElement;
  globalThis.HTMLSelectElement = FakeHTMLSelectElementShim as typeof HTMLSelectElement;
  globalThis.document = { activeElement: undefined } as unknown as Document;
}

class FakeSettingsRoot extends FakeHTMLElementShim {
  private html = "";
  private readonly renderedElements = new Set<unknown>();
  focusable: FakeSettingsFocusable | undefined;
  scrollContainer = new FakeScrollContainer();

  constructor(private readonly target: SettingsRestoreTarget) {
    super();
  }

  get innerHTML(): string {
    return this.html;
  }

  set innerHTML(value: string) {
    this.html = value;
    this.scrollContainer = new FakeScrollContainer();
    this.focusable = this.target.type === "input"
      ? new FakeSettingsInput(this.target, this.scrollContainer)
      : new FakeSettingsButton(this.target, this.scrollContainer);
    this.renderedElements.clear();
    this.renderedElements.add(this.scrollContainer);
    this.renderedElements.add(this.focusable);
  }

  contains(element: unknown): boolean {
    return this.renderedElements.has(element);
  }

  addEventListener(): void {
    // Test double only needs listener attachment to be accepted.
  }

  querySelector<T extends Element>(selector: string): T | null {
    if (selector === this.target.selector) {
      return this.focusable as T;
    }

    return null;
  }

  querySelectorAll<T extends Element>(selector: string): T[] {
    if (selector === ".config-page-scroll") {
      return [this.scrollContainer as unknown as T];
    }

    return [];
  }
}

class FakeBuilderRoot extends FakeHTMLElementShim {
  private html = "";
  private readonly renderedElements = new Set<unknown>();
  focusable: FakeBuilderFocusable | undefined;
  shellScroll = new FakeScrollContainer();
  stageScroll = new FakeScrollContainer();

  constructor(private readonly target: BuilderRestoreTarget) {
    super();
  }

  get innerHTML(): string {
    return this.html;
  }

  set innerHTML(value: string) {
    this.html = value;
    this.shellScroll = new FakeScrollContainer();
    this.stageScroll = new FakeScrollContainer();
    this.focusable = this.target.type === "textarea"
      ? new FakeBuilderTextArea(this.target, this.stageScroll)
      : new FakeBuilderButton(this.target, this.stageScroll);
    this.renderedElements.clear();
    this.renderedElements.add(this.shellScroll);
    this.renderedElements.add(this.stageScroll);
    this.renderedElements.add(this.focusable);
  }

  contains(element: unknown): boolean {
    return this.renderedElements.has(element);
  }

  addEventListener(): void {
    // Test double only needs listener attachment to be accepted.
  }

  querySelector<T extends Element>(selector: string): T | null {
    if (selector === this.target.selector || selector.endsWith(` ${this.target.selector}`)) {
      return this.focusable as T;
    }

    return null;
  }

  querySelectorAll<T extends Element>(selector: string): T[] {
    if (selector === ".cog-builder-shell") {
      return [this.shellScroll as unknown as T];
    }
    if (selector === ".builder-wizard-stage") {
      return [this.stageScroll as unknown as T];
    }

    return [];
  }
}

type FakeSettingsFocusable = FakeSettingsInput | FakeSettingsButton;
type FakeBuilderFocusable = FakeBuilderTextArea | FakeBuilderButton;

class FakeScrollContainer extends FakeHTMLElementShim {
  scrollLeft = 0;
  scrollTop = 0;

  addEventListener(): void {
    // Test double only needs listener attachment to be accepted.
  }
}

abstract class FakeFocusableElement extends FakeHTMLElementShim {
  dataset: DOMStringMap;
  scrollLeft = 0;
  scrollTop = 0;

  constructor(
    target: SettingsRestoreTarget,
    private readonly scrollContainer: FakeScrollContainer,
  ) {
    super();
    this.dataset = datasetForTarget(target) as DOMStringMap;
  }

  addEventListener(): void {
    // Test double only needs listener attachment to be accepted.
  }

  closest(): null {
    return null;
  }

  focus(): void {
    this.scrollContainer.scrollTop = 0;
    this.scrollContainer.scrollLeft = 0;
    (globalThis.document as unknown as { activeElement: unknown }).activeElement = this;
  }

  getAttribute(): null {
    return null;
  }

  hasAttribute(name: string): boolean {
    return name === "data-settings-preset-name" && "settingsPresetName" in this.dataset;
  }
}

class FakeSettingsInput extends FakeHTMLInputElementShim {
  dataset: DOMStringMap;
  selectionEnd: number | null = null;
  selectionStart: number | null = null;
  scrollLeft = 0;
  scrollTop = 0;
  value = "";

  constructor(
    target: SettingsRestoreTarget,
    private readonly scrollContainer: FakeScrollContainer,
  ) {
    super();
    this.dataset = datasetForTarget(target) as DOMStringMap;
  }

  addEventListener(): void {
    // Test double only needs listener attachment to be accepted.
  }

  closest(): null {
    return null;
  }

  focus(): void {
    this.scrollContainer.scrollTop = 0;
    this.scrollContainer.scrollLeft = 0;
    (globalThis.document as unknown as { activeElement: unknown }).activeElement = this;
  }

  getAttribute(): null {
    return null;
  }

  hasAttribute(name: string): boolean {
    return name === "data-settings-preset-name" && "settingsPresetName" in this.dataset;
  }

  setSelectionRange(selectionStart: number | null, selectionEnd: number | null): void {
    this.selectionStart = selectionStart;
    this.selectionEnd = selectionEnd;
  }
}

class FakeSettingsButton extends FakeFocusableElement {}

class FakeBuilderTextArea extends FakeHTMLTextAreaElementShim {
  dataset: DOMStringMap;
  selectionEnd: number | null = null;
  selectionStart: number | null = null;
  scrollLeft = 0;
  scrollTop = 0;
  value = "";

  constructor(
    target: BuilderRestoreTarget,
    private readonly scrollContainer: FakeScrollContainer,
  ) {
    super();
    this.dataset = builderDatasetForTarget(target) as DOMStringMap;
  }

  addEventListener(): void {
    // Test double only needs listener attachment to be accepted.
  }

  closest(selector: string): FakeHTMLElementShim | null {
    return selector === ".cog-builder-page" ? this.scrollContainer : null;
  }

  focus(): void {
    this.scrollContainer.scrollTop = 0;
    this.scrollContainer.scrollLeft = 0;
    (globalThis.document as unknown as { activeElement: unknown }).activeElement = this;
  }

  getAttribute(name: string): string | null {
    return name === "aria-label" ? "Cog description" : null;
  }

  hasAttribute(): boolean {
    return false;
  }

  setSelectionRange(selectionStart: number | null, selectionEnd: number | null): void {
    this.selectionStart = selectionStart;
    this.selectionEnd = selectionEnd;
  }
}

class FakeBuilderButton extends FakeHTMLElementShim {
  dataset: DOMStringMap;
  scrollLeft = 0;
  scrollTop = 0;

  constructor(
    target: BuilderRestoreTarget,
    private readonly scrollContainer: FakeScrollContainer,
  ) {
    super();
    this.dataset = builderDatasetForTarget(target) as DOMStringMap;
  }

  addEventListener(): void {
    // Test double only needs listener attachment to be accepted.
  }

  closest(selector: string): FakeHTMLElementShim | null {
    if (selector === ".cog-builder-page") {
      return this.scrollContainer;
    }
    return null;
  }

  focus(): void {
    this.scrollContainer.scrollTop = 0;
    this.scrollContainer.scrollLeft = 0;
    (globalThis.document as unknown as { activeElement: unknown }).activeElement = this;
  }

  getAttribute(): null {
    return null;
  }

  hasAttribute(): boolean {
    return false;
  }
}

function datasetForTarget(target: SettingsRestoreTarget): Record<string, string> {
  switch (target.tab) {
    case "params":
      return { configKey: "debateDoubt" };
    case "timing":
      return { configSecondsKey: "debatePrepTicks" };
    case "traits":
      return { traitConfigId: "contrarian", traitConfigKey: "overwhelmingTeamThreshold" };
    case "achievements":
    case "debates":
    case "venue":
      return { configTab: target.tab };
  }
}

function builderDatasetForTarget(target: BuilderRestoreTarget): Record<string, string> {
  switch (target.type) {
    case "textarea":
      return { builderField: "appearance" };
    case "button":
      return { action: "roll-builder-step" };
  }
}

const stubActions: HudActions = {
  onCloseBuilder: () => undefined,
  onCloseConfig: () => undefined,
  onCreateCog: () => Promise.resolve(undefined),
  onCreateSettingsPreset: () => undefined,
  onAbandonCog: () => Promise.resolve(false),
  onKickCog: () => Promise.resolve(false),
  onGenerateCogSprites: () => Promise.resolve(undefined),
  onOpenBuilderWindow: () => undefined,
  onOpenConfigWindow: () => undefined,
  onOpenProfileWindow: () => undefined,
  onOpenVenueEditorWindow: () => undefined,
  onPlay: () => undefined,
  onSaveCogProfile: () => undefined,
  onSaveGameConfig: () => undefined,
  onSelectCog: () => undefined,
  onSelectCogChoice: () => undefined,
  onSelectNextCog: () => undefined,
  onSelectSettingsPreset: () => undefined,
  onShuffleTeams: () => undefined,
  onToggleDisco: () => undefined,
  onSpawnCog: () => undefined,
  onStep: () => undefined,
  onStop: () => undefined,
};
