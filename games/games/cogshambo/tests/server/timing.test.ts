import { describe, expect, it } from "vitest";

import { normalizeGameConfig } from "../../src/shared/rules.js";
import {
  GAME_TICKS_PER_SECOND,
  RENDER_FRAMES_PER_SECOND,
  SIMULATION_STEPS_PER_SECOND,
  SIMULATION_TICK_MS,
  GOAL_SCORE_INTERVAL_TICKS,
  VENUE_SIDE_TO_SIDE_MOVE_SECONDS,
  legacyHalfSecondTicksToSimulationTicks,
  secondsToSimulationTicks,
  simulationTicksToLegacyHalfSecondTicks,
  simulationTicksToSeconds,
  venueMoveDurationTicksForDistance,
  venueMoveTilesPerSecond,
  venueMoveTilesPerTick,
} from "../../src/shared/timing.js";

describe("simulation timing", () => {
  it("runs the game clock at 2 ticks per second while rendering targets 60 fps", () => {
    expect(GAME_TICKS_PER_SECOND).toBe(2);
    expect(SIMULATION_STEPS_PER_SECOND).toBe(GAME_TICKS_PER_SECOND);
    expect(SIMULATION_TICK_MS).toBeCloseTo(500);
    expect(RENDER_FRAMES_PER_SECOND).toBe(60);
  });

  it("computes venue movement speed from a ten-second side-to-side crossing", () => {
    expect(VENUE_SIDE_TO_SIDE_MOVE_SECONDS).toBe(10);
    expect(venueMoveTilesPerSecond({ width: 50, height: 28 })).toBe(5);
    expect(venueMoveTilesPerTick({ width: 50, height: 28 })).toBe(2.5);
    expect(venueMoveDurationTicksForDistance(50, { width: 50, height: 28 })).toBe(secondsToSimulationTicks(10));
    expect(venueMoveDurationTicksForDistance(25, { width: 50, height: 28 })).toBe(secondsToSimulationTicks(5));
  });

  it("converts old half-second timing constants to the same wall-clock duration", () => {
    expect(legacyHalfSecondTicksToSimulationTicks(2)).toBe(secondsToSimulationTicks(1));
    expect(legacyHalfSecondTicksToSimulationTicks(120)).toBe(secondsToSimulationTicks(60));
    expect(simulationTicksToSeconds(legacyHalfSecondTicksToSimulationTicks(180))).toBe(90);
    expect(GOAL_SCORE_INTERVAL_TICKS).toBe(secondsToSimulationTicks(50));
    expect(simulationTicksToLegacyHalfSecondTicks(GOAL_SCORE_INTERVAL_TICKS)).toBe(100);
  });

  it("migrates saved legacy default timing config to 2-tps ticks", () => {
    const config = normalizeGameConfig({
      debatePrepTicks: 2,
      debateChoiceRevealTicks: 2,
      debateResultTicks: 6,
      debateCooldownTicks: 600,
      roomMoveCooldownTicks: 120,
    });

    expect(config.debatePrepTicks).toBe(secondsToSimulationTicks(1));
    expect(config.debateChoiceRevealTicks).toBe(secondsToSimulationTicks(1));
    expect(config.debateResultTicks).toBe(secondsToSimulationTicks(3));
    expect(config.debateCooldownTicks).toBe(secondsToSimulationTicks(5 * 60));
    expect(config.roomMoveCooldownTicks).toBe(secondsToSimulationTicks(60));
  });

  it("migrates saved high-frequency default timing config to 2-tps ticks", () => {
    const config = normalizeGameConfig({
      debatePrepTicks: 60,
      debateChoiceRevealTicks: 60,
      debateResultTicks: 180,
      debateCooldownTicks: 18000,
      roomMoveCooldownTicks: 3600,
    });

    expect(config.debatePrepTicks).toBe(secondsToSimulationTicks(1));
    expect(config.debateChoiceRevealTicks).toBe(secondsToSimulationTicks(1));
    expect(config.debateResultTicks).toBe(secondsToSimulationTicks(3));
    expect(config.debateCooldownTicks).toBe(secondsToSimulationTicks(5 * 60));
    expect(config.roomMoveCooldownTicks).toBe(secondsToSimulationTicks(60));
  });
});
