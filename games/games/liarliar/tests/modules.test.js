import test from 'node:test';
import assert from 'node:assert/strict';
import { MODULE_REGISTRY, createInitialModules, createModule, getModule, rpsWinner, telephoneTransform } from '../src/modules.js';
import { circleGraph } from '../src/graph.js';
import { hintsFromMessages, solveModule } from '../src/bot/brain.js';

test('module registry owns definitions, schemas, and operation handlers', () => {
  const kinds = MODULE_REGISTRY.map((entry) => entry.kind);
  assert.deepEqual(kinds, ['wire_cut', 'keypad_calibration', 'switch_panel', 'rps_duel', 'two_truths_lie', 'telephone_relay', 'coup']);
  for (const entry of MODULE_REGISTRY) {
    assert.equal(getModule(entry.kind), entry);
    assert.equal(typeof entry.def?.name, 'string');
    assert.equal(typeof entry.metaManual, 'string');
    assert.equal(typeof entry.operate, 'function');
    assert.equal(entry.actionSchema?.type, 'operate');
  }
});

test('wire and keypad modules can be solved from visible hints', () => {
  const wire = createModule('wire_cut', 0, 1, Date.now(), 'test');
  assert.deepEqual(solveModule(wire, wire.hints), wire.solution);

  const keypad = createModule('keypad_calibration', 0, 1, Date.now(), 'test');
  assert.deepEqual(solveModule(keypad, keypad.hints), keypad.solution);
  assert.equal(keypad.hints.length, 2);
  assert.equal(solveModule(keypad, keypad.hints.slice(0, 1)), null);
});

test('only wire and keypad are timed v1 modules', () => {
  const now = Date.now();
  const wire = createModule('wire_cut', 0, 1, now, 'test');
  const keypad = createModule('keypad_calibration', 0, 1, now, 'test');
  const switchPanel = createModule('switch_panel', 0, 1, now, 'test');
  const truthLie = createModule('two_truths_lie', 0, 1, now, 'test');

  assert.equal(wire.timed, true);
  assert.equal(wire.timerSeconds, 150);
  assert.equal(keypad.timed, true);
  assert.equal(keypad.timerSeconds, 150);
  assert.equal(switchPanel.timed, false);
  assert.equal(switchPanel.expiresAt, null);
  assert.equal(truthLie.timed, false);
  assert.equal(truthLie.expiresAt, null);
});

test('switch module requires combined hints', () => {
  const module = createModule('switch_panel', 0, 1, Date.now(), 'test');
  assert.equal(solveModule(module, module.hints.slice(0, 1)), null);
  assert.deepEqual(solveModule(module, module.hints), module.solution);
});

test('two truths and a lie has one false claim and bot finds it', () => {
  const module = createModule('two_truths_lie', 0, 1, Date.now(), 'test');
  const truthValues = module.hints.map((hint) => hint.data.truth);
  assert.equal(truthValues.filter(Boolean).length, 2);
  assert.equal(truthValues.filter((value) => !value).length, 1);
  assert.deepEqual(solveModule(module, module.hints), { falseClaim: module.solution.falseClaim });
});

test('telephone relay uses four digit codes and routes second hop through non-neighbor', () => {
  const graph = circleGraph(6, 2);
  const { bombs } = createInitialModules(Array.from({ length: 6 }, (_, slot) => ({ name: `P${slot + 1}` })), Date.now(), 'test', graph);
  const module = bombs[0].modules.find((candidate) => candidate.kind === 'telephone_relay');

  assert.match(module.initialCode, /^\d{4}$/);
  assert.match(module.solution.code, /^\d{4}$/);
  assert.equal(module.route.length, 3);
  assert.equal(graph[0].includes(module.route[1]), false);
  assert.match(telephoneTransform(module.route[0], module.initialCode, 'test'), /^\d{4}$/);
});

test('bot can parse ordinary chat-passed manual hints', () => {
  const hints = hintsFromMessages([
    {
      id: 'msg:1',
      text: 'For Player 1 / wire_cut / instance 1: The safe wire color is blue.',
    },
  ]);

  assert.deepEqual(hints[0], {
    id: 'chat:msg:1',
    targetSlot: 0,
    moduleId: 'wire_cut:0:1',
    moduleKind: 'wire_cut',
    moduleInstance: 1,
    text: 'The safe wire color is blue.',
    source: 'chat',
  });
});

test('rps winner rules are standard', () => {
  assert.equal(rpsWinner('rock', 'rock'), 0);
  assert.equal(rpsWinner('rock', 'scissors'), 1);
  assert.equal(rpsWinner('rock', 'paper'), -1);
});
