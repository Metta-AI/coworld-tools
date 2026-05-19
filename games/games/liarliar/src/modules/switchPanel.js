import { baseModule, hint } from './core.js';

const def = { name: 'Switch Panel', lethal: true, points: 35, timer: null, refresh: false };

export const switchPanelModule = {
  kind: 'switch_panel',
  order: 30,
  initial: true,
  def,
  metaManual: 'Combine the switch hints for this player and submit three on/off values.',
  actionSchema: { type: 'operate', action: { settings: [true, false, true] } },
  create({ id, targetSlot, instance, now, rng }) {
    const settings = [rng() > 0.5, rng() > 0.5, rng() > 0.5];
    return baseModule(def, 'switch_panel', id, targetSlot, instance, now, {
      switches: 3,
      solution: { settings },
      hints: [
        hint(id, targetSlot, 'left', `Switch 1 is ${settings[0] ? 'ON' : 'OFF'}.`, { index: 0, value: settings[0] }),
        hint(id, targetSlot, 'middle-right', `Switches 2 and 3 are ${settings[1] ? 'ON' : 'OFF'} then ${settings[2] ? 'ON' : 'OFF'}.`, {
          values: [settings[1], settings[2]],
        }),
      ],
    });
  },
  operate(game, slot, module, action) {
    const settings = Array.isArray(action?.settings) ? action.settings.map(Boolean) : [];
    game.resolveSimple(slot, module, sameArray(settings, module.solution.settings), action);
  },
};

function sameArray(a, b) {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}
