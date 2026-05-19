import type { Direction, Position } from "../../shared/types.js";

export function nextPosition(position: Position, direction: Direction): Position {
  switch (direction) {
    case "north":
      return { x: position.x, y: position.y - 1 };
    case "south":
      return { x: position.x, y: position.y + 1 };
    case "east":
      return { x: position.x + 1, y: position.y };
    case "west":
      return { x: position.x - 1, y: position.y };
  }
}
