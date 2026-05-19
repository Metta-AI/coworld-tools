import { makeRng } from './modules/core.js';
import {
  MODULE_DEFS,
  MODULE_REGISTRY,
  MODULES,
  getModule,
  initialModuleEntries,
  moduleOrder,
  pairedModuleEntries,
} from './modules/registry.js';

export { MODULE_DEFS, MODULE_REGISTRY, MODULES, getModule, moduleOrder };
export { hint, makeRng, publicModule } from './modules/core.js';
export { rpsPairs, rpsWinner } from './modules/rpsDuel.js';
export { telephoneTransform } from './modules/telephoneRelay.js';

export function metaManuals() {
  return Object.fromEntries(MODULE_REGISTRY.map((entry) => [entry.kind, entry.metaManual]));
}

export function createInitialModules(players, now, seed = 'liarliar', communicationGraph = {}) {
  const bombs = players.map((player, slot) => ({
    slot,
    playerName: player.name,
    detonated: false,
    modules: [],
  }));
  const allHints = [];
  const options = { playerCount: players.length, communicationGraph };
  for (const bomb of bombs) {
    for (const entry of initialModuleEntries()) {
      const module = createModule(entry.kind, bomb.slot, 1, now, seed, options);
      bombs[bomb.slot].modules.push(module);
      allHints.push(...module.hints);
    }
  }
  for (const entry of pairedModuleEntries()) {
    for (const { slot, module } of entry.createInitial({ players, now, seed, options })) {
      bombs[slot].modules.push(module);
      allHints.push(...module.hints);
    }
  }
  return { bombs, allHints };
}

export function createModule(kind, targetSlot, instance, now, seed = 'liarliar', options = {}) {
  const entry = getModule(kind);
  if (!entry) throw new Error(`Unknown module kind: ${kind}`);
  const id = `${kind}:${targetSlot}:${instance}`;
  const rng = makeRng(`${seed}:${id}`);
  return entry.create({ id, targetSlot, instance, now, seed, rng, options });
}
