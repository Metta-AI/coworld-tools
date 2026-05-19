import { baseModule } from './core.js';

const def = { name: 'Coup', lethal: false, points: 0, timer: null, refresh: false, utility: true };

export const coupModule = {
  kind: 'coup',
  order: 70,
  initial: true,
  def,
  metaManual: 'Toggle coup votes against direct communication neighbors. If any player receives two active coup votes, that player detonates.',
  actionSchema: { type: 'operate', action: { target: 1 } },
  create({ id, targetSlot, instance, now, options }) {
    const graph = options.communicationGraph ?? {};
    const targets = [...(graph[targetSlot] ?? [])].sort((a, b) => a - b);
    return baseModule(def, 'coup', id, targetSlot, instance, now, {
      targets,
      votes: [],
      solution: {},
      hints: [],
    });
  },
  operate(game, slot, module, action) {
    const target = Number(action?.target);
    if (!Number.isInteger(target) || !module.targets.includes(target) || game.bombs[target]?.detonated) return;
    if (module.votes.includes(target)) {
      module.votes = module.votes.filter((candidate) => candidate !== target);
      game.coupVotes[target].delete(slot);
      game.record('coup_removed', { slot, target, moduleId: module.id, count: game.coupVotes[target].size });
    } else {
      module.votes = [...module.votes, target].sort((a, b) => a - b);
      game.coupVotes[target].add(slot);
      const coupers = [...game.coupVotes[target]].sort((a, b) => a - b);
      game.record('coup_added', { slot, target, moduleId: module.id, count: coupers.length, coupers });
      if (coupers.length >= 2) {
        for (const couper of coupers) game.scores[couper] -= 5;
        game.detonate(target, 'couped', { coupers, coupCost: 5 });
      }
    }
    game.broadcast();
  },
  onDetonation(game, slot) {
    for (const targetVotes of game.coupVotes) targetVotes.delete(slot);
    for (const bomb of game.bombs) {
      for (const module of bomb.modules) {
        if (module.kind === 'coup') module.votes = bomb.slot === slot ? [] : module.votes.filter((target) => target !== slot);
      }
    }
  },
};
