import type { ServerStatus, SimulationMode } from "../../shared/types.js";

export type SimulationCommand = "play" | "pause" | "step" | "toggleDisco";

export type SimulationControlStatus = Pick<ServerStatus, "discoMode" | "simulationMode" | "stepRequested">;

export type SimulationControls = {
  mode: () => SimulationMode;
  discoMode: () => boolean;
  isPlaying: () => boolean;
  pause: () => void;
  play: () => void;
  step: () => void;
  toggleDisco: () => void;
  consumeStep: () => boolean;
  statusPatch: () => SimulationControlStatus;
  onChange: (listener: () => void) => () => void;
};

export function createSimulationControls(initialMode: SimulationMode = "playing"): SimulationControls {
  let simulationMode = initialMode;
  let discoMode = false;
  let pendingSteps = 0;
  const listeners = new Set<() => void>();

  const notify = (): void => {
    Array.from(listeners).forEach((listener) => listener());
  };

  return {
    mode: () => simulationMode,
    discoMode: () => discoMode,
    isPlaying: () => simulationMode === "playing",
    pause: () => {
      simulationMode = "paused";
      notify();
    },
    play: () => {
      simulationMode = "playing";
      pendingSteps = 0;
      notify();
    },
    step: () => {
      simulationMode = "paused";
      pendingSteps += 1;
      notify();
    },
    toggleDisco: () => {
      discoMode = !discoMode;
      notify();
    },
    consumeStep: () => {
      if (simulationMode === "playing") {
        return true;
      }

      if (pendingSteps > 0) {
        pendingSteps -= 1;
        return true;
      }

      return false;
    },
    statusPatch: () => ({
      discoMode,
      simulationMode,
      stepRequested: pendingSteps > 0,
    }),
    onChange: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
