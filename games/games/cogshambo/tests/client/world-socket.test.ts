import { afterEach, describe, expect, it, vi } from "vitest";
import { parseServerMessage, WorldSocket } from "../../src/client/net/world-socket";
import { createSeedWorld } from "../../src/server/simulation/seed-world";

describe("WorldSocket", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("reloads the page when the websocket stays disconnected without a recent heartbeat", () => {
    const browser = installFakeBrowser();

    WorldSocket.connect({
      onMessage: () => undefined,
      onStatus: () => undefined,
    });
    browser.sockets[0]?.close();

    vi.advanceTimersByTime(60_000);

    expect(browser.reload).toHaveBeenCalledTimes(1);
  });

  it("skips the disconnect reload when a websocket heartbeat arrived in the last minute", () => {
    const browser = installFakeBrowser();

    WorldSocket.connect({
      onMessage: () => undefined,
      onStatus: () => undefined,
    });
    browser.sockets[0]?.close();
    vi.advanceTimersByTime(250);
    browser.sockets[1]?.open();
    browser.sockets[1]?.message(serverStatusMessage());

    vi.advanceTimersByTime(59_750);

    expect(browser.reload).not.toHaveBeenCalled();
  });

  it("reschedules the reload check when a later websocket disconnects after a recent heartbeat", () => {
    const browser = installFakeBrowser();

    WorldSocket.connect({
      onMessage: () => undefined,
      onStatus: () => undefined,
    });
    browser.sockets[0]?.close();
    vi.advanceTimersByTime(250);
    browser.sockets[1]?.open();
    browser.sockets[1]?.message(serverStatusMessage());

    vi.advanceTimersByTime(49_750);
    browser.sockets[1]?.close();
    vi.advanceTimersByTime(10_000);
    expect(browser.reload).not.toHaveBeenCalled();

    vi.advanceTimersByTime(50_000);

    expect(browser.reload).toHaveBeenCalledTimes(1);
  });

  it("normalizes legacy snapshot messages before protocol parsing", () => {
    const parsed = parseServerMessage(JSON.stringify({
      type: "snapshot",
      snapshot: {
        tick: 1,
        dimensions: { width: 6, height: 6 },
        activeColors: ["red", "blue"],
        cogs: [
          {
            id: "cog-red",
            name: "Red",
            behaviorPrompt: "",
            position: { x: 2, y: 2 },
            spriteSheetKey: "cog-default",
            attributes: { energy: 5 },
            color: "red",
            defensiveTrait: "stubborn",
            activeTrait: "forceful",
            personalGoal: "majority",
            activity: "idle",
            personalScore: 0,
            achievements: [],
            completedAchievements: [],
            goalScores: [],
            stats: { argumentsWon: 0, argumentsLost: 0, teamFlips: 0 },
            doubt: { red: 0, blue: 12 },
            controllerId: "stub",
            movementCooldown: 0,
            conversationLog: [],
          },
        ],
        objects: [],
        terrain: [],
        recentEvents: [],
      },
    }));

    expect(parsed?.type).toBe("snapshot");
    if (parsed?.type !== "snapshot") {
      throw new Error("Expected a parsed snapshot message");
    }
    expect(parsed.snapshot).not.toHaveProperty("activeColors");
    expect(parsed.snapshot.cogs[0]?.certainty).toBe(88);
  });

  it("strips legacy doubt from snapshots that already have certainty", () => {
    const parsed = parseServerMessage(JSON.stringify({
      type: "snapshot",
      snapshot: {
        tick: 1,
        dimensions: { width: 6, height: 6 },
        cogs: [
          {
            id: "cog-red",
            name: "Red",
            behaviorPrompt: "",
            position: { x: 2, y: 2 },
            spriteSheetKey: "cog-default",
            attributes: { energy: 5 },
            color: "red",
            defensiveTrait: "stubborn",
            activeTrait: "forceful",
            personalGoal: "majority",
            activity: "idle",
            personalScore: 0,
            achievements: [],
            completedAchievements: [],
            goalScores: [],
            stats: { argumentsWon: 0, argumentsLost: 0, teamFlips: 0 },
            certainty: 76,
            doubt: { red: 0, blue: 24 },
            controllerId: "stub",
            movementCooldown: 0,
            conversationLog: [],
          },
        ],
        objects: [],
        terrain: [],
        recentEvents: [],
      },
    }));

    expect(parsed?.type).toBe("snapshot");
    if (parsed?.type !== "snapshot") {
      throw new Error("Expected a parsed snapshot message");
    }
    expect(parsed.snapshot.cogs[0]).not.toHaveProperty("doubt");
    expect(parsed.snapshot.cogs[0]?.certainty).toBe(76);
  });

  it("drops unknown retired achievement ids instead of rejecting the whole snapshot", () => {
    const parsed = parseServerMessage(JSON.stringify({
      type: "snapshot",
      snapshot: {
        tick: 1,
        dimensions: { width: 6, height: 6 },
        cogs: [
          {
            id: "cog-red",
            name: "Red",
            behaviorPrompt: "",
            position: { x: 2, y: 2 },
            spriteSheetKey: "cog-default",
            attributes: { energy: 5 },
            color: "red",
            defensiveTrait: "stubborn",
            activeTrait: "forceful",
            personalGoal: "majority",
            activity: "idle",
            personalScore: 0,
            achievements: [
              {
                assignmentId: "legacy-assignment",
                achievementId: "retiredAchievement",
                assignedTick: 0,
                timeoutTick: 100,
              },
              {
                assignmentId: "known-assignment",
                achievementId: "debateThreeCogs",
                assignedTick: 0,
                timeoutTick: 100,
              },
            ],
            completedAchievements: [
              {
                assignmentId: "legacy-completed",
                achievementId: "retiredCompletedAchievement",
                assignedTick: 0,
                timeoutTick: 100,
                completedTick: 1,
                points: 10,
              },
            ],
            goalScores: [],
            stats: { argumentsWon: 0, argumentsLost: 0, teamFlips: 0 },
            certainty: 76,
            controllerId: "stub",
            movementCooldown: 0,
            conversationLog: [],
          },
        ],
        objects: [],
        terrain: [],
        recentEvents: [],
        achievementCounts: [
          {
            achievementId: "retiredAchievement",
            assigned: 1,
            completed: 0,
            current: 1,
            expired: 0,
          },
          {
            achievementId: "debateThreeCogs",
            assigned: 1,
            completed: 0,
            current: 1,
            expired: 0,
          },
        ],
      },
    }));

    expect(parsed?.type).toBe("snapshot");
    if (parsed?.type !== "snapshot") {
      throw new Error("Expected a parsed snapshot message");
    }
    expect(parsed.snapshot.cogs[0]?.achievements.map((achievement) => achievement.achievementId)).toEqual(["debateThreeCogs"]);
    expect(parsed.snapshot.cogs[0]?.completedAchievements).toEqual([]);
    expect(parsed.snapshot.achievementCounts.map((count) => count.achievementId)).toEqual(["debateThreeCogs"]);
  });

  it("drops retired map objects instead of rejecting the whole snapshot", () => {
    const parsed = parseServerMessage(JSON.stringify({
      type: "snapshot",
      snapshot: {
        tick: 1,
        dimensions: { width: 6, height: 6 },
        cogs: [],
        objects: [
          {
            id: "retired-map-object",
            type: "retired-object",
            position: { x: 1, y: 1 },
            spriteKey: "map-object-marker",
            attributes: {},
          },
          {
            id: "bench-object",
            type: "bench",
            position: { x: 2, y: 2 },
            spriteKey: "map-object-marker",
            attributes: {},
          },
        ],
        terrain: [],
        recentEvents: [],
      },
    }));

    expect(parsed?.type).toBe("snapshot");
    if (parsed?.type !== "snapshot") {
      throw new Error("Expected a parsed snapshot message");
    }
    expect(parsed.snapshot.objects.map((object) => object.id)).toEqual(["bench-object"]);
  });

  it("accepts achievement count parameters from goal snapshots", () => {
    const parsed = parseServerMessage(JSON.stringify({
      type: "snapshot",
      snapshot: {
        tick: 1,
        dimensions: { width: 6, height: 6 },
        cogs: [],
        objects: [],
        terrain: [],
        recentEvents: [],
        achievementCounts: [
          {
            achievementId: "winInRoom",
            parameters: { roomKind: "walkway" },
            assigned: 1,
            completed: 0,
            current: 1,
            expired: 0,
          },
          {
            achievementId: "witnessTeamWins",
            parameters: { team: "blue", rounds: 4 },
            assigned: 1,
            completed: 0,
            current: 1,
            expired: 0,
          },
        ],
      },
    }));

    expect(parsed?.type).toBe("snapshot");
    if (parsed?.type !== "snapshot") {
      throw new Error("Expected a parsed snapshot message");
    }
    expect(parsed.snapshot.achievementCounts[0]?.parameters).toEqual({ roomKind: "walkway" });
    expect(parsed.snapshot.achievementCounts[1]?.parameters).toEqual({ team: "blue", rounds: 4 });
  });

  it("parses current server seed snapshots instead of dropping the whole browser update", () => {
    const snapshot = createSeedWorld(undefined, { controllerId: "wander" }).snapshot();
    const parsed = parseServerMessage(JSON.stringify({ type: "snapshot", snapshot }));

    expect(snapshot.cogs.length).toBeGreaterThan(0);
    expect(snapshot.achievementCounts.some((count) => count.parameters?.roomKind)).toBe(true);
    expect(parsed?.type).toBe("snapshot");
    if (parsed?.type !== "snapshot") {
      throw new Error("Expected a parsed snapshot message");
    }
    expect(parsed.snapshot.cogs).toHaveLength(snapshot.cogs.length);
  });
});

type FakeBrowser = {
  reload: ReturnType<typeof vi.fn>;
  sockets: FakeWebSocket[];
};

type FakeWebSocketEvent = {
  data?: string;
};

type FakeWebSocketListener = (event: FakeWebSocketEvent) => void;

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 3;

  readonly listeners = new Map<string, FakeWebSocketListener[]>();
  readyState = FakeWebSocket.CONNECTING;

  constructor(readonly url: string) {
    fakeWebSocketInstances.push(this);
  }

  addEventListener(type: string, listener: FakeWebSocketListener): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  send(): void {
    return;
  }

  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.emit("open", {});
  }

  message(data: string): void {
    this.emit("message", { data });
  }

  close(): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.emit("close", {});
  }

  private emit(type: string, event: FakeWebSocketEvent): void {
    for (const listener of this.listeners.get(type) ?? []) {
      listener(event);
    }
  }
}

let fakeWebSocketInstances: FakeWebSocket[] = [];

function installFakeBrowser(): FakeBrowser {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-05-15T00:00:00Z"));
  fakeWebSocketInstances = [];

  const reload = vi.fn();
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.stubGlobal("window", {
    location: {
      protocol: "http:",
      host: "127.0.0.1:8787",
      reload,
    },
    setTimeout,
    clearTimeout,
  });

  return {
    reload,
    sockets: fakeWebSocketInstances,
  };
}

function serverStatusMessage(): string {
  return JSON.stringify({
    type: "serverStatus",
    status: {
      tick: 1,
      cogCount: 2,
      clientCount: 1,
      controllerMode: "llm",
      simulationMode: "playing",
      stepRequested: false,
    },
  });
}
