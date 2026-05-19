import { coupModule } from './coup.js';
import { keypadCalibrationModule } from './keypadCalibration.js';
import { rpsDuelModule } from './rpsDuel.js';
import { switchPanelModule } from './switchPanel.js';
import { telephoneRelayModule } from './telephoneRelay.js';
import { twoTruthsLieModule } from './twoTruthsLie.js';
import { wireCutModule } from './wireCut.js';

export const MODULE_REGISTRY = Object.freeze(
  [wireCutModule, keypadCalibrationModule, switchPanelModule, rpsDuelModule, twoTruthsLieModule, telephoneRelayModule, coupModule].sort(
    (a, b) => a.order - b.order || a.kind.localeCompare(b.kind),
  ),
);

export const MODULES = Object.freeze(Object.fromEntries(MODULE_REGISTRY.map((entry) => [entry.kind, entry])));
export const MODULE_DEFS = Object.freeze(Object.fromEntries(MODULE_REGISTRY.map((entry) => [entry.kind, entry.def])));

export function getModule(kind) {
  return MODULES[kind] ?? null;
}

export function initialModuleEntries() {
  return MODULE_REGISTRY.filter((entry) => entry.initial !== false && !entry.paired);
}

export function pairedModuleEntries() {
  return MODULE_REGISTRY.filter((entry) => entry.paired);
}

export function moduleOrder(kind) {
  return getModule(kind)?.order ?? 999;
}
