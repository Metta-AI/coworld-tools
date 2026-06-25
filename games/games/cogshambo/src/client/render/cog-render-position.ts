import type { Cog, Position, WorldSnapshot } from "../../shared/types";
import { SIMULATION_TICK_MS, secondsToSimulationTicks } from "../../shared/timing";
import { pathLength, positionAlongPath, venueMovementPositionForRender } from "./venue-movement";

export const COG_SPAWN_HALO_TICKS = secondsToSimulationTicks(30);

export type CogRenderTiming = {
  snapshotSeenAtMs: number;
  movementTimingForCog?: (cog: Cog) => CogMovementRenderTiming | undefined;
  spawnTimingForCog?: (cog: Cog) => CogSpawnRenderTiming | undefined;
};

type CogMovementRenderTiming = {
  movementSeenAtMs: number;
  movementSeenTick: number;
};

type CogSpawnRenderTiming = {
  spawnSeenAtMs: number;
  spawnSeenTicksAlive: number;
};

type MovementRenderAnchor = {
  key: string;
  seenAtMs: number;
  seenTick: number;
};

type SpawnRenderAnchor = {
  seenAtMs: number;
  seenTicksAlive: number;
};

const COG_SPAWN_ENTRY_TICKS = secondsToSimulationTicks(6);
const COG_SPAWN_ENTRANCE_X = -2;

export class CogRenderPositionTracker {
  private readonly movementRenderAnchors = new Map<string, MovementRenderAnchor>();
  private readonly spawnRenderAnchors = new Map<string, SpawnRenderAnchor>();
  private snapshotSeenAtMs = 0;
  private snapshotTick: number | undefined;

  timingForSnapshot(snapshot: WorldSnapshot, frameTimeMs: number): CogRenderTiming {
    if (this.snapshotTick !== snapshot.tick) {
      this.snapshotTick = snapshot.tick;
      this.snapshotSeenAtMs = frameTimeMs;
    }
    this.pruneMovementRenderAnchors(snapshot);
    this.pruneSpawnRenderAnchors(snapshot);

    return {
      snapshotSeenAtMs: this.snapshotSeenAtMs,
      movementTimingForCog: (cog) => this.movementTimingForCog(cog, snapshot.tick, frameTimeMs),
      spawnTimingForCog: (cog) => this.spawnTimingForCog(cog, frameTimeMs),
    };
  }

  private movementTimingForCog(cog: Cog, snapshotTick: number, frameTimeMs: number): CogMovementRenderTiming | undefined {
    const key = movementRenderKey(cog);
    if (!key) {
      return undefined;
    }

    const existing = this.movementRenderAnchors.get(cog.id);
    if (existing?.key === key) {
      return {
        movementSeenAtMs: existing.seenAtMs,
        movementSeenTick: existing.seenTick,
      };
    }

    const anchor: MovementRenderAnchor = {
      key,
      seenAtMs: frameTimeMs,
      seenTick: snapshotTick,
    };
    this.movementRenderAnchors.set(cog.id, anchor);
    return {
      movementSeenAtMs: anchor.seenAtMs,
      movementSeenTick: anchor.seenTick,
    };
  }

  private pruneMovementRenderAnchors(snapshot: WorldSnapshot): void {
    const activeMovementKeys = new Map<string, string>();
    for (const cog of snapshot.cogs) {
      const key = movementRenderKey(cog);
      if (key) {
        activeMovementKeys.set(cog.id, key);
      }
    }

    for (const [cogId, anchor] of this.movementRenderAnchors) {
      if (activeMovementKeys.get(cogId) !== anchor.key) {
        this.movementRenderAnchors.delete(cogId);
      }
    }
  }

  private spawnTimingForCog(cog: Cog, frameTimeMs: number): CogSpawnRenderTiming | undefined {
    const ticksAlive = renderSnapshotTicksAlive(cog);
    if (ticksAlive >= COG_SPAWN_HALO_TICKS) {
      this.spawnRenderAnchors.delete(cog.id);
      return undefined;
    }

    const existing = this.spawnRenderAnchors.get(cog.id);
    if (existing) {
      return {
        spawnSeenAtMs: existing.seenAtMs,
        spawnSeenTicksAlive: existing.seenTicksAlive,
      };
    }

    const anchor: SpawnRenderAnchor = {
      seenAtMs: frameTimeMs,
      seenTicksAlive: ticksAlive,
    };
    this.spawnRenderAnchors.set(cog.id, anchor);
    return {
      spawnSeenAtMs: anchor.seenAtMs,
      spawnSeenTicksAlive: anchor.seenTicksAlive,
    };
  }

  private pruneSpawnRenderAnchors(snapshot: WorldSnapshot): void {
    const activeSpawnCogIds = new Set(
      snapshot.cogs.filter((cog) => renderSnapshotTicksAlive(cog) < COG_SPAWN_HALO_TICKS).map((cog) => cog.id),
    );

    for (const cogId of this.spawnRenderAnchors.keys()) {
      if (!activeSpawnCogIds.has(cogId)) {
        this.spawnRenderAnchors.delete(cogId);
      }
    }
  }
}

export function cogPositionForRender(
  cog: Cog,
  snapshot: WorldSnapshot,
  frameTimeMs: number,
  timing?: CogRenderTiming,
): Position {
  const movementTiming = timing?.movementTimingForCog?.(cog);
  const movementPosition = timing
    ? venueMovementPositionForRender(
        cog,
        snapshot.tick,
        timing.snapshotSeenAtMs,
        frameTimeMs,
        movementTiming?.movementSeenAtMs,
        movementTiming?.movementSeenTick,
      )
    : cog.position;
  return spawnEntrancePositionForRender(cog, snapshot, movementPosition, cogTicksAliveForRender(cog, timing, frameTimeMs));
}

export function cogTicksAliveForRender(cog: Cog, timing: CogRenderTiming | undefined, frameTimeMs: number): number {
  const ticksAlive = renderSnapshotTicksAlive(cog);
  if (!timing) {
    return ticksAlive;
  }

  const snapshotTicksAlive = ticksAlive + Math.max(0, (frameTimeMs - timing.snapshotSeenAtMs) / SIMULATION_TICK_MS);
  const spawnTiming = timing.spawnTimingForCog?.(cog);
  const anchoredTicksAlive = spawnTiming
    ? spawnTiming.spawnSeenTicksAlive + Math.max(0, (frameTimeMs - spawnTiming.spawnSeenAtMs) / SIMULATION_TICK_MS)
    : snapshotTicksAlive;

  return Math.max(ticksAlive, snapshotTicksAlive, anchoredTicksAlive);
}

function spawnEntrancePositionForRender(
  cog: Cog,
  snapshot: WorldSnapshot,
  targetPosition: Position,
  ticksAlive: number,
): Position {
  if (ticksAlive >= COG_SPAWN_ENTRY_TICKS) {
    return targetPosition;
  }

  const entrance = lobbyEntrancePosition(snapshot) ?? { x: 0, y: targetPosition.y };
  const path = [{ x: COG_SPAWN_ENTRANCE_X, y: entrance.y }, entrance, targetPosition];
  const progress = easeOutCubic(Math.max(0, ticksAlive) / Math.max(1, COG_SPAWN_ENTRY_TICKS));
  return positionAlongPath(path, pathLength(path) * progress);
}

function renderSnapshotTicksAlive(cog: Cog): number {
  return Number.isFinite(cog.ticksAlive) ? Math.max(0, cog.ticksAlive) : COG_SPAWN_HALO_TICKS;
}

function lobbyEntrancePosition(snapshot: WorldSnapshot): Position | undefined {
  const spots = snapshot.venue?.spots ?? [];
  return (
    spots.find((spot) => spot.id === "lobby_entry_door")?.position ??
    spots.find((spot) => /lobby/i.test(spot.roomId) && /(door|entrance|entry|front)/i.test(`${spot.id} ${spot.label}`))?.position
  );
}

function movementRenderKey(cog: Cog): string | undefined {
  if (!cog.moving) {
    return undefined;
  }

  return [
    cog.moving.startedTick,
    cog.moving.arriveTick,
    locationKey(cog.moving.from),
    locationKey(cog.moving.to),
    pathKey(cog.moving.path?.length ? cog.moving.path : [cog.moving.fromPosition, cog.moving.toPosition]),
  ].join("|");
}

function locationKey(location: { roomId: string; spotId: string }): string {
  return `${location.roomId}:${location.spotId}`;
}

function pathKey(path: Position[]): string {
  return path.map((position) => `${position.x},${position.y}`).join(";");
}

function easeOutCubic(amount: number): number {
  const clamped = Math.min(1, Math.max(0, amount));
  return 1 - (1 - clamped) ** 3;
}
