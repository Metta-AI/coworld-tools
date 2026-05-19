import type { CogAction, CogDecisionInput, Direction } from "../../shared/types.js";
import { SeededRandom } from "../simulation/random.js";
import type { CogController } from "./cog-controller.js";
import { preferredTacticForCog } from "./fallback-tactic.js";

const directions: Direction[] = ["north", "south", "east", "west"];

export class WanderController implements CogController {
  private readonly random: SeededRandom;

  constructor(seed: number) {
    this.random = new SeededRandom(seed);
  }

  async decide(input: CogDecisionInput): Promise<CogAction> {
    if (input.allowedActions.length === 0) {
      throw new Error("WanderController requires at least one allowed action");
    }

    const roll = this.random.next();
    const canWait = input.allowedActions.includes("wait");
    const canMove = input.allowedActions.includes("move");
    const canChooseTactic = input.allowedActions.includes("chooseTactic");

    const wait = (): CogAction => ({ type: "wait", intent: "pausing to observe" });
    const chooseTactic = (): CogAction => ({
      type: "chooseTactic",
      tactic: preferredTacticForCog(input.observation.cog) ?? this.random.choice(["reason", "spin", "passion"]),
      intent: "pressing the debate",
    });
    const move = (): CogAction => ({
      type: "move",
      direction: this.random.choice(input.allowedDirections?.length ? input.allowedDirections : directions),
      intent: `wandering as ${input.observation.cog.color}`,
    });
    const venueMove = venueMoveTarget(input, this.random);

    if (canChooseTactic) {
      return chooseTactic();
    }

    if (roll < 0.1 && canWait) {
      return wait();
    }

    if (canMove) {
      return venueMove ?? move();
    }

    if (canWait) {
      return wait();
    }

    return wait();
  }
}

function venueMoveTarget(input: CogDecisionInput, random: SeededRandom): CogAction | undefined {
  const roomId = input.observation.cog.location?.roomId;
  const venue = input.observation.venue;
  if (!roomId || !venue) {
    return undefined;
  }

  const room = venue.rooms.find((candidate) => candidate.id === roomId);
  if (!room) {
    return undefined;
  }

  const candidates = input.allowedRoomIds?.length ? input.allowedRoomIds : room.neighborIds;
  if (candidates.length === 0) {
    return undefined;
  }

  const roomIdTarget = random.choice(candidates);
  return {
    type: "move",
    roomId: roomIdTarget,
    intent: "finding another conversation zone",
  };
}
