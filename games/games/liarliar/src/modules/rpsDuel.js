import { baseModule, hint } from './core.js';

const RPS = ['rock', 'paper', 'scissors'];
const def = { name: 'RPS Duel', lethal: true, points: 30, timer: null, refresh: false };

export const rpsDuelModule = {
  kind: 'rps_duel',
  order: 40,
  initial: false,
  paired: true,
  def,
  metaManual:
    'Pick rock, paper, or scissors. Choices lock in and resolve at round end. Draws are safe. Losing is lethal unless the opponent is already detonated.',
  actionSchema: { type: 'operate', action: { choice: 'rock|paper|scissors' } },
  create({ id, targetSlot, instance, now, options }) {
    return createRpsModule(id, targetSlot, options.opponentSlot, instance, now);
  },
  createInitial({ players, now }) {
    const modules = [];
    for (const [a, b] of rpsPairs(players.length)) {
      modules.push({ slot: a, module: createRpsModule(`rps_duel:${a}:1`, a, b, 1, now) });
      modules.push({ slot: b, module: createRpsModule(`rps_duel:${b}:1`, b, a, 1, now) });
    }
    return modules;
  },
  operate(game, slot, module, action) {
    const choice = String(action?.choice ?? '');
    if (!RPS.includes(choice) || module.choice) return;
    game.rpsChoices.set(slot, choice);
    module.choice = choice;
    game.record('rps_choice', { slot, moduleId: module.id });
    game.broadcast();
  },
  addressed(module) {
    return Boolean(module.choice);
  },
  detonatesAtFinalization(module) {
    return !module.choice;
  },
  finalize(game) {
    for (const [a, b] of rpsPairs(game.players.length)) resolveRpsPair(game, a, b);
  },
};

function createRpsModule(id, targetSlot, opponentSlot, instance, now) {
  return baseModule(def, 'rps_duel', id, targetSlot, instance, now, {
    opponentSlot,
    choices: RPS,
    solution: {},
    hints: [
      hint(id, targetSlot, 'opponent', `Your RPS duel is against Player ${opponentSlot + 1}. Draws are safe.`, {
        opponentSlot,
      }),
    ],
  });
}

export function rpsWinner(a, b) {
  if (a === b) return 0;
  if ((a === 'rock' && b === 'scissors') || (a === 'scissors' && b === 'paper') || (a === 'paper' && b === 'rock')) {
    return 1;
  }
  return -1;
}

export function rpsPairs(count) {
  const pairs = [];
  for (let i = 0; i < Math.floor(count / 2); i += 1) pairs.push([i, count - 1 - i]);
  return pairs;
}

function resolveRpsPair(game, a, b) {
  const bombA = game.bombs[a];
  const bombB = game.bombs[b];
  const moduleA = bombA?.modules.find((module) => module.kind === 'rps_duel' && module.opponentSlot === b && module.status === 'active');
  const moduleB = bombB?.modules.find((module) => module.kind === 'rps_duel' && module.opponentSlot === a && module.status === 'active');
  if (bombA?.detonated && !bombB?.detonated && moduleB) return autopassRps(game, b, moduleB, a);
  if (bombB?.detonated && !bombA?.detonated && moduleA) return autopassRps(game, a, moduleA, b);
  if (!moduleA || !moduleB) return;
  const choiceA = game.rpsChoices.get(a);
  const choiceB = game.rpsChoices.get(b);
  if (!choiceA || !choiceB) return;
  const outcome = rpsWinner(choiceA, choiceB);
  moduleA.status = 'solved';
  moduleB.status = 'solved';
  if (outcome === 0) {
    moduleA.rpsResult = `${title(choiceA)} ties ${title(choiceB)}. Draw.`;
    moduleB.rpsResult = `${title(choiceB)} ties ${title(choiceA)}. Draw.`;
    game.scores[a] += 10;
    game.scores[b] += 10;
    game.record('rps_draw', { a, b, choiceA, choiceB, points: 10 });
  } else if (outcome === 1) {
    moduleA.rpsResult = `${title(choiceA)} beats ${title(choiceB)}. You win.`;
    moduleB.rpsResult = `${title(choiceB)} loses to ${title(choiceA)}. You explode.`;
    game.scores[a] += game.pointsFor(moduleA);
    game.record('rps_win', { winner: a, loser: b, choiceA, choiceB, points: game.pointsFor(moduleA) });
    game.detonate(b, 'lost rps_duel', { moduleId: moduleB.id });
  } else {
    moduleA.rpsResult = `${title(choiceA)} loses to ${title(choiceB)}. You explode.`;
    moduleB.rpsResult = `${title(choiceB)} beats ${title(choiceA)}. You win.`;
    game.scores[b] += game.pointsFor(moduleB);
    game.record('rps_win', { winner: b, loser: a, choiceA, choiceB, points: game.pointsFor(moduleB) });
    game.detonate(a, 'lost rps_duel', { moduleId: moduleA.id });
  }
}

function autopassRps(game, slot, module, opponentSlot) {
  module.status = 'solved';
  module.rpsResult = module.choice
    ? `${title(module.choice)} beats NULL. Player ${opponentSlot + 1} exploded; you win by default.`
    : `Player ${opponentSlot + 1} exploded; you win by default.`;
  game.scores[slot] += 15;
  game.record('rps_autopass', { slot, opponentSlot, moduleId: module.id, points: 15 });
}

function title(value) {
  return String(value).slice(0, 1).toUpperCase() + String(value).slice(1);
}
