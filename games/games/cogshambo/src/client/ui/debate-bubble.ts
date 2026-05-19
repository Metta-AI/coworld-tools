import type { Cog, DebateChoice, Color, DebateLogEntry, WorldEvent } from "../../shared/types";
import { simulationTicksToMs } from "../../shared/timing";
import { DEBATE_TACTIC_ICONS, DEBATE_TACTIC_LABELS } from "./debate-tactics";
import { escapeHtml } from "./html";

type DebateCog = Pick<Cog, "id" | "name" | "color" | "certainty" | "defensiveTrait" | "activeTrait">;
type DebatePhase = "prep" | "choices" | "result";
type DebateSide = "first" | "second";
type CertaintyPosition = "top" | "bottom";
const CERTAINTY_BARS: Array<{ color: Color; position: CertaintyPosition }> = [
  { color: "red", position: "top" },
  { color: "blue", position: "bottom" },
];
const MIN_VISIBLE_CERTAINTY_PERCENT = 4;
const LOCKED_CERTAINTY_FLOOR = 1;

export function renderDebateBubbleContent(
  first: DebateCog,
  second: DebateCog,
  events: WorldEvent[],
  currentTick?: number,
  debateLog: DebateLogEntry[] = [],
  conversionThreshold = 100,
): string {
  const detail = latestDebateDetail(first.id, second.id, events, currentTick);
  const phase = debatePhase(detail, currentTick);
  const showActions = phase === "choices" || phase === "result";
  const showResult = phase === "result";
  const firstAction = showActions
    ? detail?.actions.find((action) => action.cogId === first.id)?.action ?? "pending"
    : "pending";
  const secondAction = showActions
    ? detail?.actions.find((action) => action.cogId === second.id)?.action ?? "pending"
    : "pending";
  const winnerSide = winningSide(first, second, detail);
  const showFill = showResult && detail?.outcome !== "draw" && detail?.winnerColor && winnerSide;
  const resultStyle = showResult ? debateResultAgeStyle(detail, currentTick) : "";
  const resultFill = showFill
    ? `<span class="debate-result-fill debate-result-fill-${escapeHtml(detail.winnerColor)} debate-result-fill-from-${winnerSide}"${resultStyle} aria-hidden="true"></span>`
    : "";
  const outcome = showResult && detail ? detail.outcome : "pending";

  return [
    resultFill,
    renderCertaintyBars(first, second, detail, phase, currentTick, debateLog, conversionThreshold),
    `<span class="debate-phase-marker" data-debate-phase="${phase}" data-debate-outcome="${outcome}" aria-hidden="true"></span>`,
    renderMatchupNames(first, second),
    renderActionCircle(
      first,
      firstAction,
      "first",
      showResult && isWinningCog(first, detail),
      showResult && isLosingCog(first, detail),
      showResult && detail?.outcome === "draw",
      showResult,
      resultStyle,
    ),
    renderActionCircle(
      second,
      secondAction,
      "second",
      showResult && isWinningCog(second, detail),
      showResult && isLosingCog(second, detail),
      showResult && detail?.outcome === "draw",
      showResult,
      resultStyle,
    ),
  ].join("");
}

function renderMatchupNames(first: DebateCog, second: DebateCog): string {
  return [
    `<span class="debate-matchup" aria-hidden="true">`,
    renderMatchupName(first),
    `<span class="debate-matchup-vs">vs</span>`,
    renderMatchupName(second),
    `</span>`,
  ].join("");
}

function renderMatchupName(cog: DebateCog): string {
  const zealotBadge = hasZealotTrait(cog)
    ? `<span class="debate-zealot-badge" aria-label="${escapeHtml(`${cog.name} is a Zealot and cannot convert`)}"><span class="debate-zealot-badge-lock" aria-hidden="true"></span>ZEALOT</span>`
    : "";
  return `
    <span class="debate-matchup-name-wrap">
      <span class="debate-matchup-name debate-matchup-name-${cog.color}">${escapeHtml(cog.name)}</span>
      ${zealotBadge}
    </span>
  `;
}

function renderCertaintyBars(
  first: DebateCog,
  second: DebateCog,
  detail: WorldEvent["debate"] | undefined,
  phase: DebatePhase,
  currentTick: number | undefined,
  debateLog: DebateLogEntry[],
  conversionThreshold: number,
): string {
  const debateLogEntry = detail ? latestDebateLogEntry(detail, debateLog) : undefined;
  const resultAgeMs = phase === "result" ? debateResultAgeMs(detail, currentTick) : 0;
  return CERTAINTY_BARS.map(({ color, position }) =>
    renderCertaintyBar(color, position, first, second, phase, debateLogEntry, resultAgeMs, conversionThreshold),
  ).join("");
}

function renderCertaintyBar(
  color: Color,
  position: CertaintyPosition,
  first: DebateCog,
  second: DebateCog,
  phase: DebatePhase,
  debateLogEntry: DebateLogEntry | undefined,
  resultAgeMs: number,
  conversionThreshold: number,
): string {
  const cog = first.color === color ? first : second.color === color ? second : undefined;
  if (!cog) {
    return "";
  }

  const side: DebateSide = cog.id === first.id ? "first" : "second";
  const change = certaintyChangeForCog(cog.id, debateLogEntry);
  const beforeCertainty = certaintyPercent(change?.certaintyBefore ?? cog.certainty, conversionThreshold);
  const afterCertainty = certaintyPercent(change?.certaintyAfter ?? cog.certainty, conversionThreshold);
  const certainty = phase === "choices" && change ? beforeCertainty : afterCertainty;
  const rawCertainty = phase === "choices" && change ? change.certaintyBefore : change?.certaintyAfter ?? cog.certainty;
  const certaintyFill = certaintyFillPercent(certainty);
  const beforeCertaintyFill = certaintyFillPercent(beforeCertainty);
  const isLockedFloor = hasZealotTrait(cog) && rawCertainty <= LOCKED_CERTAINTY_FLOOR;
  const lossAmount = phase === "result" && change?.certaintyDelta && change.certaintyDelta < 0
    ? Math.max(0, beforeCertaintyFill - certaintyFill)
    : 0;
  const lossStyle =
    lossAmount > 0
      ? ` --debate-certainty-before: ${beforeCertainty}%; --debate-certainty-fill-before: ${beforeCertaintyFill}%; --debate-certainty-loss: ${lossAmount}%; --debate-result-age-ms: ${negativeMs(resultAgeMs)};`
      : "";
  const lossLayer =
    lossAmount > 0
      ? `<span class="debate-certainty-loss" aria-hidden="true"></span>`
      : "";
  const lockLayer = isLockedFloor ? `<span class="debate-certainty-lock" aria-hidden="true"></span>` : "";
  const damageClass = lossAmount > 0 ? " debate-certainty-damaged" : "";
  const lockedClass = isLockedFloor ? " debate-certainty-locked" : "";
  const lockedData = isLockedFloor ? ` data-debate-certainty-locked="true"` : "";
  const lockedLabel = isLockedFloor ? ", Zealot conversion locked" : "";

  return [
    `<span class="debate-certainty-track debate-certainty-${position} debate-certainty-${color} debate-certainty-from-${side}${damageClass}${lockedClass}"`,
    ` data-debate-certainty="${color}"`,
    ` data-debate-certainty-side="${side}"`,
    lockedData,
    ` style="--debate-certainty: ${certainty}%; --debate-certainty-fill: ${certaintyFill}%;${lossStyle}"`,
    ` aria-label="${escapeHtml(`${color} certainty ${certainty}%${lockedLabel}`)}">`,
    `<span class="debate-certainty-fill" aria-hidden="true"></span>`,
    lossLayer,
    lockLayer,
    `<span class="debate-certainty-label" aria-hidden="true">${certainty}</span>`,
    "</span>",
  ].join("");
}

function hasZealotTrait(cog: DebateCog): boolean {
  return cog.defensiveTrait === "zealot" || cog.activeTrait === "zealot";
}

function certaintyPercent(certainty: number, conversionThreshold: number): number {
  const threshold = Math.max(1, conversionThreshold);
  return Math.round(Math.min(100, Math.max(0, (certainty / threshold) * 100)));
}

function certaintyFillPercent(certaintyPercentValue: number): number {
  return certaintyPercentValue > 0 ? Math.max(MIN_VISIBLE_CERTAINTY_PERCENT, certaintyPercentValue) : 0;
}

function certaintyChangeForCog(cogId: string, debateLogEntry: DebateLogEntry | undefined): DebateLogEntry["changes"][number] | undefined {
  return debateLogEntry?.changes.find((change) => change.cogId === cogId);
}

function latestDebateLogEntry(
  detail: NonNullable<WorldEvent["debate"]>,
  debateLog: DebateLogEntry[],
): DebateLogEntry | undefined {
  for (let index = debateLog.length - 1; index >= 0; index -= 1) {
    const entry = debateLog[index];
    if (
      !entry ||
      entry.tick !== detail.choicesRevealedAtTick ||
      entry.round !== detail.round ||
      entry.actions.length !== detail.actions.length
    ) {
      continue;
    }

    const matchesActions = detail.actions.every((action) =>
      entry.actions.some((loggedAction) => loggedAction.cogId === action.cogId && loggedAction.tactic === action.action),
    );
    if (matchesActions) {
      return entry;
    }
  }

  return undefined;
}

function latestDebateDetail(
  firstCogId: string,
  secondCogId: string,
  events: WorldEvent[],
  currentTick?: number,
): WorldEvent["debate"] | undefined {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const detail = events[index]?.debate;
    if (!detail || (currentTick !== undefined && currentTick >= detail.expiresAtTick)) {
      continue;
    }

    const cogIds = new Set(detail.actions.map((action) => action.cogId));
    if (cogIds.has(firstCogId) && cogIds.has(secondCogId)) {
      return detail;
    }
  }

  return undefined;
}

function debatePhase(detail: WorldEvent["debate"] | undefined, currentTick?: number): DebatePhase {
  if (!detail) {
    return "prep";
  }

  if (currentTick === undefined) {
    return "result";
  }

  const choicesRevealedAtTick = detail.choicesRevealedAtTick ?? detail.expiresAtTick;
  const resultRevealedAtTick = detail.resultRevealedAtTick ?? choicesRevealedAtTick;

  if (currentTick < choicesRevealedAtTick || currentTick >= detail.expiresAtTick) {
    return "prep";
  }

  return currentTick < resultRevealedAtTick ? "choices" : "result";
}

function isWinningCog(cog: DebateCog, detail: WorldEvent["debate"] | undefined): boolean {
  if (!detail) {
    return false;
  }

  return detail.winnerCogId ? detail.winnerCogId === cog.id : detail.winnerColor === cog.color;
}

function isLosingCog(cog: DebateCog, detail: WorldEvent["debate"] | undefined): boolean {
  return Boolean(
    detail && detail.outcome !== "draw" && (detail.winnerCogId || detail.winnerColor) && !isWinningCog(cog, detail),
  );
}

function winningSide(
  first: DebateCog,
  second: DebateCog,
  detail: WorldEvent["debate"] | undefined,
): DebateSide | undefined {
  if (!detail || detail.outcome === "draw") {
    return undefined;
  }

  if (detail.winnerCogId === first.id || (!detail.winnerCogId && detail.winnerColor === first.color)) {
    return "first";
  }

  if (detail.winnerCogId === second.id || (!detail.winnerCogId && detail.winnerColor === second.color)) {
    return "second";
  }

  return undefined;
}

function debateResultAgeStyle(detail: WorldEvent["debate"] | undefined, currentTick?: number): string {
  return ` style="--debate-result-age-ms: ${negativeMs(debateResultAgeMs(detail, currentTick))};"`;
}

function debateResultAgeMs(detail: WorldEvent["debate"] | undefined, currentTick?: number): number {
  if (!detail || currentTick === undefined) {
    return 0;
  }

  const resultRevealedAtTick = detail.resultRevealedAtTick ?? detail.choicesRevealedAtTick ?? detail.expiresAtTick;
  return simulationTicksToMs(Math.max(0, currentTick - resultRevealedAtTick));
}

function negativeMs(ms: number): string {
  return ms === 0 ? "0ms" : `-${ms}ms`;
}

function renderActionCircle(
  cog: DebateCog,
  action: DebateChoice | "pending",
  side: DebateSide,
  isWinner: boolean,
  isLoser: boolean,
  isDraw: boolean,
  isResultPhase: boolean,
  resultStyle: string,
): string {
  const stateClass = action === "pending" ? "debate-action-pending-choice" : "debate-action-resolved";
  const resultClass = isResultPhase && action !== "pending" ? " debate-action-result" : "";
  const winnerClass = isWinner ? " debate-action-winner" : "";
  const loserClass = isLoser ? " debate-action-loser" : "";
  const drawClass = isDraw ? " debate-action-draw" : "";
  const winnerData = isWinner ? "true" : "false";
  const resultLabel = isWinner ? ", winner" : "";
  const placeholder = action === "pending" ? `<span class="debate-action-placeholder" aria-hidden="true">?</span>` : "";

  return [
    `<span class="debate-action-circle debate-action-${cog.color} debate-action-side-${side} ${stateClass}${resultClass}${winnerClass}${loserClass}${drawClass}"`,
    resultStyle,
    ` data-debate-side="${side}"`,
    ` data-debate-action="${action}"`,
    ` data-debate-winner="${winnerData}"`,
    ` title="${escapeHtml(`${cog.name}: ${DEBATE_TACTIC_LABELS[action]}${resultLabel}`)}"`,
    ` aria-label="${escapeHtml(`${cog.name}: ${DEBATE_TACTIC_LABELS[action]}${resultLabel}`)}">`,
    placeholder,
    `<span class="debate-action-symbol" aria-hidden="true">${DEBATE_TACTIC_ICONS[action]}</span>`,
    "</span>",
  ].join("");
}
