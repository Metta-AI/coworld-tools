import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";

import { DIARY_INITIAL_ROOM_LIMIT, Hud, renderCogProfilePage, scrollRosterCogTowardTop, type HudActions } from "../../src/client/ui/hud";
import { secondsToSimulationTicks } from "../../src/shared/timing";
import type { Cog, CogConversationMessage, ServerStatus, WorldSnapshot } from "../../src/shared/types";

const styles = readFileSync(new URL("../../src/client/ui/styles.css", import.meta.url), "utf8");

const originalDocument = globalThis.document;
const originalHTMLElement = globalThis.HTMLElement;
const originalHTMLInputElement = globalThis.HTMLInputElement;
const originalHTMLTextAreaElement = globalThis.HTMLTextAreaElement;
const originalHTMLSelectElement = globalThis.HTMLSelectElement;
const originalWindow = globalThis.window;

class FakeElement {
  private html = "";

  get innerHTML(): string {
    return this.html;
  }

  set innerHTML(value: string) {
    this.html = value;
    this.onInnerHTML(value);
  }

  protected onInnerHTML(_value: string): void {
    // Test doubles can observe rendered markup by overriding this.
  }

  contains(): boolean {
    return false;
  }

  addEventListener(): void {
    // Test double only needs render output, not browser event dispatch.
  }

  querySelector(): null {
    return null;
  }

  querySelectorAll(): [] {
    return [];
  }
}

class FakeFocusableRoot extends FakeElement {
  private readonly knownElements = new Set<unknown>();
  discoButton: HTMLElement | undefined;

  override contains(element: unknown): boolean {
    return this.knownElements.has(element);
  }

  override querySelector(selector: string): HTMLElement | null {
    return selector.includes("data-action") && selector.includes("toggle-disco") ? this.discoButton ?? null : null;
  }

  protected override onInnerHTML(value: string): void {
    if (!value.includes('data-action="toggle-disco"')) {
      this.discoButton = undefined;
      return;
    }

    this.discoButton = createFocusableElement({ action: "toggle-disco" });
    this.knownElements.add(this.discoButton);
  }
}

class FakeScrollRoot extends FakeElement {
  constructor(readonly roster: FakeRosterElement) {
    super();
  }

  override querySelector(selector: string): FakeRosterElement | null {
    return selector === ".cog-roster" ? this.roster : null;
  }

  override querySelectorAll(selector: string): FakeRosterElement[] {
    return selector === ".cog-roster" ? [this.roster] : [];
  }
}

class FakeTickerRoot extends FakeElement {
  readonly group: { offsetWidth: number };
  readonly track = { style: { transform: "" } };

  constructor(groupWidth: number) {
    super();
    this.group = { offsetWidth: groupWidth };
  }

  override querySelector(selector: string): unknown {
    if (selector === ".game-ticker-group") {
      return this.group;
    }
    return null;
  }

  override querySelectorAll(selector: string): unknown[] {
    return selector === ".game-ticker-track" ? [this.track] : [];
  }
}

class FakeControllerLogRestoreRoot extends FakeElement {
  private readonly knownElements = new Set<unknown>();
  private controllerLogRendered = false;
  readonly profileScroll = new FakeScrollContainer();
  readonly logThread = new FakeScrollContainer();
  readonly profilePage = createControllerLogProfilePage("ada");
  readonly controllerLogDetails = createControllerLogDetails(this.profilePage);
  readonly filterButton = createControllerLogFilterButton("movement", () => this.profileScroll, this.profilePage);

  constructor() {
    super();
    this.knownElements.add(this.profileScroll);
    this.knownElements.add(this.logThread);
    this.knownElements.add(this.profilePage);
    this.knownElements.add(this.controllerLogDetails);
    this.knownElements.add(this.filterButton);
  }

  override contains(element: unknown): boolean {
    return this.knownElements.has(element);
  }

  override querySelector(selector: string): HTMLElement | null {
    if (!this.controllerLogRendered) {
      return selector === ".cog-profile-scroll" ? this.profileScroll as unknown as HTMLElement : null;
    }
    if (selector === ".cog-profile-scroll") {
      return this.profileScroll as unknown as HTMLElement;
    }
    if (selector.includes("data-action") && selector.includes("toggle-controller-log-filter") && selector.includes("movement")) {
      return this.filterButton;
    }
    if (selector === ".profile-controller-log" || selector.endsWith(".profile-controller-log")) {
      return this.controllerLogDetails;
    }
    return null;
  }

  override querySelectorAll(selector: string): HTMLElement[] {
    if (selector === ".cog-profile-scroll") {
      return [this.profileScroll as unknown as HTMLElement];
    }
    if (!this.controllerLogRendered) {
      return [];
    }
    if (selector === ".profile-log-thread") {
      return [this.logThread as unknown as HTMLElement];
    }
    if (selector === "details") {
      return [this.controllerLogDetails];
    }
    if (selector === "[data-action='toggle-controller-log-filter']") {
      return [this.filterButton];
    }
    return [];
  }

  protected override onInnerHTML(): void {
    this.controllerLogRendered = this.innerHTML.includes('data-action="toggle-controller-log-filter"');
    this.profileScroll.scrollLeft = 0;
    this.profileScroll.scrollTop = 0;
    this.logThread.scrollLeft = 0;
    this.logThread.scrollTop = 0;
    this.controllerLogDetails.open = true;
    (globalThis.document as unknown as { activeElement: unknown }).activeElement = undefined;
  }
}

class FakeScrollContainer {
  scrollLeft = 0;
  scrollTop = 0;

  addEventListener(): void {
    // Test double only needs listener attachment to be accepted.
  }
}

class FakeRosterElement {
  scrollLeft = 0;
  scrollTop = 0;
  scrollHeight = 900;
  clientHeight = 240;
  offsetTop = 12;

  private readonly rows = new Map<string, FakeRosterRow>();

  setRow(cogId: string, offsetTop: number): void {
    this.rows.set(cogId, { offsetTop });
  }

  querySelector(selector: string): FakeRosterRow | null {
    const cogId = /\[data-cog-id="([^"]+)"\]/.exec(selector)?.[1];
    return cogId ? this.rows.get(cogId) ?? null : null;
  }
}

type FakeRosterRow = {
  offsetTop: number;
};

const baseCog: Omit<Cog, "color" | "id" | "name" | "position"> = {
  activeTrait: "rationalist",
  attributes: {},
  behaviorPrompt: "",
  controllerId: "stub",
  conversationLog: [],
  defensiveTrait: "stubborn",
  certainty: 100,
  achievements: [],
  completedAchievements: [],
  failedAchievements: [],
  goalScores: [],
  movementCooldown: 0,
  personalGoal: "majority",
  personalScore: 0,
  spriteSheetKey: "missing-test-sprite",
  stats: { argumentsLost: 0, argumentsWon: 0, teamFlips: 0 },
  ticksAlive: 0,
};

describe("HUD teams gauge", () => {
  afterEach(() => {
    globalThis.document = originalDocument;
    globalThis.HTMLElement = originalHTMLElement;
    globalThis.HTMLInputElement = originalHTMLInputElement;
    globalThis.HTMLTextAreaElement = originalHTMLTextAreaElement;
    globalThis.HTMLSelectElement = originalHTMLSelectElement;
    globalThis.window = originalWindow;
    vi.useRealTimers();
  });

  it("renders per-team counts without a visible total", () => {
    const element = renderHudWithSnapshot(
      snapshot([
        ...Array.from({ length: 6 }, (_, index) => cog({ color: "red", id: `red-${index}`, name: `Red ${index}` })),
        ...Array.from({ length: 4 }, (_, index) => cog({ color: "blue", id: `blue-${index}`, name: `Blue ${index}` })),
      ]),
    );

    const colorBar = htmlBlock(element.innerHTML, "teams-color-bar");

    expect(element.innerHTML).not.toContain(">Teams<");
    expect(element.innerHTML).not.toContain(">red<");
    expect(element.innerHTML).not.toContain(">blue<");
    expect(element.innerHTML).not.toContain('class="teams-legend"');
    expect(element.innerHTML).not.toContain("10 cogs");
    expect(colorBar).toContain('class="team-segment-count">6</span>');
    expect(colorBar).toContain('class="team-segment-count">4</span>');
    expect(element.innerHTML).toContain('aria-label="red 6, blue 4"');
  });

  it("keeps queued ticker events after they roll out of recent snapshots", () => {
    installFakeDom();
    const element = new FakeElement();
    const hud = new Hud(element as unknown as HTMLElement, stubActions);

    hud.update({
      connectionStatus: "connected",
      snapshot: {
        ...snapshot([
          cog({ color: "red", id: "shear", name: "E.Shear" }),
          cog({ color: "blue", id: "blue", name: "Blue Holdout" }),
        ]),
        recentEvents: [
          {
            actorId: "shear",
            id: "shear-flip",
            message: "E.Shear converted from blue to red",
            tick: 22,
            type: "colorChange",
          },
        ],
        tick: 25,
      },
    });

    expect(element.innerHTML).toContain("game-ticker-panel");
    expect(element.innerHTML).toContain("E.Shear");

    hud.update({
      snapshot: {
        ...snapshot([
          cog({ color: "red", id: "shear", name: "E.Shear" }),
          cog({ color: "blue", id: "blue", name: "Blue Holdout" }),
        ]),
        recentEvents: [],
        tick: 120,
      },
    });

    expect(element.innerHTML).toContain("game-ticker-panel");
    expect(element.innerHTML).toContain("E.Shear");
  });

  it("removes ticker events after they scroll past the panel", () => {
    installFakeDom();
    globalThis.window = {
      location: { href: "http://127.0.0.1:9509/" },
      matchMedia: () => ({ matches: false }),
      requestAnimationFrame: vi.fn(() => 1),
    } as unknown as Window & typeof globalThis;
    const element = new FakeTickerRoot(10);
    const hud = new Hud(element as unknown as HTMLElement, stubActions);
    const worldSnapshot = {
      ...snapshot([
        cog({ color: "red", id: "ada", name: "Ada" }),
        cog({ color: "blue", id: "blue", name: "Blue Holdout" }),
      ]),
      recentEvents: [
        {
          actorId: "ada",
          id: "ada-spawn",
          message: "Ada arrived!",
          tick: 22,
          type: "spawn" as const,
        },
      ],
      tick: 25,
    };

    hud.update({
      connectionStatus: "connected",
      snapshot: worldSnapshot,
    });
    expect(element.innerHTML).toContain("game-ticker-panel");
    expect(element.innerHTML).toContain("Ada");

    (hud as unknown as { advanceGameTicker: (timestamp: number) => void }).advanceGameTicker(0);
    (hud as unknown as { advanceGameTicker: (timestamp: number) => void }).advanceGameTicker(4000);

    expect(element.innerHTML).not.toContain("game-ticker-panel");
    expect(element.innerHTML).not.toContain("Ada arrived!");

    hud.update({ snapshot: worldSnapshot });
    expect(element.innerHTML).not.toContain("Ada arrived!");
  });

  it("multiplies roster scores by the display scale", () => {
    const element = renderHudWithSnapshot(
      snapshot([
        cog({
          color: "red",
          id: "red",
          name: "Red",
          personalScore: 7,
        }),
      ]),
    );

    expect(element.innerHTML).toMatch(/class="cog-score" aria-label="Red score 7000 points"[\s\S]*?<strong>7000<\/strong>/);
    expect(element.innerHTML).not.toMatch(/class="cog-score" aria-label="Red score 7 points"[\s\S]*?<strong>7<\/strong>/);
  });

  it("shows achievement counts and the last completed achievement on roster rows", () => {
    const element = renderHudWithSnapshot(
      snapshot([
        cog({
          color: "red",
          id: "red",
          name: "Red",
          completedAchievements: [
            {
              achievementId: "beatTrait",
              assignedTick: 1,
              assignmentId: "completed-older",
              completedTick: 2,
              parameters: { trait: "swift" },
              points: 10,
              timeoutTick: 12,
            },
            {
              achievementId: "winInRoom",
              assignedTick: 1,
              assignmentId: "completed-1",
              completedTick: 3,
              parameters: { roomKind: "bar" },
              points: 10,
              timeoutTick: 12,
            },
          ],
          failedAchievements: [
            {
              achievementId: "witnessTeamWins",
              assignedTick: 1,
              assignmentId: "failed-1",
              failedTick: 8,
              parameters: { team: "blue", rounds: 3 },
              timeoutTick: 8,
            },
          ],
        }),
      ]),
    );

    expect(element.innerHTML).toContain("cog-row-achievements");
    expect(element.innerHTML).toContain("<span>C 2</span>");
    expect(element.innerHTML).toContain("<span>E 1</span>");
    expect(element.innerHTML).toContain(">Completed:<");
    expect(element.innerHTML).toContain("Win Round in Bar");
    expect(element.innerHTML).not.toContain("Beat Cog with Swift");
    expect(element.innerHTML).not.toContain(">Failed:<");
    expect(element.innerHTML).not.toContain("Witness Blue Win 3 Rounds");
  });

  it("shows the last completed achievement on roster rows for only thirty seconds", () => {
    const completedTick = 20;
    const recentElement = renderHudWithSnapshot({
      ...snapshot([
        cog({
          color: "red",
          id: "red",
          name: "Red",
          completedAchievements: [
            {
              achievementId: "winInRoom",
              assignedTick: 1,
              assignmentId: "completed-1",
              completedTick,
              parameters: { roomKind: "bar" },
              points: 10,
              timeoutTick: 40,
            },
          ],
        }),
      ]),
      tick: completedTick + secondsToSimulationTicks(30) - 1,
    });
    const expiredElement = renderHudWithSnapshot({
      ...snapshot([
        cog({
          color: "red",
          id: "red",
          name: "Red",
          completedAchievements: [
            {
              achievementId: "winInRoom",
              assignedTick: 1,
              assignmentId: "completed-1",
              completedTick,
              parameters: { roomKind: "bar" },
              points: 10,
              timeoutTick: 40,
            },
          ],
        }),
      ]),
      tick: completedTick + secondsToSimulationTicks(30),
    });

    expect(recentElement.innerHTML).toContain(">Completed:<");
    expect(recentElement.innerHTML).toContain("Win Round in Bar");
    expect(expiredElement.innerHTML).not.toContain(">Completed:<");
    expect(expiredElement.innerHTML).not.toContain("Win Round in Bar");
  });

  it("does not offer roster room choices into a leaving cog's reserved source spot", () => {
    installFakeDom();
    const element = new FakeElement();
    const hud = new Hud(element as unknown as HTMLElement, stubActions);
    (hud as unknown as { expandedRosterCogId: string }).expandedRosterCogId = "blue";

    hud.update({
      connectionStatus: "connected",
      snapshot: {
        ...snapshot([
          cog({
            color: "red",
            id: "moving",
            name: "Moving",
            moving: {
              from: { roomId: "room-a", spotId: "a1" },
              to: { roomId: "room-b", spotId: "b2" },
              fromPosition: { x: 1, y: 1 },
              toPosition: { x: 9, y: 1 },
              startedTick: 1,
              arriveTick: 3,
            },
            position: { x: 1, y: 1 },
          }),
          cog({
            color: "blue",
            id: "blue",
            name: "Blue",
            location: { roomId: "room-b", spotId: "b1" },
            position: { x: 8, y: 1 },
          }),
        ]),
        venue: {
          rooms: [
            { id: "room-a", label: "Room A", kind: "lounge", spotIds: ["a1"], neighborIds: ["room-b"] },
            { id: "room-b", label: "Room B", kind: "lounge", spotIds: ["b1", "b2"], neighborIds: ["room-a"] },
          ],
          spots: [
            { id: "a1", roomId: "room-a", label: "A1", position: { x: 1, y: 1 } },
            { id: "b1", roomId: "room-b", label: "B1", position: { x: 8, y: 1 } },
            { id: "b2", roomId: "room-b", label: "B2", position: { x: 9, y: 1 } },
          ],
          spotLinks: [],
        },
      },
    });

    expect(element.innerHTML).not.toContain('data-room-id="room-a"');
    expect(element.innerHTML).not.toContain('data-action="select-cog-choice"');
    expect(element.innerHTML).toContain('class="cog-choice-qr-card"');
  });

  it("renders the text builder launch control as a named-window link", () => {
    const element = renderHudWithSnapshot(snapshot([cog({ color: "red", id: "red", name: "Red" })]));

    expect(element.innerHTML).toContain('href="/builder"');
    expect(element.innerHTML).toContain('target="cogshambo-cog-builder"');
    expect(element.innerHTML).toContain('data-action="open-builder-link"');
    expect(element.innerHTML).toContain('aria-label="Build cog in new window"');
    expect(element.innerHTML).not.toContain('data-action="open-builder">Build cog</button>');
  });

  it("renders a shuffle control in the main controls panel", () => {
    const element = renderHudWithSnapshot(snapshot([cog({ color: "red", id: "red", name: "Red" })]));

    const controlsPanel = htmlBlock(element.innerHTML, "top-actions");

    expect(controlsPanel).toContain('data-action="shuffle-teams"');
    expect(controlsPanel).toContain(">Shuffle<");
  });

  it("renders the LLM move timeout percentage in the controls panel", () => {
    const element = renderHudWithSnapshot(snapshot([cog({ color: "red", id: "red", name: "Red" })]), serverStatus({
      llmMoveDecisions: 10,
      llmTimedOutMovePercent: 20,
      llmTimedOutMoves: 2,
    }));

    const controlsPanel = htmlBlock(element.innerHTML, "top-panel");

    expect(controlsPanel).toContain('class="llm-timeout-meter"');
    expect(controlsPanel).toContain("LLM move timeouts");
    expect(controlsPanel).toContain("20%");
    expect(controlsPanel).toContain("2 / 10");
  });

  it("only renders game flow when the controls drawer is open", () => {
    installFakeDom();
    const element = new FakeElement();
    const hud = new Hud(element as unknown as HTMLElement, stubActions);
    hud.update({
      connectionStatus: "connected",
      snapshot: {
        ...snapshot([cog({ color: "red", id: "red", name: "Red" })]),
        recentEvents: [
          {
            id: "flow-1",
            tick: 2,
            type: "gameFlow",
            actorId: "red",
            message: "asking Red to move",
          },
        ],
      },
    });

    expect(element.innerHTML).not.toContain('data-action="toggle-top-controls"');
    expect(element.innerHTML).not.toContain("game-flow-panel");

    (hud as unknown as { toggleControlsPanel: () => void }).toggleControlsPanel();

    expect(element.innerHTML).toContain('class="top-drawer is-open"');
    expect(element.innerHTML).toContain("game-flow-panel");
    expect(element.innerHTML).toContain("asking Red to move");
  });

  it("toggles the roster panel", () => {
    installFakeDom();
    const element = new FakeElement();
    const hud = new Hud(element as unknown as HTMLElement, stubActions);
    hud.update({
      connectionStatus: "connected",
      snapshot: snapshot([cog({ color: "red", id: "red", name: "Red" })]),
    });

    expect(element.innerHTML).toContain('class="right-panel"');
    expect(element.innerHTML).toContain('class="cogs-panel"');

    (hud as unknown as { toggleRosterPanel: () => void }).toggleRosterPanel();

    expect(element.innerHTML).not.toContain('class="right-panel"');
    expect(element.innerHTML).not.toContain('class="cogs-panel"');

    (hud as unknown as { toggleRosterPanel: () => void }).toggleRosterPanel();

    expect(element.innerHTML).toContain('class="right-panel"');
    expect(element.innerHTML).toContain('class="cogs-panel"');
  });

  it("toggles the shortcuts panel", () => {
    installFakeDom();
    const element = new FakeElement();
    const hud = new Hud(element as unknown as HTMLElement, stubActions);
    hud.update({
      connectionStatus: "connected",
      snapshot: snapshot([cog({ color: "red", id: "red", name: "Red" })]),
    });

    expect(element.innerHTML).not.toContain('class="shortcuts-panel"');

    (hud as unknown as { toggleShortcutsPanel: () => void }).toggleShortcutsPanel();

    expect(element.innerHTML).toContain('class="shortcuts-panel"');
    expect(element.innerHTML).toContain("Cmd-G");
    expect(element.innerHTML).toContain("Cmd-S");

    (hud as unknown as { toggleShortcutsPanel: () => void }).toggleShortcutsPanel();

    expect(element.innerHTML).not.toContain('class="shortcuts-panel"');
  });

  it("renders disco mode as a main controls toggle with a rainbow team bar", () => {
    const element = renderHudWithSnapshot(snapshot([cog({ color: "red", id: "red", name: "Red" })]), {
      ...serverStatus(),
      discoMode: true,
    });

    const controlsPanel = htmlBlock(element.innerHTML, "top-actions");

    expect(controlsPanel).toContain('data-action="toggle-disco"');
    expect(controlsPanel).toContain('aria-pressed="true"');
    expect(controlsPanel).toContain(">Disco<");
    expect(element.innerHTML).toContain('class="teams-color-bar is-disco"');
    expect(element.innerHTML).toContain('aria-label="Disco mode: rainbow team bar, debates paused"');
  });

  it("renders roster cog circles and certainty meters as disco rainbows", () => {
    const element = renderHudWithSnapshot(snapshot([
      cog({ color: "red", id: "red", name: "Red", certainty: 75 }),
      cog({ color: "blue", id: "blue", name: "Blue", certainty: 40 }),
    ]), {
      ...serverStatus(),
      discoMode: true,
    });

    expect(element.innerHTML.match(/class="cog-row-avatar is-disco"/g)).toHaveLength(2);
    expect(element.innerHTML.match(/class="flip-gauge-fill is-disco"/g)).toHaveLength(2);
  });

  it("keeps focus on the disco toggle while live updates refresh the HUD", () => {
    installFakeDom();
    const element = new FakeFocusableRoot();
    const hud = new Hud(element as unknown as HTMLElement, stubActions);
    hud.update({
      connectionStatus: "connected",
      serverStatus: serverStatus({ discoMode: false, tick: 1 }),
      snapshot: snapshot([cog({ color: "red", id: "red", name: "Red" })]),
    });
    const firstButton = element.discoButton;
    expect(firstButton).toBeDefined();
    firstButton?.focus();

    hud.update({ serverStatus: serverStatus({ discoMode: true, tick: 2 }) });

    expect(globalThis.document.activeElement).toBe(element.discoButton);
    expect(element.innerHTML).toContain('data-action="toggle-disco"');
    expect(element.innerHTML).toContain('aria-pressed="true"');
  });

  it("uses the QR card instead of the floating plus builder button", () => {
    const element = renderHudWithSnapshot(snapshot([cog({ color: "red", id: "red", name: "Red" })]));

    expect(element.innerHTML).toContain('class="builder-qr-card"');
    expect(element.innerHTML).toContain('data-action="open-builder-window"');
    expect(element.innerHTML).not.toContain('class="control-panel"');
    expect(element.innerHTML).not.toContain('class="control-button control-add-button"');
  });

  it("toggles the QR card", () => {
    installFakeDom();
    const element = new FakeElement();
    const hud = new Hud(element as unknown as HTMLElement, stubActions);
    hud.update({
      connectionStatus: "connected",
      snapshot: snapshot([cog({ color: "red", id: "red", name: "Red" })]),
    });

    expect(element.innerHTML).toContain('class="builder-qr-card"');

    (hud as unknown as { toggleBuilderQrCard: () => void }).toggleBuilderQrCard();

    expect(element.innerHTML).not.toContain('class="builder-qr-card"');

    (hud as unknown as { toggleBuilderQrCard: () => void }).toggleBuilderQrCard();

    expect(element.innerHTML).toContain('class="builder-qr-card"');
  });

  it("renders a profile QR claim link on expanded roster cogs without action choices", () => {
    installFakeDom();
    const element = new FakeElement();
    const hud = new Hud(element as unknown as HTMLElement, stubActions);
    (hud as unknown as { expandedRosterCogId: string }).expandedRosterCogId = "red";

    hud.update({
      connectionStatus: "connected",
      snapshot: snapshot([
        cog({
          color: "red",
          id: "red",
          name: "Red",
          intent: "player steer: older preset cue",
        }),
      ]),
    });

    expect(element.innerHTML).toContain('data-action="open-profile-window"');
    expect(element.innerHTML).toContain('data-action="kick-cog"');
    expect(element.innerHTML).toContain('data-cog-id="red"');
    expect(element.innerHTML).toContain('aria-label="Kick Red home"');
    expect(element.innerHTML).toContain(">Kick</button>");
    expect(element.innerHTML).toContain('class="cog-choice-qr-card"');
    expect(element.innerHTML).toContain('class="cog-choice-qr-code"');
    expect(element.innerHTML).toContain('href="https://redvblue.dbloom.in/profile/red?setCogCookie=1"');
    expect(element.innerHTML).toContain('target="cogshambo-profile"');
    expect(element.innerHTML).toContain('aria-label="Open Red profile and remember this cog"');
    expect(element.innerHTML).not.toContain('aria-label="State"');
    expect(element.innerHTML).not.toContain("<h3>State</h3>");
    expect(element.innerHTML).not.toContain('class="cog-choice-facts"');
    expect(element.innerHTML).not.toContain("Valid Actions");
    expect(element.innerHTML).not.toContain('data-action="select-cog-valid-action"');
    expect(element.innerHTML).not.toContain('data-action="select-cog-choice"');
  });

  it("keeps player score counters in the mobile profile status header", () => {
    installFakeDom();
    const element = new FakeElement();
    const hud = new Hud(element as unknown as HTMLElement, stubActions);

    hud.update({
      connectionStatus: "connected",
      snapshot: snapshot([
        cog({
          color: "red",
          id: "red",
          name: "Red",
          certainty: 35,
          personalScore: 42,
          stats: { argumentsWon: 2, argumentsLost: 5, teamFlips: 1 },
        }),
      ]),
    });
    hud.openCogProfilePage("red");

    expect(element.innerHTML).toContain('class="profile-mobile-score-strip"');
    expect(element.innerHTML).toContain('aria-label="Red status counters"');
    expect(element.innerHTML).toMatch(/<span>Score<\/span>\s*<strong>42000<\/strong>\s*<span>pts<\/span>/);
    expect(element.innerHTML).toMatch(/<span>Debates<\/span>\s*<strong>2-5<\/strong>\s*<span>29% win<\/span>/);
    expect(element.innerHTML).not.toContain("<span>Won</span>");
    expect(element.innerHTML).not.toContain("<span>Lost</span>");
    expect(element.innerHTML).toMatch(/<span>Flips<\/span>\s*<strong>1<\/strong>\s*<span>team<\/span>/);
    expect(element.innerHTML).toMatch(/<span>Achievements<\/span>\s*<strong>0\/0<\/strong>\s*<span>done\/active<\/span>/);
    expect(element.innerHTML).toContain('aria-label="Red certainty"');
    expect(element.innerHTML).toContain(">Certainty<");
    expect(element.innerHTML).toContain(">35/100<");
    expect(element.innerHTML).toContain('class="profile-mobile-certainty-gauge"');
    expect(element.innerHTML).toContain('aria-label="Red certainty 35 of 100"');
    expect(element.innerHTML).toContain('data-color="red"');
    expect(element.innerHTML).toContain('style="width: 35%"');
    expect(element.innerHTML).toContain(">red team<");
  });

  it("uses time-based copy for plural mobile team flips", () => {
    installFakeDom();
    const element = new FakeElement();
    const hud = new Hud(element as unknown as HTMLElement, stubActions);

    hud.update({
      connectionStatus: "connected",
      snapshot: snapshot([
        cog({
          color: "red",
          id: "red",
          name: "Red",
          stats: { argumentsWon: 0, argumentsLost: 0, teamFlips: 2 },
        }),
      ]),
    });
    hud.openCogProfilePage("red");

    expect(element.innerHTML).toMatch(/<span>Flips<\/span>\s*<strong>2<\/strong>\s*<span>teams<\/span>/);
    expect(element.innerHTML).not.toContain("<span>times</span>");
  });

  it("keeps mobile current status visible while movement is cooling down", () => {
    installFakeDom();
    const element = new FakeElement();
    const hud = new Hud(element as unknown as HTMLElement, stubActions);

    hud.update({
      connectionStatus: "connected",
      snapshot: {
        ...snapshot([
          cog({
            color: "red",
          id: "red",
          name: "Red",
          activeTrait: "avenger",
          lastVenueMoveTick: 10,
          location: { roomId: "room-a", spotId: "a1" },
        }),
          cog({
            color: "red",
            id: "teammate",
            name: "Teammate",
            location: { roomId: "room-a", spotId: "a2" },
          }),
        ]),
        tick: 20,
        venue: {
          rooms: [
            { id: "room-a", label: "Room A", kind: "lounge", spotIds: ["a1", "a2"], neighborIds: ["room-b"] },
            { id: "room-b", label: "Room B", kind: "stage", spotIds: ["b1"], neighborIds: ["room-a"] },
          ],
          spots: [
            { id: "a1", roomId: "room-a", label: "A1", position: { x: 1, y: 1 } },
            { id: "a2", roomId: "room-a", label: "A2", position: { x: 2, y: 1 } },
            { id: "b1", roomId: "room-b", label: "B1", position: { x: 3, y: 1 } },
          ],
          spotLinks: [],
        },
      },
    });
    hud.openCogProfilePage("red");

    expect(element.innerHTML).toContain('class="profile-mobile-current-strip"');
    expect(element.innerHTML).not.toContain('class="profile-mobile-current-line"');
    expect(element.innerHTML).toContain('class="profile-mobile-intent-line"');
    expect(element.innerHTML).not.toContain("profile-mobile-now-panel");
    expect(element.innerHTML).toContain("Reading the room for the next opening.");
    expect(element.innerHTML).toContain('data-trait-value="avenger"');
    expect(element.innerHTML).not.toContain("is-impacting");
    expect(element.innerHTML).not.toContain('title="shaping room movement timing"');
    expect(element.innerHTML).not.toContain("profile-mobile-action-panel");
    expect(element.innerHTML).not.toContain("Room choices unlock shortly");
  });

  it("labels mobile activity as a room diary", () => {
    installFakeDom();
    const element = new FakeElement();
    const hud = new Hud(element as unknown as HTMLElement, stubActions);

    hud.update({
      connectionStatus: "connected",
      snapshot: snapshot([cog({ color: "red", id: "red", name: "Red" })]),
    });
    hud.openCogProfilePage("red");

    expect(element.innerHTML).toContain("<span>Diary</span>");
    expect(element.innerHTML).toContain("<strong>Diary</strong>");
    expect(element.innerHTML).not.toContain(">Red&#39;s Actions<");
  });

  it("keeps controller actions visible in the controller log when recent events roll off", () => {
    installFakeDom();
    const element = new FakeElement();
    const hud = new Hud(element as unknown as HTMLElement, stubActions);

    hud.update({
      connectionStatus: "connected",
      snapshot: snapshot([
        cog({
          color: "red",
          conversationLog: [
            {
              content: "Manual keyboard control selected Red.",
              id: "prompt-user",
              role: "user",
              tick: 10,
            },
            {
              content: JSON.stringify({
                type: "wait",
                intent: "player steer: ask Rhea what they actually believe",
              }),
              id: "prompt-action",
              role: "assistant",
              tick: 10,
            },
            {
              content: JSON.stringify({
                type: "move",
                intent: "finding another conversation zone",
                roomId: "gallery",
              }),
              id: "move-action",
              role: "assistant",
              tick: 11,
            },
          ],
          id: "red",
          name: "Red",
        }),
      ]),
    });
    hud.openCogProfilePage("red");

    expect(element.innerHTML).not.toContain(">Red&#39;s Actions<");
    expect(element.innerHTML).toContain("Controller note: player steer: ask Rhea what they actually believe");
    expect(element.innerHTML).toContain("Controller note: finding another conversation zone");
  });

  it("renders mobile intent, prompt composer, and achievements card", () => {
    const element = renderProfileWithSnapshot(
      {
        ...snapshot([
          cog({
            color: "red",
            id: "red",
            name: "Red",
            intent: "player steer: find Blue and keep the argument playful",
            location: { roomId: "gallery", spotId: "speaker-red" },
            achievements: [
              {
                achievementId: "witnessTeamWins",
                assignedTick: 1,
                assignmentId: "achievement-1",
                parameters: { team: "blue", rounds: 3 },
                timeoutTick: 1 + secondsToSimulationTicks(10),
              },
              {
                achievementId: "debateThreeCogs",
                assignedTick: 1,
                assignmentId: "achievement-2",
                timeoutTick: 1 + secondsToSimulationTicks(5),
              },
              {
                achievementId: "flipFlop",
                assignedTick: 1,
                assignmentId: "achievement-3",
                timeoutTick: 1 + secondsToSimulationTicks(8),
              },
            ],
            completedAchievements: [
              {
                achievementId: "winInRoom",
                assignedTick: 1,
                assignmentId: "achievement-done-1",
                completedTick: 4,
                parameters: { roomKind: "lounge" },
                points: 5,
                timeoutTick: 1 + secondsToSimulationTicks(10),
              },
            ],
          }),
          cog({
            color: "blue",
            id: "blue",
            name: "Blue",
            certainty: 44,
            location: { roomId: "gallery", spotId: "speaker-blue" },
          }),
        ]),
        recentEvents: [
          {
            actorId: "red",
            id: "red-flip",
            message: "Red flipped teams",
            tick: 1,
            type: "colorChange",
          },
          {
            actorId: "blue",
            debate: {
              actions: [
                { action: "reason", cogId: "blue" },
                { action: "spin", cogId: "red" },
              ],
              choicesRevealedAtTick: 1,
              expiresAtTick: 1,
              outcome: "win",
              resultRevealedAtTick: 1,
              round: 1,
              winnerCogId: "blue",
              winnerColor: "blue",
              witnessCogIds: ["red"],
            },
            id: "debate-1",
            message: "Blue won",
            targetId: "red",
            tick: 1,
            type: "debateExchange",
          },
          {
            actorId: "blue",
            debate: {
              actions: [
                { action: "reason", cogId: "blue" },
                { action: "spin", cogId: "red" },
              ],
              choicesRevealedAtTick: 1,
              expiresAtTick: 1,
              outcome: "win",
              resultRevealedAtTick: 1,
              round: 1,
              winnerCogId: "blue",
              winnerColor: "blue",
              witnessCogIds: ["red"],
            },
            id: "debate-2",
            message: "Blue won again",
            targetId: "red",
            tick: 1,
            type: "debateExchange",
          },
        ],
        venue: {
          rooms: [{ id: "gallery", label: "Gallery", kind: "lounge", spotIds: ["speaker-red", "speaker-blue"], neighborIds: [] }],
          spots: [
            { id: "speaker-red", roomId: "gallery", label: "Red mic", position: { x: 1, y: 1 }, role: "speaker" },
            { id: "speaker-blue", roomId: "gallery", label: "Blue mic", position: { x: 2, y: 1 }, role: "speaker" },
          ],
          spotLinks: [],
        },
      },
      "red",
    );

    expect(element.innerHTML).not.toContain("profile-mobile-action-panel");
    expect(element.innerHTML).toContain('class="profile-mobile-intent-line"');
    expect(element.innerHTML).not.toContain("No live instruction yet");
    expect(element.innerHTML).toContain("find Blue and keep the argument playful");
    expect(element.innerHTML).toContain(">Guidance<");
    expect(element.innerHTML).toContain('name="behaviorPrompt"');
    expect(element.innerHTML).toContain('class="profile-mobile-prompt-action-row"');
    expect(element.innerHTML).toContain('class="profile-mobile-guidance-panel"');
    expect(element.innerHTML).toContain(">Guidance<");
    expect(element.innerHTML).not.toContain("Current cue:");
    expect(element.innerHTML).not.toContain('data-action="fill-cog-prompt"');
    expect(element.innerHTML).toContain('class="profile-mobile-prompt-submit" type="submit">Send</button>');
    expect(element.innerHTML).not.toContain(">Poke<");
    expect(element.innerHTML).not.toContain("profile-poke-button");
    expect(element.innerHTML).toContain("profile-mobile-guidance-card");
    expect(element.innerHTML).toContain("profile-mobile-achievements-panel");
    expect(element.innerHTML).not.toContain("profile-mobile-panel profile-mobile-achievements-panel");
    expect(element.innerHTML).not.toContain("profile-mobile-achievement-row-goal");
    expect(element.innerHTML).not.toContain(">Majority<");
    expect(element.innerHTML).toContain("Witness Blue Win 3 Rounds");
    expect(element.innerHTML).toContain("profile-mobile-achievement-time");
    expect(element.innerHTML).toContain('aria-label="10 seconds left"');
    expect(element.innerHTML).toContain('style="width: 100%"');
    expect(element.innerHTML).toContain(">10s remaining<");
    expect(element.innerHTML).toContain(">2/3<");
    expect(element.innerHTML).toContain(">1/3<");
    expect(element.innerHTML).toContain("FlipFlop");
    expect(element.innerHTML).toContain(">1/2<");
    expect(element.innerHTML.indexOf("Debate Three Opponents")).toBeLessThan(element.innerHTML.indexOf("Witness Blue Win 3 Rounds"));
    expect(element.innerHTML).not.toContain("profile-mobile-completed-heading");
    expect(element.innerHTML).not.toContain("profile-mobile-completed-list");
    expect(element.innerHTML).toContain("profile-mobile-completed-copy");
    expect(element.innerHTML).toContain("profile-mobile-completed-status");
    expect(element.innerHTML).toContain(">Completed:<");
    expect(element.innerHTML).toContain("profile-mobile-completed-description");
    expect(element.innerHTML).toContain("profile-mobile-completed-score");
    expect(element.innerHTML).toContain(">1/1<");
    expect(element.innerHTML).toContain("Win Round in Lounge");
    expect(element.innerHTML).toContain("Wins a debate round in a Lounge room.");
  });

  it("shows the strategy editor without mobile prompt presets", () => {
    installFakeDom();
    const element = new FakeElement();
    const hud = new Hud(element as unknown as HTMLElement, stubActions);
    hud.update({
      connectionStatus: "connected",
      selectedCogId: "red",
      snapshot: {
        ...snapshot([
          cog({
            color: "red",
            id: "red",
            name: "Red",
            location: { roomId: "gallery", spotId: "speaker-red" },
          }),
          cog({
            color: "blue",
            id: "blue",
            name: "Blue",
            certainty: 44,
            location: { roomId: "gallery", spotId: "speaker-blue" },
          }),
        ]),
        venue: {
          rooms: [{ id: "gallery", label: "Gallery", kind: "lounge", spotIds: ["speaker-red", "speaker-blue"], neighborIds: [] }],
          spots: [
            { id: "speaker-red", roomId: "gallery", label: "Red mic", position: { x: 1, y: 1 }, role: "speaker" },
            { id: "speaker-blue", roomId: "gallery", label: "Blue mic", position: { x: 2, y: 1 }, role: "speaker" },
          ],
          spotLinks: [],
        },
      },
    });
    hud.openCogProfilePage("red");

    expect(element.innerHTML).toContain(">Guidance<");
    expect(element.innerHTML).toContain('name="behaviorPrompt"');
    expect(element.innerHTML).not.toContain('data-action="fill-cog-prompt"');
    expect(element.innerHTML).toContain('class="profile-mobile-prompt-submit" type="submit">Send</button>');
  });

  it("renders intent as the cog's current focus, not just live player instruction", () => {
    const element = renderProfileWithSnapshot(
      snapshot([
        cog({
          color: "red",
          id: "red",
          name: "Red",
          intent: "finding another conversation zone",
        }),
      ]),
      "red",
    );

    expect(element.innerHTML).toContain('class="profile-mobile-intent-line"');
    expect(element.innerHTML).toContain("Finding another conversation zone");
    expect(element.innerHTML).not.toContain("No live instruction yet");
  });

  it("does not show old cue state in the strategy editor through live updates", () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    installFakeDom();
    const element = new FakeElement();
    const hud = new Hud(element as unknown as HTMLElement, stubActions);
    const action = { type: "wait" as const, intent: "player steer: ask Rhea what they actually believe" };
    const internals = hud as unknown as {
      pendingManualChoices: Map<string, { action: typeof action; signature: string; timestamp: number }>;
    };

    hud.update({
      connectionStatus: "connected",
      snapshot: snapshot([cog({ color: "red", id: "red", name: "Red" })]),
    });
    internals.pendingManualChoices.set("red", {
      action,
      signature: "red:intent:player steer: ask Rhea what they actually believe",
      timestamp: 0,
    });
    hud.openCogProfilePage("red");

    expect(element.innerHTML).toContain(">Guidance<");
    expect(element.innerHTML).not.toContain("Current cue: ask Rhea what they actually believe");
    expect(htmlBlock(element.innerHTML, "profile-mobile-intent-line")).not.toContain("ask Rhea what they actually believe");
    expect(htmlBlock(element.innerHTML, "profile-mobile-intent-line")).toContain("Reading the room for the next opening.");

    vi.setSystemTime(3000);
    hud.update({
      connectionStatus: "connected",
      snapshot: snapshot([
        cog({
          color: "red",
          id: "red",
          name: "Red",
          intent: "player steer: older preset cue",
        }),
      ]),
    });

    expect(element.innerHTML).toContain(">Guidance<");
    expect(element.innerHTML).not.toContain("Current cue: ask Rhea what they actually believe");
    expect(htmlBlock(element.innerHTML, "profile-mobile-intent-line")).not.toContain("ask Rhea what they actually believe");
    expect(htmlBlock(element.innerHTML, "profile-mobile-intent-line")).not.toContain("older preset cue");
  });

  it("keeps the strategy editor visible while an argument is preparing", () => {
    const element = renderProfileWithSnapshot(
      {
        ...snapshot([
          cog({
            color: "red",
            id: "red",
            name: "Red",
            debate: { opponentId: "blue", startedTick: 1, nextRoundTick: 10, roundsResolved: 0 },
          }),
          cog({
            color: "blue",
            id: "blue",
            name: "Blue",
            debate: { opponentId: "red", startedTick: 1, nextRoundTick: 10, roundsResolved: 0 },
          }),
        ]),
        tick: 2,
      },
      "red",
    );

    expect(element.innerHTML).not.toContain("profile-mobile-action-panel");
    expect(element.innerHTML).not.toContain(">Load tactic<");
    expect(element.innerHTML).toContain(">Guidance<");
    expect(element.innerHTML).toContain('name="behaviorPrompt"');
    expect(element.innerHTML).not.toContain('data-action="fill-cog-prompt"');
  });

  it("does not generate builder sprites when traits are randomized", () => {
    installFakeDom();
    let spriteRequests = 0;
    const element = new FakeElement();
    const hud = new Hud(element as unknown as HTMLElement, {
      ...stubActions,
      onGenerateCogSprites: () => {
        spriteRequests += 1;
        return Promise.resolve([]);
      },
    });

    hud.openBuilderPage();
    (hud as unknown as { randomizeBuilderTraits: () => void }).randomizeBuilderTraits();

    expect(spriteRequests).toBe(0);
    expect(element.innerHTML).toContain("Ready for the argument pit?");
  });

  it("requests one generated sprite from the builder", () => {
    const hud = new Hud(new FakeElement() as unknown as HTMLElement, stubActions);
    const builder = hud as unknown as {
      builderDraft: {
        activeTrait: string;
        appearanceDescription: string;
        behaviorPrompt: string;
        defensiveTrait: string;
        name: string;
      };
      builderSpriteRequest: () => { count: number } | undefined;
    };

    builder.builderDraft.name = "Helix";
    builder.builderDraft.appearanceDescription = "A brass passionate cog with a teal glass eye.";
    builder.builderDraft.behaviorPrompt = "Seek crowded rooms and argue with Spin.";
    builder.builderDraft.defensiveTrait = "stubborn";
    builder.builderDraft.activeTrait = "passionate";

    expect(builder.builderSpriteRequest()).toMatchObject({ count: 1 });
  });

  it("rolls builder text suggestions without generating sprites", () => {
    vi.useFakeTimers();
    installFakeDom();
    let spriteRequests = 0;
    const element = new FakeElement();
    const hud = new Hud(element as unknown as HTMLElement, {
      ...stubActions,
      onGenerateCogSprites: () => {
        spriteRequests += 1;
        return Promise.resolve([]);
      },
    });
    const builder = hud as unknown as {
      builderDraft: { appearanceDescription: string; behaviorPrompt: string; name: string };
      builderStep: string;
      rollBuilderDescription: () => void;
      rollBuilderStep: () => void;
    };

    hud.openBuilderPage();
    builder.builderStep = "name";
    builder.rollBuilderStep();
    vi.runAllTimers();
    builder.builderStep = "appearance";
    builder.rollBuilderStep();
    vi.runAllTimers();

    expect(builder.builderDraft.name).not.toBe("");
    expect(builder.builderDraft.appearanceDescription).not.toContain(`${builder.builderDraft.name} is`);
    expect(builder.builderDraft.appearanceDescription).toMatch(/^A /);
    expect(builder.builderDraft.appearanceDescription.length).toBeLessThanOrEqual(112);
    expect(builder.builderDraft.appearanceDescription).toMatch(
      /Cog|lens|rim|bolts|bevels|gear|glow|antenna|screws|toy-like/,
    );
    expect(spriteRequests).toBe(0);
  });

  it("does not repeat rolled description openers back-to-back", () => {
    vi.useFakeTimers();
    installFakeDom();
    const hud = new Hud(new FakeElement() as unknown as HTMLElement, stubActions);
    const builder = hud as unknown as {
      builderDraft: { appearanceDescription: string };
      builderStep: string;
      rollBuilderStep: () => void;
    };
    const openers: string[] = [];

    hud.openBuilderPage();
    builder.builderStep = "appearance";
    for (let index = 0; index < 12; index += 1) {
      builder.rollBuilderStep();
      vi.runAllTimers();
      openers.push(builder.builderDraft.appearanceDescription.match(/^A (.*?)(?: with| carrying|;)/)?.[1] ?? "");
    }

    for (let index = 1; index < openers.length; index += 1) {
      expect(openers[index]).not.toBe(openers[index - 1]);
    }
  });

  it("cycles trait rolls before landing on a selected choice", () => {
    vi.useFakeTimers();
    installFakeDom();
    const hud = new Hud(new FakeElement() as unknown as HTMLElement, stubActions);
    const builder = hud as unknown as {
      builderDraft: { defensiveTrait: string | undefined };
      builderStep: string;
      builderTraitRoll: { kind: string; value: string } | undefined;
      rollBuilderStep: () => void;
    };

    hud.openBuilderPage();
    builder.builderStep = "defensiveTrait";
    builder.builderDraft.defensiveTrait = "stubborn";
    builder.rollBuilderStep();

    expect(builder.builderTraitRoll?.kind).toBe("defensiveTrait");
    expect(builder.builderDraft.defensiveTrait).toBeUndefined();
    vi.advanceTimersByTime(1200);
    expect(builder.builderTraitRoll?.kind).toBe("defensiveTrait");
    let finalRollingValue = builder.builderTraitRoll?.value;
    for (let index = 0; index < 80 && builder.builderTraitRoll; index += 1) {
      finalRollingValue = builder.builderTraitRoll.value;
      vi.advanceTimersToNextTimer();
    }

    expect(builder.builderTraitRoll).toBeUndefined();
    expect(builder.builderDraft.defensiveTrait).toBeTruthy();
    expect(builder.builderDraft.defensiveTrait).toBe(finalRollingValue);
  });

  it("scrolls the roster selected from the main view toward the top after preserving prior scroll", () => {
    installFakeDom();
    const roster = new FakeRosterElement();
    const element = new FakeScrollRoot(roster);
    const hud = new Hud(element as unknown as HTMLElement, stubActions);

    hud.update({
      connectionStatus: "connected",
      selectedCogId: "red",
      snapshot: snapshot([
        cog({ color: "red", id: "red", name: "Red" }),
        cog({ color: "blue", id: "blue", name: "Blue" }),
      ]),
    });

    roster.scrollTop = 75;
    roster.setRow("blue", 372);
    hud.update({ selectedCogId: "blue" });

    expect(roster.scrollTop).toBe(168);
  });

  it("clamps selected roster scrolling to the reachable bottom edge", () => {
    const roster = new FakeRosterElement();
    const element = new FakeScrollRoot(roster);
    roster.setRow("blue", 860);

    expect(scrollRosterCogTowardTop(element as unknown as ParentNode, "blue")).toBe(true);

    expect(roster.scrollTop).toBe(656);
  });
});

describe("HUD controller log", () => {
  afterEach(() => {
    globalThis.document = originalDocument;
    globalThis.HTMLElement = originalHTMLElement;
    globalThis.HTMLInputElement = originalHTMLInputElement;
    globalThis.HTMLTextAreaElement = originalHTMLTextAreaElement;
    globalThis.HTMLSelectElement = originalHTMLSelectElement;
  });

  it("renders each current state with its own state card", () => {
    const element = renderProfileWithSnapshot(
      snapshot([
        cog({
          color: "blue",
          conversationLog: [
            controllerPromptMessage(4, [
              "Nearby Team Size: Blue - 2, Red - 1",
              "You're in [Theater] debating Bob (Red, certainty 25)",
              "Nearby guests: Jack (Blue 20)",
            ]),
            controllerPromptMessage(3, [
              "Nearby Team Size: Blue - 2, Red - 1",
              "You're in [Lounge] chilling; available for movement or debate.",
              "Nearby guests: none",
            ]),
            controllerPromptMessage(2, [
              "Nearby Team Size: Blue - 2, Red - 2",
              "You're in [Bar] witnessing Mira and Turing debate.",
              "Nearby guests: Mira (Red 40), Turing (Blue 30)",
            ]),
            controllerPromptMessage(1, [
              "Nearby Team Size: Blue - 1, Red - 1",
              "You're moving to [bar], arriving t14.",
              "Nearby guests: none",
            ]),
          ],
          id: "ada",
          name: "Ada",
        }),
      ]),
      "ada",
    );

    expect(element.innerHTML).toContain('class="log-current-state is-debating"');
    expect(element.innerHTML).toContain('data-current-state="debating"');
    expect(element.innerHTML).toContain('class="log-current-state is-chilling"');
    expect(element.innerHTML).toContain('data-current-state="chilling"');
    expect(element.innerHTML).toContain('class="log-current-state is-witnessing"');
    expect(element.innerHTML).toContain('data-current-state="witnessing"');
    expect(element.innerHTML).toContain('class="log-current-state is-moving"');
    expect(element.innerHTML).toContain('data-current-state="moving"');
    expect(element.innerHTML).toContain("Opponent");
    expect(element.innerHTML).toContain("Destination");
    expect(element.innerHTML).toContain("Witnessing");
    expect(element.innerHTML).toContain("Chilling");
  });

  it("renders the full profile controller log without dropping older LLM thoughts", () => {
    const conversationLog = Array.from({ length: 16 }, (_value, index) => {
      const tick = index + 1;
      return [
        controllerPromptMessage(tick, [
          "Nearby Team Size: Blue - 1, Red - 1",
          "You're in [Workshop] chilling; available for movement or debate.",
          "Nearby guests: none",
        ]),
        {
          content: JSON.stringify({
            type: "wait",
            thoughts: `full thought ${tick}`,
          }),
          role: "assistant" as const,
          tick,
        },
      ];
    }).flat();
    const worldSnapshot = snapshot([
      cog({
        color: "blue",
        conversationLog,
        id: "ada",
        name: "Ada",
      }),
    ]);
    const profileElement = renderProfileWithSnapshot(worldSnapshot, "ada");

    expect(profileElement.innerHTML).toContain('data-tick="1"');
    expect(profileElement.innerHTML).toContain("full thought 1");
  });

  it("keeps the desktop controller log as a wide two-column section", () => {
    const element = renderProfileWithSnapshot(
      snapshot([
        cog({
          color: "blue",
          conversationLog: [
            controllerPromptMessage(2, [
              "Nearby Team Size: Blue - 1, Red - 1",
              "You're moving to [bar], arriving t14.",
              "Nearby guests: none",
            ]),
            controllerPromptMessage(1, [
              "Nearby Team Size: Blue - 2, Red - 1",
              "You're in [Theater] debating Bob (Red, certainty 25)",
              "Nearby guests: Jack (Blue 20)",
            ]),
          ],
          id: "ada",
          name: "Ada",
        }),
      ]),
      "ada",
    );
    const controllerLogTag = profileControllerLogTag(element.innerHTML);
    const threadBlock = cssBlock(".profile-controller-log.profile-page-wide .profile-log-thread");
    const tickBlock = cssBlock(".profile-controller-log.profile-page-wide .log-tick-section");

    expect(controllerLogTag).toContain("profile-page-wide");
    expect(element.innerHTML).toMatch(/<\/div>\s*<details class="profile-block profile-controller-log profile-page-wide"/);
    expect(threadBlock).toContain("align-items: start;");
    expect(threadBlock).toContain("grid-template-columns: repeat(2, minmax(0, 1fr));");
    expect(tickBlock).toContain("align-self: start;");
  });

  it("renders instructions as one rich block and emphasizes prompt entities", () => {
    const element = renderProfileWithSnapshot(
      snapshot([
        cog({
          color: "blue",
          conversationLog: [
            controllerPromptMessage(
              1,
              [
                "Nearby Team Size: Blue - 2, Red - 1",
                "You're in [Theater] debating Bob (Red, certainty 25)",
                "Nearby guests: Jack (Blue 20)",
              ],
              {
                identity: [
                  "  [Stubborn] - losing an argument to Passion doesn't impact you as much.",
                  "  [Charismatic] - witnesses are impacted more by the results of your debate",
                ],
                achievements: [
                  "   - Win Round in Bar [45s left] - Win one round while both debaters are in a Bar room.",
                ],
                instructions: [
                  "Your name is Ada, and you are attending a party at the Grey Area Foundation.",
                  "You are on team Blue, and are 30% certain that you're on the correct team.",
                  "A debate is one two-cog session against a single opponent.",
                  "A debate can last up to five rounds.",
                  "Each round, choose Reason, Spin, or Passion to convince your opponent.",
                  "Reason beats Spin",
                  "Spin beats Passion",
                  "Passion beats Reason",
                ],
              },
            ),
          ],
          id: "ada",
          name: "Ada",
        }),
      ]),
      "ada",
    );
    const rulesSection = sectionHtml(element.innerHTML, "rules");
    const identitySection = sectionHtml(element.innerHTML, "identity");

    expect(rulesSection).toContain('class="log-instructions-block"');
    expect(rulesSection).not.toContain("log-outline-row");
    expect(rulesSection).toContain('class="log-emphasis log-emphasis-color" data-color="blue">Blue</strong>');
    expect(rulesSection).toContain('class="log-emphasis log-emphasis-number">30%</strong>');
    expect(rulesSection).toContain('class="log-tactic-icon" aria-hidden="true">🧠</span>Reason');
    expect(rulesSection).toContain('class="log-tactic-icon" aria-hidden="true">🔥</span>Passion');
    expect(rulesSection).toContain('class="log-tactic-icon" aria-hidden="true">🌀</span>Spin');
    expect(identitySection).toContain('class="log-emphasis log-emphasis-trait">[Stubborn]</strong>');
    expect(identitySection).toContain('class="log-emphasis log-emphasis-trait">[Charismatic]</strong>');
    expect(identitySection).toContain('class="log-emphasis log-emphasis-goal">Win Round in Bar</strong>');
    expect(identitySection).not.toContain("Majority");
  });

  it("opens current state, thoughts, and actions in the controller log by default", () => {
    const element = renderProfileWithSnapshot(
      snapshot([
        cog({
          conversationLog: [
            controllerPromptMessage(1, [
              "Nearby Team Size: Blue - 2, Red - 1",
              "You're in [Theater] debating Bob (Red, certainty 25)",
              "Nearby guests: Jack (Blue 20)",
            ]),
          ],
          id: "ada",
          name: "Ada",
        }),
      ]),
      "ada",
    );

    expect(detailsTagFor(element.innerHTML, "rules")).not.toContain(" open");
    expect(detailsTagFor(element.innerHTML, "identity")).not.toContain(" open");
    expect(detailsTagFor(element.innerHTML, "current")).toContain(" open");
    expect(detailsTagFor(element.innerHTML, "strategy")).not.toContain(" open");
    expect(detailsTagFor(element.innerHTML, "thoughts")).toContain(" open");
    expect(detailsTagFor(element.innerHTML, "actions")).toContain(" open");
  });

  it("filters the controller log by debates and movement", () => {
    const ada = cog({
      color: "blue",
      conversationLog: [
        controllerPromptMessage(3, [
          "Nearby Team Size: Blue - 1, Red - 1",
          "You're in [Lobby] chilling; available for movement or debate.",
          "Nearby guests: none",
        ]),
        controllerPromptMessage(2, [
          "Nearby Team Size: Blue - 1, Red - 1",
          "You're moving to [bar], arriving t14.",
          "Nearby guests: none",
        ]),
        controllerPromptMessage(1, [
          "Nearby Team Size: Blue - 2, Red - 1",
          "You're in [Theater] debating Bob (Red, certainty 25)",
          "Nearby guests: Jack (Blue 20)",
        ]),
      ],
      id: "ada",
      name: "Ada",
    });
    const worldSnapshot = snapshot([ada]);
    const markup = renderCogProfilePage(
      ada,
      worldSnapshot,
      profileDraftFor(ada),
      undefined,
      undefined,
      false,
      0,
      DIARY_INITIAL_ROOM_LIMIT,
      { debates: true, movement: false },
    );

    expect(markup).toContain('data-controller-log-filter="debates"');
    expect(markup).toContain('data-controller-log-filter="movement"');
    expect(markup).toContain('data-log-category="debates"');
    expect(markup).toContain('data-log-category="other"');
    expect(markup).not.toContain('data-log-category="movement"');
    expect(markup).toMatch(/data-controller-log-filter="debates"[\s\S]*aria-pressed="true"/);
    expect(markup).toMatch(/data-controller-log-filter="movement"[\s\S]*aria-pressed="false"/);
  });

  it("keeps controller log filter focus and panel scroll when filters rerender", () => {
    installFakeDom();
    const element = new FakeControllerLogRestoreRoot();
    const hud = new Hud(element as unknown as HTMLElement, stubActions);
    hud.update({
      connectionStatus: "connected",
      selectedCogId: "ada",
      snapshot: snapshot([
        cog({
          color: "blue",
          conversationLog: [
            controllerPromptMessage(2, [
              "Nearby Team Size: Blue - 1, Red - 1",
              "You're moving to [bar], arriving t14.",
              "Nearby guests: none",
            ]),
            controllerPromptMessage(1, [
              "Nearby Team Size: Blue - 2, Red - 1",
              "You're in [Theater] debating Bob (Red, certainty 25)",
              "Nearby guests: Jack (Blue 20)",
            ]),
          ],
          id: "ada",
          name: "Ada",
        }),
      ]),
    });
    hud.openCogProfilePage("ada");

    element.profileScroll.scrollTop = 312;
    element.profileScroll.scrollLeft = 19;
    element.logThread.scrollTop = 45;
    element.filterButton.dispatchFakeEvent("pointerdown");
    element.filterButton.focus();
    expect(element.profileScroll.scrollTop).toBe(0);

    element.filterButton.dispatchFakeEvent("click");

    expect(globalThis.document.activeElement).toBe(element.filterButton);
    expect(element.profileScroll.scrollTop).toBe(312);
    expect(element.profileScroll.scrollLeft).toBe(19);
    expect(element.logThread.scrollTop).toBe(45);
    expect(element.innerHTML).toMatch(/data-controller-log-filter="movement"[\s\S]*aria-pressed="false"/);
  });

  it("separates missing LLM thoughts from controller intent notes", () => {
    const element = renderProfileWithSnapshot(
      snapshot([
        cog({
          color: "blue",
          conversationLog: [
            controllerPromptMessage(1, [
              "Nearby Team Size: Blue - 2, Red - 1",
              "You're in [Theater] debating Bob (Red, certainty 25)",
              "Nearby guests: Jack (Blue 20)",
            ]),
            {
              content: JSON.stringify({ type: "chooseTactic", tactic: "spin", intent: "pressing the debate" }),
              role: "assistant",
              tick: 1,
            },
          ],
          id: "ada",
          name: "Ada",
        }),
      ]),
      "ada",
    );
    const thoughtsSection = sectionHtml(element.innerHTML, "thoughts");

    expect(thoughtsSection).toContain("LLM Thoughts");
    expect(thoughtsSection).toContain("No LLM thoughts recorded.");
    expect(thoughtsSection).toContain("Controller note: pressing the debate");
    expect(thoughtsSection).not.toContain('<p class="log-thoughts">pressing the debate</p>');
  });

  it("renders chilling current state as a plain room narrative", () => {
    const element = renderProfileWithSnapshot(
      snapshot([
        cog({
          color: "blue",
          conversationLog: [
            controllerPromptMessage(
              1,
              [
                "Nearby Team Size: Blue - 1, Red - 2",
                "You're in [Workshop] chilling; available for movement or debate.",
                "Nearby guests: Bob (Red 24), Alice (Blue 12)",
              ],
              {
                transcript: [
                  "You arrived at The Chair Nook - orange chair",
                  "You started moving to Workshop - workbench",
                  "You arrived at Workshop - workbench",
                  "Alice arrived at Bar - rail",
                  "Alice started moving to Workshop - stool",
                  "Alice arrived at Workshop - stool",
                  "Alice and Bob start debating",
                  "Alice converted from blue to red",
                  "You started moving to The Chair Nook - orange chair",
                ],
              },
            ),
          ],
          id: "ada",
          name: "Ada",
        }),
      ]),
      "ada",
    );
    const currentSection = sectionHtml(element.innerHTML, "current");

    expect(currentSection).toContain("You entered Workshop from The Chair Nook.");
    expect(currentSection).toContain("You noticed Bob (Red, 24).");
    expect(currentSection).toContain("Alice (Blue, 12) entered from Bar.");
    expect(currentSection).toContain("Alice and Bob started debating.");
    expect(currentSection).toContain("Alice flipped to Red.");
    expect(currentSection).toContain("You decided to move on.");
    expect(currentSection).not.toContain("Options");
    expect(currentSection).not.toContain("Nearby teams");
    expect(currentSection).not.toContain("Transcript");
  });

  it("renders legacy random choice letters as numbers", () => {
    const element = renderProfileWithSnapshot(
      snapshot([
        cog({
          color: "blue",
          conversationLog: [
            {
              content: [
                "Instructions:",
                "Stay at the party.",
                "",
                "You are:",
                "Ada",
                "",
                "Current State:",
                "Nearby Team Size: Blue - 1",
                "You're in [Workshop] debating Bob (Red, certainty 30)",
                "Nearby guests: Bob (Red 30)",
                "",
                "Transcript:",
                "No transcript yet.",
                "",
                "Pick an action:",
                "Random choice: B",
                "1. Reason",
                "2. Spin",
                "3. Passion",
              ].join("\n"),
              role: "user",
              tick: 1,
            },
          ],
          id: "ada",
          name: "Ada",
        }),
      ]),
      "ada",
    );
    const actionsSection = sectionHtml(element.innerHTML, "actions");

    expect(actionsSection).toContain("Random choice: 2");
    expect(actionsSection).not.toContain("Random choice: B");
  });

  it("formats move action choices without room ids", () => {
    const element = renderProfileWithSnapshot(
      snapshot([
        cog({
          color: "blue",
          conversationLog: [
            {
              content: [
                "Instructions:",
                "Stay at the party.",
                "",
                "You are:",
                "Ada",
                "",
                "Current State:",
                "Nearby Team Size: Blue - 1",
                "You're in [Workshop] chilling; available for movement or debate.",
                "",
                "Pick an action:",
                "1. Move to Center Cluster B (exhibit_center_b)",
                "2. Move to Projection Wall Pair (projection_pair)",
                "3. Move to Proscenium Apron (proscenium_apron)",
              ].join("\n"),
              role: "user",
              tick: 1,
            },
            {
              content: JSON.stringify({ type: "move", roomId: "projection_pair" }),
              role: "assistant",
              tick: 1,
            },
          ],
          id: "ada",
          name: "Ada",
        }),
      ]),
      "ada",
    );
    const actionsSection = sectionHtml(element.innerHTML, "actions");

    expect(actionsSection).toContain("1. Move To: Center Cluster B");
    expect(actionsSection).toContain("2. Move To: Projection Wall Pair");
    expect(actionsSection).toContain("3. Move To: Proscenium Apron");
    expect(actionsSection).not.toContain("Move to Center Cluster B");
    expect(actionsSection).not.toContain("exhibit_center_b");
    expect(actionsSection).not.toContain("projection_pair");
    expect(actionsSection).not.toContain("proscenium_apron");
    expect(actionsSection).toContain("log-outline-row is-action is-selected");
  });
});

function renderHudWithSnapshot(worldSnapshot: WorldSnapshot, serverStatus?: ServerStatus): FakeElement {
  installFakeDom();
  const element = new FakeElement();
  const hud = new Hud(element as unknown as HTMLElement, stubActions);
  hud.update({ connectionStatus: "connected", serverStatus, snapshot: worldSnapshot });
  return element;
}

function renderProfileWithSnapshot(worldSnapshot: WorldSnapshot, cogId: string): FakeElement {
  installFakeDom();
  const element = new FakeElement();
  const hud = new Hud(element as unknown as HTMLElement, stubActions);
  hud.update({ connectionStatus: "connected", selectedCogId: cogId, snapshot: worldSnapshot });
  hud.openCogProfilePage(cogId);
  return element;
}

function installFakeDom(): void {
  const FakeHTMLElement = class {};
  globalThis.document = { activeElement: undefined } as unknown as Document;
  globalThis.HTMLElement = FakeHTMLElement as typeof HTMLElement;
  globalThis.HTMLInputElement = class extends FakeHTMLElement {} as typeof HTMLInputElement;
  globalThis.HTMLTextAreaElement = class extends FakeHTMLElement {} as typeof HTMLTextAreaElement;
  globalThis.HTMLSelectElement = class extends FakeHTMLElement {} as typeof HTMLSelectElement;
}

function createFocusableElement(dataset: Record<string, string>): HTMLElement {
  return new (class extends HTMLElement {
    dataset = dataset as DOMStringMap;
    scrollLeft = 0;
    scrollTop = 0;

    addEventListener(): void {
      // Test double only needs listener attachment to be accepted.
    }

    closest(): null {
      return null;
    }

    focus(): void {
      (globalThis.document as unknown as { activeElement: unknown }).activeElement = this;
    }

    getAttribute(): null {
      return null;
    }

    hasAttribute(): boolean {
      return false;
    }
  })();
}

function createControllerLogFilterButton(
  filter: "debates" | "movement",
  profileScroll: () => FakeScrollContainer,
  profilePage: HTMLElement,
): HTMLElement & { dispatchFakeEvent: (type: string, init?: { key?: string }) => void } {
  return new (class extends HTMLElement {
    private readonly listeners = new Map<string, Array<(event: { key?: string }) => void>>();
    dataset = { action: "toggle-controller-log-filter", controllerLogFilter: filter } as DOMStringMap;
    scrollLeft = 0;
    scrollTop = 0;

    addEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
      const callbacks = this.listeners.get(type) ?? [];
      callbacks.push((event) => {
        if (typeof listener === "function") {
          listener(event as Event);
        } else {
          listener.handleEvent(event as Event);
        }
      });
      this.listeners.set(type, callbacks);
    }

    closest(selector: string): HTMLElement | null {
      return selector === "[data-cog-id]" ? profilePage : null;
    }

    dispatchFakeEvent(type: string, init: { key?: string } = {}): void {
      for (const listener of [...(this.listeners.get(type) ?? [])]) {
        listener(init);
      }
    }

    focus(): void {
      profileScroll().scrollLeft = 0;
      profileScroll().scrollTop = 0;
      (globalThis.document as unknown as { activeElement: unknown }).activeElement = this;
    }

    getAttribute(): null {
      return null;
    }

    hasAttribute(): boolean {
      return false;
    }
  })();
}

function createControllerLogProfilePage(cogId: string): HTMLElement {
  return new (class extends HTMLElement {
    dataset = { cogId } as DOMStringMap;
  })();
}

function createControllerLogDetails(profilePage: HTMLElement): HTMLElement {
  return new (class extends HTMLElement {
    classList = {
      contains: (className: string) => className === "profile-controller-log",
    } as DOMTokenList;
    dataset = {} as DOMStringMap;
    open = true;

    addEventListener(): void {
      // Test double only needs listener attachment to be accepted.
    }

    closest(selector: string): HTMLElement | null {
      return selector === ".cog-profile-page[data-cog-id]" ? profilePage : null;
    }

    matches(): boolean {
      return false;
    }
  })();
}

function serverStatus(overrides: Partial<ServerStatus> = {}): ServerStatus {
  return {
    tick: 1,
    cogCount: 1,
    clientCount: 0,
    controllerMode: "stub",
    discoMode: false,
    llmMoveDecisions: 0,
    llmTimedOutMovePercent: 0,
    llmTimedOutMoves: 0,
    simulationMode: "playing",
    stepRequested: false,
    ...overrides,
  };
}

function cog(overrides: Pick<Cog, "color" | "id" | "name"> & Partial<Cog>): Cog {
  return {
    ...baseCog,
    position: { x: 0, y: 0 },
    ...overrides,
  };
}

function profileDraftFor(cog: Cog) {
  return {
    activeTrait: cog.activeTrait,
    attributes: { ...cog.attributes },
    behaviorPrompt: cog.behaviorPrompt,
    defensiveTrait: cog.defensiveTrait,
    name: cog.name,
  };
}

function snapshot(cogs: Cog[]): WorldSnapshot {
  return {
    cogs,
    dimensions: { width: 10, height: 8 },
    objects: [],
    recentEvents: [],
    terrain: [],
    tick: 1,
  };
}

function controllerPromptMessage(
  tick: number,
  currentStateLines: string[],
  options: {
    achievements?: string[];
    identity?: string[];
    instructions?: string[];
    transcript?: string[];
  } = {},
): CogConversationMessage {
  const identity = options.identity ?? ["Ada"];
  const achievements = options.achievements ?? [];
  const instructions = options.instructions ?? ["Stay at the party."];
  const transcript = options.transcript ?? ["No transcript yet."];
  return {
    content: [
      "Instructions:",
      ...instructions,
      "",
      "You are:",
      ...identity,
      ...(achievements.length > 0 ? ["", "Your achievements are:", ...achievements] : []),
      "",
      "Current State:",
      ...currentStateLines,
      "",
      "Transcript:",
      ...transcript,
      "",
      "Pick an action:",
      "1. Wait",
    ].join("\n"),
    role: "user",
    tick,
  };
}

function sectionHtml(html: string, subsection: string): string {
  const marker = `data-log-subsection="${subsection}"`;
  const start = html.indexOf(marker);
  expect(start).toBeGreaterThanOrEqual(0);
  const next = html.indexOf('data-log-subsection="', start + marker.length);
  return next === -1 ? html.slice(start) : html.slice(start, next);
}

function detailsTagFor(html: string, subsection: string): string {
  const marker = `data-log-subsection="${subsection}"`;
  const markerIndex = html.indexOf(marker);
  expect(markerIndex).toBeGreaterThanOrEqual(0);
  const tagStart = html.lastIndexOf("<details", markerIndex);
  const tagEnd = html.indexOf(">", markerIndex);
  return html.slice(tagStart, tagEnd + 1);
}

function profileControllerLogTag(html: string): string {
  const marker = 'class="profile-block profile-controller-log profile-page-wide"';
  const markerIndex = html.indexOf(marker);
  expect(markerIndex).toBeGreaterThanOrEqual(0);
  const tagStart = html.lastIndexOf("<details", markerIndex);
  const tagEnd = html.indexOf(">", markerIndex);
  return html.slice(tagStart, tagEnd + 1);
}

function htmlBlock(html: string, className: string): string {
  const match = new RegExp(`<div class="${className}"[\\s\\S]*?</div>`).exec(html);
  return match?.[0] ?? "";
}

function cssBlock(selector: string): string {
  const match = styles.match(new RegExp(`${escapeRegExp(selector)}\\s*\\{[\\s\\S]*?\\n\\s*\\}`));
  expect(match).toBeTruthy();
  return match?.[0] ?? "";
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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
