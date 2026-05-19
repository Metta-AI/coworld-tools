import type { Cog, Position } from "../../shared/types";
import { SIMULATION_TICK_MS } from "../../shared/timing";

export function venueMovementPositionForRender(
  cog: Pick<Cog, "moving" | "position">,
  snapshotTick: number,
  snapshotSeenAt: number,
  now: number,
  movementSeenAt = snapshotSeenAt,
  movementSeenTick = snapshotTick,
): Position {
  if (!cog.moving) {
    return clonePosition(cog.position);
  }

  const path = cog.moving.path?.length > 0 ? cog.moving.path : [cog.moving.fromPosition, cog.moving.toPosition];
  const snapshotMovementTicks = Math.max(0, snapshotTick - cog.moving.startedTick);
  const anchorMovementTicks = Math.max(0, movementSeenTick - cog.moving.startedTick);
  const elapsedTicks = Math.max(0, (now - movementSeenAt) / SIMULATION_TICK_MS);
  const durationTicks = Math.max(1, cog.moving.arriveTick - cog.moving.startedTick);
  const movementTicks = Math.min(durationTicks, Math.max(snapshotMovementTicks, anchorMovementTicks + elapsedTicks));
  return positionAlongPath(path, movementTicks * venueMovementTilesPerTick(path, durationTicks));
}

function venueMovementTilesPerTick(path: Position[], durationTicks: number): number {
  return pathLength(path) / Math.max(1, durationTicks);
}

export function pathLength(path: Position[]): number {
  let length = 0;
  for (let index = 1; index < path.length; index += 1) {
    const start = path[index - 1];
    const end = path[index];
    length += Math.hypot(end.x - start.x, end.y - start.y);
  }
  return length;
}

export function positionAlongPath(path: Position[], distance: number): Position {
  const first = path[0];
  if (!first) {
    return { x: 0, y: 0 };
  }

  let remaining = Math.max(0, distance);
  for (let index = 1; index < path.length; index += 1) {
    const start = path[index - 1];
    const end = path[index];
    const segmentLength = Math.hypot(end.x - start.x, end.y - start.y);
    if (segmentLength <= 0) {
      continue;
    }
    if (remaining <= segmentLength) {
      const amount = remaining / segmentLength;
      return {
        x: start.x + (end.x - start.x) * amount,
        y: start.y + (end.y - start.y) * amount,
      };
    }
    remaining -= segmentLength;
  }

  return clonePosition(path[path.length - 1]);
}

function clonePosition(position: Position): Position {
  return { ...position };
}
