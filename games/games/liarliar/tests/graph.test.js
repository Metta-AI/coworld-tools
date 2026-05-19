import test from 'node:test';
import assert from 'node:assert/strict';
import { buildGraph, circleGraph, distributeHints, gridGraph } from '../src/graph.js';

test('circle graph connects players within radius two', () => {
  const graph = circleGraph(6, 2);
  for (let slot = 0; slot < 6; slot += 1) {
    assert.equal(graph[slot].length, 4);
    assert.equal(new Set(graph[slot]).size, 4);
    assert(!graph[slot].includes(slot));
  }
  assert.deepEqual(graph[0], [1, 2, 4, 5]);
  assert.deepEqual(graph[5], [0, 1, 3, 4]);
});

test('custom graph normalizes undirected edges', () => {
  const graph = buildGraph({ type: 'custom', edges: [[0, 1], [1, 2]] }, 3);
  assert.deepEqual(graph, { 0: [1], 1: [0, 2], 2: [1] });
});

test('grid graph can infer decomposable m x n dimensions', () => {
  const graph = gridGraph(12);
  assert.deepEqual(graph[0], [1, 4]);
  assert.deepEqual(graph[5], [1, 4, 6, 9]);
  assert.deepEqual(graph[11], [7, 10]);
});

test('grid graph supports explicit wrapped dimensions', () => {
  const graph = buildGraph({ type: 'grid', rows: 3, cols: 3, wrap: true }, 9);
  assert.deepEqual(graph[0], [1, 2, 3, 6]);
  assert.deepEqual(graph[4], [1, 3, 5, 7]);
});

test('hint distribution excludes owner and applies redundancy', () => {
  const graph = circleGraph(6, 2);
  const hints = [{ id: 'hint:a', targetSlot: 0 }, { id: 'hint:b', targetSlot: 1 }];
  const held = distributeHints(hints, graph, Array.from({ length: 6 }, () => ({})), 2);
  assert.equal(held.flat().filter((hint) => hint.id === 'hint:a').length, 2);
  assert.equal(held[0].some((hint) => hint.targetSlot === 0), false);
});

test('redundant copies of one hint never go to the same holder', () => {
  const graph = { 0: [1, 1, 2, 2, 3], 1: [0], 2: [0], 3: [0] };
  const hint = { id: 'hint:dedupe', targetSlot: 0 };
  const held = distributeHints([hint], graph, Array.from({ length: 4 }, () => ({})), 3);
  const holders = held.flatMap((hints, slot) => (hints.some((candidate) => candidate.id === hint.id) ? [slot] : []));

  assert.equal(holders.length, 3);
  assert.equal(new Set(holders).size, holders.length);
});

test('fractional hint redundancy gives one required holder plus deterministic extras', () => {
  const graph = circleGraph(6, 2);
  const hints = Array.from({ length: 20 }, (_, index) => ({ id: `hint:fractional:${index}`, targetSlot: index % 6 }));
  const held = distributeHints(hints, graph, Array.from({ length: 6 }, () => ({})), 1.3);
  const delivered = held.flat().length;

  assert(delivered >= hints.length);
  assert(delivered < hints.length * 2);
  for (const hint of hints) {
    assert.equal(held.flat().filter((candidate) => candidate.id === hint.id).length >= 1, true);
  }
});

test('default hint distribution keeps player loads close', () => {
  const graph = circleGraph(6, 2);
  const hints = Array.from({ length: 54 }, (_, index) => ({ id: `hint:load:${index}`, targetSlot: index % 6 }));
  const held = distributeHints(hints, graph, Array.from({ length: 6 }, () => ({})), 1.3);
  const loads = held.map((items) => items.length);

  assert(Math.max(...loads) - Math.min(...loads) <= 2);
});
