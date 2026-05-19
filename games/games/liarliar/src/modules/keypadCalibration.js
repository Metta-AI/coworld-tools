import { baseModule, hint, pick } from './core.js';

const KEYPAD = ['star', 'moon', 'bolt', 'wave', 'ring', 'cross'];
const KEYPAD_GROUPS = [
  ['star', 'moon'],
  ['bolt', 'wave'],
  ['ring', 'cross'],
];
const def = { name: 'Keypad Calibration', lethal: false, points: 10, timer: 150, refresh: true };

export const keypadCalibrationModule = {
  kind: 'keypad_calibration',
  order: 20,
  initial: true,
  def,
  metaManual: 'Combine the symbol pair and position for this player. Wrong entries reset only this module and cost points.',
  actionSchema: { type: 'operate', action: { answer: 'star|moon|bolt|wave|ring|cross' } },
  create({ id, targetSlot, instance, now, rng }) {
    const group = pick(KEYPAD_GROUPS, rng);
    const position = rng() > 0.5 ? 1 : 0;
    const answer = group[position];
    return baseModule(def, 'keypad_calibration', id, targetSlot, instance, now, {
      symbols: KEYPAD,
      solution: { answer },
      hints: [
        hint(id, targetSlot, 'symbol-pair', `The calibration symbol is either ${group[0]} or ${group[1]}.`, { symbols: group }),
        hint(id, targetSlot, 'symbol-position', `Use the ${position === 0 ? 'first' : 'second'} symbol from the calibration pair.`, {
          position,
        }),
      ],
    });
  },
  operate(game, slot, module, action) {
    game.resolveSimple(slot, module, action?.answer === module.solution.answer, action);
  },
};
