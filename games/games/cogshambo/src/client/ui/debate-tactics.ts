import type { DebateChoice } from "../../shared/types";

export const DEBATE_TACTIC_ICONS: Record<DebateChoice | "pending", string> = {
  reason: "🧠",
  spin: "🌀",
  passion: "🔥",
  pending: "?",
};

export const DEBATE_TACTIC_LABELS: Record<DebateChoice | "pending", string> = {
  reason: "reason",
  spin: "spin",
  passion: "passion",
  pending: "choosing",
};

export const DEBATE_TACTIC_BEATS: Array<{ winner: DebateChoice; loser: DebateChoice }> = [
  { winner: "reason", loser: "spin" },
  { winner: "spin", loser: "passion" },
  { winner: "passion", loser: "reason" },
];
