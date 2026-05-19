export const RENDER_FRAMES_PER_SECOND = 60;
export const GAME_TICKS_PER_SECOND = 2;
export const SIMULATION_STEPS_PER_SECOND = GAME_TICKS_PER_SECOND;
export const SIMULATION_TICK_SECONDS = 1 / SIMULATION_STEPS_PER_SECOND;
export const SIMULATION_TICK_MS = 1000 / SIMULATION_STEPS_PER_SECOND;

const LEGACY_HALF_SECOND_TICK_SECONDS = 0.5;

export const VENUE_SIDE_TO_SIDE_MOVE_SECONDS = 10;
export const GOAL_SCORE_INTERVAL_TICKS = legacyHalfSecondTicksToSimulationTicks(100);

export type VenueMoveDimensions = {
  width: number;
  height: number;
};

export function venueMoveTilesPerSecond(dimensions: VenueMoveDimensions): number {
  return venueSideToSideDistance(dimensions) / VENUE_SIDE_TO_SIDE_MOVE_SECONDS;
}

export function venueMoveTilesPerTick(dimensions: VenueMoveDimensions): number {
  return venueMoveTilesPerSecond(dimensions) / SIMULATION_STEPS_PER_SECOND;
}

export function venueMoveDurationTicksForDistance(distance: number, dimensions: VenueMoveDimensions): number {
  return Math.max(1, Math.ceil(Math.max(0, distance) / venueMoveTilesPerTick(dimensions)));
}

export function secondsToSimulationTicks(seconds: number): number {
  return Math.max(0, Math.round(seconds * SIMULATION_STEPS_PER_SECOND));
}

export function simulationTicksToSeconds(ticks: number): number {
  return ticks / SIMULATION_STEPS_PER_SECOND;
}

export function simulationTicksToMs(ticks: number): number {
  return Math.round(simulationTicksToSeconds(ticks) * 1000);
}

export function legacyHalfSecondTicksToSimulationTicks(ticks: number): number {
  return secondsToSimulationTicks(ticks * LEGACY_HALF_SECOND_TICK_SECONDS);
}

export function simulationTicksToLegacyHalfSecondTicks(ticks: number): number {
  return ticks / legacyHalfSecondTicksToSimulationTicks(1);
}

function venueSideToSideDistance(dimensions: VenueMoveDimensions): number {
  return Math.max(1, dimensions.width, dimensions.height);
}
