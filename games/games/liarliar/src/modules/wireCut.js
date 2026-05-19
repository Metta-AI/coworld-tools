import { baseModule, hint, pick } from './core.js';

const COLORS = ['red', 'blue', 'yellow', 'white', 'black'];
const def = { name: 'Wire Cut', lethal: true, points: 20, timer: 150, refresh: true };

export const wireCutModule = {
  kind: 'wire_cut',
  order: 10,
  initial: true,
  def,
  metaManual: 'Get the safe color for this player and cut exactly that wire.',
  actionSchema: { type: 'operate', action: { wire: 'red|blue|yellow|white|black' } },
  create({ id, targetSlot, instance, now, rng }) {
    const safeColor = pick(COLORS, rng);
    return baseModule(def, 'wire_cut', id, targetSlot, instance, now, {
      wires: COLORS,
      solution: { wire: safeColor },
      hints: [hint(id, targetSlot, 'safe-color', `The safe wire color is ${safeColor}.`, { wire: safeColor })],
    });
  },
  operate(game, slot, module, action) {
    game.resolveSimple(slot, module, action?.wire === module.solution.wire, action);
  },
};
