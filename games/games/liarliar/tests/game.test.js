import test from 'node:test';
import assert from 'node:assert/strict';
import { LiarLiarGame } from '../src/game.js';
import { defaultPlayers } from '../src/graph.js';

function config() {
  return {
    seed: 'test',
    duration_seconds: 300,
    tick_rate: 1,
    player_connect_timeout_seconds: 60,
    hint_redundancy: 1.3,
    tokens: Array.from({ length: 6 }, (_, slot) => `t${slot}`),
    players: defaultPlayers(6),
    communication_graph: { type: 'circle', radius: 2 },
    hint_graph: { type: 'circle', radius: 2 },
  };
}

function solveLethalNonRps(game, slots) {
  for (const slot of slots) {
    for (const module of game.bombs[slot].modules) {
      if (module.lethal && module.kind !== 'rps_duel') module.status = 'solved';
    }
  }
}

test('player view hides solution metadata from hints and modules', () => {
  const game = new LiarLiarGame(config());
  game.start();
  const view = game.viewFor(0);
  assert.equal(view.bomb.modules.some((module) => 'solution' in module), false);
  assert.equal(view.hints.some((hint) => 'data' in hint), false);
  clearInterval(game.interval);
});

test('lobby hides bomb and hints until ready start', () => {
  const game = new LiarLiarGame(config());
  const view = game.viewFor(0);
  assert.equal(view.phase, 'lobby');
  assert.equal(view.bomb, null);
  assert.deepEqual(view.hints, []);
  game.setReady(0, true);
  assert.equal(game.readySlots.has(0), true);
});

test('wrong lethal operation detonates and recovers held hints to relevant players', () => {
  const game = new LiarLiarGame(config());
  game.start();
  const wire = game.bombs[0].modules.find((module) => module.kind === 'wire_cut');
  const wrong = wire.wires.find((wireColor) => wireColor !== wire.solution.wire);
  game.operate(0, wire.id, { wire: wrong });
  assert.equal(game.bombs[0].detonated, true);
  assert(game.recoveredHints.some((hints, slot) => slot !== 0 && hints.length > 0));
  clearInterval(game.interval);
});

test('detonated players cannot chat and their panel exposes recovered hints for you', () => {
  const game = new LiarLiarGame(config());
  try {
    game.start();
    game.heldHints[1].push({
      id: 'hint:test:for-p1',
      targetSlot: 0,
      targetLabel: 'Player 1',
      moduleId: 'wire_cut:0:1',
      moduleKind: 'wire_cut',
      moduleInstance: 1,
      label: 'For Player 1 / wire_cut / instance 1',
      text: 'The safe wire color is blue.',
      data: { wire: 'blue' },
    });

    game.detonate(1, 'test detonation');
    game.chat(1, 0, 'dead player message');
    game.chat(0, 1, 'message to dead player');

    assert.equal(game.directMessages.length, 0);
    const neighborState = game.viewFor(0).communication.neighborStates.find((state) => state.slot === 1);
    assert.equal(neighborState.detonated, true);
    assert(neighborState.revealedHintsForYou.some((hint) => hint.text === 'The safe wire color is blue.'));
  } finally {
    clearInterval(game.interval);
  }
});

test('non-lethal keypad failure refreshes without detonation', () => {
  const game = new LiarLiarGame(config());
  game.start();
  const keypad = game.bombs[0].modules.find((module) => module.kind === 'keypad_calibration');
  game.operate(0, keypad.id, { answer: 'definitely-wrong' });
  assert.equal(game.bombs[0].detonated, false);
  assert.equal(keypad.status, 'expired');
  assert(game.bombs[0].modules.some((module) => module.kind === 'keypad_calibration' && module.instance === 2));
  clearInterval(game.interval);
});

test('solved refreshable timed modules refresh only when their timer expires', () => {
  const game = new LiarLiarGame(config());
  game.start();
  const wire = game.bombs[0].modules.find((module) => module.kind === 'wire_cut');
  game.operate(0, wire.id, { wire: wire.solution.wire });

  assert.equal(wire.status, 'solved');
  assert.equal(game.bombs[0].modules.filter((module) => module.kind === 'wire_cut').length, 1);

  wire.expiresAt = Date.now() - 1;
  game.tick();
  assert.equal(game.bombs[0].modules.filter((module) => module.kind === 'wire_cut').length, 2);
  assert(game.bombs[0].modules.some((module) => module.kind === 'wire_cut' && module.instance === 2));
  assert.deepEqual(
    game.viewFor(0).bomb.modules.filter((module) => module.kind === 'wire_cut').map((module) => module.instance),
    [2],
  );

  game.tick();
  game.tick();
  assert.equal(game.bombs[0].modules.filter((module) => module.kind === 'wire_cut').length, 2);
  clearInterval(game.interval);
});

test('timed keypad timeout refreshes, timed wire timeout detonates', () => {
  const keypadGame = new LiarLiarGame(config());
  keypadGame.start();
  const keypad = keypadGame.bombs[0].modules.find((module) => module.kind === 'keypad_calibration');
  keypad.expiresAt = Date.now() - 1;
  keypadGame.tick();
  assert.equal(keypadGame.bombs[0].detonated, false);
  assert.equal(keypad.status, 'expired');
  assert(keypadGame.bombs[0].modules.some((module) => module.kind === 'keypad_calibration' && module.instance === 2));
  clearInterval(keypadGame.interval);

  const wireGame = new LiarLiarGame(config());
  wireGame.start();
  const wire = wireGame.bombs[0].modules.find((module) => module.kind === 'wire_cut');
  wire.expiresAt = Date.now() - 1;
  wireGame.tick();
  assert.equal(wireGame.bombs[0].detonated, true);
  assert.equal(wire.status, 'failed');
  clearInterval(wireGame.interval);
});

test('untimed modules do not expire during ticks', () => {
  const game = new LiarLiarGame(config());
  game.start();
  const rps = game.bombs[0].modules.find((module) => module.kind === 'rps_duel');
  const truthLie = game.bombs[0].modules.find((module) => module.kind === 'two_truths_lie');
  rps.expiresAt = Date.now() - 1;
  truthLie.expiresAt = Date.now() - 1;
  game.tick();
  assert.equal(game.bombs[0].detonated, false);
  assert.equal(rps.status, 'active');
  assert.equal(truthLie.status, 'active');
  clearInterval(game.interval);
});

test('rps draw is safe and awards draw points', () => {
  const game = new LiarLiarGame(config());
  game.start();
  const a = 0;
  const b = 5;
  const modA = game.bombs[a].modules.find((module) => module.kind === 'rps_duel');
  const modB = game.bombs[b].modules.find((module) => module.kind === 'rps_duel');
  solveLethalNonRps(game, [a, b]);
  game.operate(a, modA.id, { choice: 'rock' });
  game.operate(b, modB.id, { choice: 'rock' });
  assert.equal(game.bombs[a].detonated, false);
  assert.equal(game.bombs[b].detonated, false);
  assert.equal(modA.status, 'active');
  assert.equal(modB.status, 'active');
  assert.equal(game.scores[a], 0);
  assert.equal(game.scores[b], 0);
  game.finalizeRound('test');
  assert.equal(game.bombs[a].detonated, false);
  assert.equal(game.bombs[b].detonated, false);
  assert.equal(game.scores[a], 10);
  assert.equal(game.scores[b], 10);
  assert.equal(modA.rpsResult, 'Rock ties Rock. Draw.');
  assert.equal(modB.rpsResult, 'Rock ties Rock. Draw.');
  clearInterval(game.interval);
});

test('rps result explains normal win and loss', () => {
  const game = new LiarLiarGame(config());
  game.start();
  const modA = game.bombs[0].modules.find((module) => module.kind === 'rps_duel');
  const modB = game.bombs[5].modules.find((module) => module.kind === 'rps_duel');
  solveLethalNonRps(game, [0, 5]);

  game.operate(0, modA.id, { choice: 'rock' });
  game.operate(5, modB.id, { choice: 'paper' });

  assert.equal(modA.rpsResult, undefined);
  assert.equal(modB.rpsResult, undefined);
  assert.equal(game.bombs[0].detonated, false);
  game.finalizeRound('test');
  assert.equal(modA.rpsResult, 'Rock loses to Paper. You explode.');
  assert.equal(modB.rpsResult, 'Paper beats Rock. You win.');
  assert.equal(game.bombs[0].detonated, true);
  clearInterval(game.interval);
});

test('rps choice is locked and opponent detonation autopasses survivor', () => {
  const game = new LiarLiarGame(config());
  game.start();
  const modA = game.bombs[0].modules.find((module) => module.kind === 'rps_duel');
  const modB = game.bombs[5].modules.find((module) => module.kind === 'rps_duel');
  solveLethalNonRps(game, [0]);

  game.operate(0, modA.id, { choice: 'paper' });
  game.operate(0, modA.id, { choice: 'scissors' });
  assert.equal(modA.choice, 'paper');

  game.detonate(5, 'test detonation');
  assert.equal(modA.status, 'active');
  assert.equal(game.scores[0], 0);
  game.finalizeRound('test');
  assert.equal(modA.status, 'solved');
  assert.equal(modB.status, 'failed');
  assert.equal(game.scores[0], 15);
  assert.equal(modA.rpsResult, 'Paper beats NULL. Player 6 exploded; you win by default.');
  clearInterval(game.interval);
});

test('finalization detonates unresolved lethal modules before resolving rps', () => {
  const game = new LiarLiarGame(config());
  game.start();
  const modA = game.bombs[0].modules.find((module) => module.kind === 'rps_duel');
  const modB = game.bombs[5].modules.find((module) => module.kind === 'rps_duel');
  solveLethalNonRps(game, [0]);

  game.operate(0, modA.id, { choice: 'rock' });
  game.operate(5, modB.id, { choice: 'paper' });

  game.finalizeRound('test');

  assert.equal(game.bombs[5].detonated, true);
  assert.equal(game.bombs[0].detonated, false);
  assert.equal(modA.status, 'solved');
  assert.equal(modA.rpsResult, 'Rock beats NULL. Player 6 exploded; you win by default.');
  clearInterval(game.interval);
});

test('telephone calculator is private per player and solves relay with returned code', () => {
  const game = new LiarLiarGame(config());
  game.start();
  const module = game.bombs[0].modules.find((candidate) => candidate.kind === 'telephone_relay');
  let code = module.initialCode;
  for (const slot of module.route) code = game.calculate(slot, code) ?? game.calculatorResults[slot].at(-1).output;

  assert.match(code, /^\d{4}$/);
  game.operate(0, module.id, { code });
  assert.equal(module.status, 'solved');
  assert.equal(game.scores[0], 40);
  assert.equal(game.viewFor(module.route[0]).calculatorResults.at(-1).output.length, 4);
  clearInterval(game.interval);
});

test('telephone relay can skip only currently dead relay players', () => {
  const game = new LiarLiarGame(config());
  game.start();
  const module = game.bombs[0].modules.find((candidate) => candidate.kind === 'telephone_relay');
  const [first, second, third] = module.route;
  const firstOnly = game.calculate(first, module.initialCode);
  const skippedSecond = game.calculate(third, firstOnly);
  const withSecond = game.calculate(third, game.calculate(second, firstOnly));

  assert.notEqual(skippedSecond, withSecond);
  assert.equal(game.acceptsTelephoneCode(module, skippedSecond), false);

  game.detonate(second, 'test detonation');
  assert.equal(game.calculate(second, firstOnly), undefined);
  assert.equal(game.acceptsTelephoneCode(module, skippedSecond), true);
  game.operate(0, module.id, { code: skippedSecond });
  assert.equal(module.status, 'solved');
  clearInterval(game.interval);
});

test('two coup votes detonate the target and coup votes can be toggled', () => {
  const game = new LiarLiarGame(config());
  game.start();
  const coup0 = game.bombs[0].modules.find((module) => module.kind === 'coup');
  const coup2 = game.bombs[2].modules.find((module) => module.kind === 'coup');

  game.operate(0, coup0.id, { target: 1 });
  assert.deepEqual(coup0.votes, [1]);
  assert.equal(game.bombs[1].detonated, false);

  game.operate(0, coup0.id, { target: 1 });
  assert.deepEqual(coup0.votes, []);
  game.operate(0, coup0.id, { target: 1 });
  game.operate(2, coup2.id, { target: 1 });

  assert.equal(game.bombs[1].detonated, true);
  assert.equal(game.bombs[1].detonationReason, 'couped');
  assert.equal(game.scores[0], -5);
  assert.equal(game.scores[2], -5);
  clearInterval(game.interval);
});

test('game finishes early when every module is addressed', () => {
  const game = new LiarLiarGame(config());
  game.start();
  for (const bomb of game.bombs) {
    for (const module of bomb.modules) module.status = 'solved';
  }
  game.tick();

  assert.equal(game.phase(), 'finished');
  assert.equal(game.events.at(-1).data.reason, 'all modules addressed');
});
