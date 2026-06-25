import { baseModule, hint, pick } from './core.js';

const WORDS = ['alpha', 'bravo', 'cobalt', 'delta', 'ember', 'fable'];
const def = { name: 'Two Truths and a Lie', lethal: true, points: 45, timer: null, refresh: false };

export const twoTruthsLieModule = {
  kind: 'two_truths_lie',
  order: 50,
  initial: true,
  def,
  metaManual: 'Collect the three claims for this player. Exactly one claim is false. Submit the false claim number.',
  actionSchema: { type: 'operate', action: { falseClaim: 1 } },
  create({ id, targetSlot, instance, now, rng }) {
    const answer = pick(WORDS, rng);
    const falseAnswer = pick(WORDS.filter((word) => word !== answer), rng);
    const falseIndex = Math.floor(rng() * 3);
    const claims = [0, 1, 2].map((index) =>
      index === falseIndex ? `The safe word is ${falseAnswer}.` : `The safe word is ${answer}.`,
    );
    return baseModule(def, 'two_truths_lie', id, targetSlot, instance, now, {
      claims,
      solution: { falseClaim: falseIndex + 1, answer },
      hints: claims.map((text, index) =>
        hint(id, targetSlot, `claim-${index + 1}`, `Claim ${index + 1}: ${text}`, {
          claim: index + 1,
          truth: index !== falseIndex,
        }),
      ),
    });
  },
  operate(game, slot, module, action) {
    game.resolveSimple(slot, module, Number(action?.falseClaim) === module.solution.falseClaim, action);
  },
};
