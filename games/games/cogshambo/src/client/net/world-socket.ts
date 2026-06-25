import {
  achievementIdSchema,
  serverMessageSchema,
  worldObjectSchema,
  type ClientMessage,
  type ServerMessage,
} from "../../shared/protocol";

export type WorldSocketHandlers = {
  onMessage: (message: ServerMessage) => void;
  onStatus: (status: string) => void;
};

const HEARTBEAT_FRESH_MS = 60_000;
const MAYBE_RELOAD_DELAY_MS = 60_000;

export class WorldSocket {
  private lastHeartbeatAt: number | undefined;
  private maybeReloadTimeout: number | undefined;
  private reconnectDelayMs = 250;
  private socket: WebSocket | undefined;

  private constructor(private readonly handlers: WorldSocketHandlers) {}

  static connect(handlers: WorldSocketHandlers): WorldSocket {
    const worldSocket = new WorldSocket(handlers);
    worldSocket.connect();
    return worldSocket;
  }

  send(message: ClientMessage): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(message));
    }
  }

  private connect(): void {
    this.handlers.onStatus("connecting");

    const socket = new WebSocket(this.url());
    this.socket = socket;

    socket.addEventListener("open", () => {
      this.reconnectDelayMs = 250;
      this.handlers.onStatus("connected");
      this.send({ type: "hello", clientName: "browser" });
    });

    socket.addEventListener("message", (event) => {
      const message = this.parse(event.data);
      if (message) {
        this.lastHeartbeatAt = Date.now();
        this.handlers.onMessage(message);
      }
    });

    socket.addEventListener("error", () => {
      this.handlers.onStatus("error");
    });

    socket.addEventListener("close", () => {
      if (this.socket === socket) {
        this.socket = undefined;
        this.scheduleMaybeReload();
      }

      this.handlers.onStatus("reconnecting");
      const delay = this.reconnectDelayMs;
      this.reconnectDelayMs = Math.min(this.reconnectDelayMs * 2, 5_000);
      window.setTimeout(() => this.connect(), delay);
    });
  }

  private parse(data: unknown): ServerMessage | undefined {
    return parseServerMessage(data);
  }

  private scheduleMaybeReload(): void {
    if (this.maybeReloadTimeout !== undefined) {
      window.clearTimeout(this.maybeReloadTimeout);
    }

    this.maybeReloadTimeout = window.setTimeout(() => {
      this.maybeReloadTimeout = undefined;
      this.maybeReload();
    }, MAYBE_RELOAD_DELAY_MS);
  }

  private maybeReload(): void {
    if (this.lastHeartbeatAt !== undefined && Date.now() - this.lastHeartbeatAt < HEARTBEAT_FRESH_MS) {
      return;
    }

    window.location.reload();
  }

  private url(): string {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}/ws`;
  }
}

export function parseServerMessage(data: unknown): ServerMessage | undefined {
  if (typeof data !== "string") {
    return undefined;
  }

  try {
    const value = normalizeLegacyServerMessage(JSON.parse(data) as unknown);
    return serverMessageSchema.safeParse(value).data;
  } catch {
    return undefined;
  }
}

function normalizeLegacyServerMessage(value: unknown): unknown {
  if (!isRecord(value) || value.type !== "snapshot" || !isRecord(value.snapshot)) {
    return value;
  }

  return {
    ...value,
    snapshot: normalizeLegacySnapshot(value.snapshot),
  };
}

function normalizeLegacySnapshot(snapshot: Record<string, unknown>): Record<string, unknown> {
  const { activeColors: _activeColors, ...normalized } = snapshot;
  return {
    ...normalized,
    ...(Array.isArray(normalized.cogs) ? { cogs: normalized.cogs.map(normalizeLegacyCog) } : {}),
    ...(Array.isArray(normalized.objects)
      ? { objects: normalized.objects.filter((object) => worldObjectSchema.safeParse(object).success) }
      : {}),
    ...(Array.isArray(normalized.achievementCounts)
      ? { achievementCounts: normalizeLegacyAchievements(normalized.achievementCounts) }
      : {}),
  };
}

function normalizeLegacyAchievements(value: unknown[]): unknown[] {
  return value.filter((achievement) => {
    if (!isRecord(achievement) || typeof achievement.achievementId !== "string") {
      return true;
    }

    return achievementIdSchema.safeParse(achievement.achievementId).success;
  });
}

function normalizeLegacyCogAchievements(cog: Record<string, unknown>): Record<string, unknown> {
  return {
    ...cog,
    ...(Array.isArray(cog.achievements) ? { achievements: normalizeLegacyAchievements(cog.achievements) } : {}),
    ...(Array.isArray(cog.completedAchievements)
      ? { completedAchievements: normalizeLegacyAchievements(cog.completedAchievements) }
      : {}),
  };
}

function normalizeLegacyCog(cog: unknown): unknown {
  if (!isRecord(cog)) {
    return cog;
  }

  const { doubt: _doubt, ...normalizedCog } = cog;
  if (typeof cog.certainty === "number") {
    return normalizeLegacyCogAchievements(normalizedCog);
  }

  const doubt = legacyDoubt(cog);
  if (typeof doubt !== "number") {
    return normalizeLegacyCogAchievements(normalizedCog);
  }

  return normalizeLegacyCogAchievements({ ...normalizedCog, certainty: Math.max(0, 100 - doubt) });
}

function legacyDoubt(cog: Record<string, unknown>): number | undefined {
  if (typeof cog.doubt === "number") {
    return cog.doubt;
  }

  if (!isRecord(cog.doubt)) {
    return undefined;
  }

  const color = typeof cog.color === "string" ? cog.color : undefined;
  return Object.entries(cog.doubt).reduce((highest, [doubtColor, doubt]) => {
    if (doubtColor === color || typeof doubt !== "number") {
      return highest;
    }
    return Math.max(highest, doubt);
  }, 0);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
