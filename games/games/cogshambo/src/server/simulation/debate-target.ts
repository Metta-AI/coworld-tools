import type { Color, Position, VenueLocation } from "../../shared/types.js";

type DebateParticipant = {
  id: string;
  color: Color;
  position: Position;
  location?: VenueLocation;
  debate?: unknown;
  moving?: unknown;
};

export function isEligibleDebateTarget(actor: DebateParticipant, target: DebateParticipant): boolean {
  return (
    target.id !== actor.id &&
    !actor.moving &&
    !target.debate &&
    !target.moving &&
    target.color !== actor.color &&
    (actor.location && target.location
      ? actor.location.roomId === target.location.roomId
      : Math.abs(target.position.x - actor.position.x) + Math.abs(target.position.y - actor.position.y) === 1)
  );
}
