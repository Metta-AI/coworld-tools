import type { CogRoomHistoryEntry } from "./types.js";

export function isValidCogRoomHistoryEntry(entry: CogRoomHistoryEntry): boolean {
  return (
    typeof entry.roomId === "string" &&
    entry.roomId.length > 0 &&
    Number.isFinite(entry.enteredTick) &&
    entry.enteredTick >= 0 &&
    (entry.leftTick === undefined || (Number.isFinite(entry.leftTick) && entry.leftTick >= entry.enteredTick))
  );
}
