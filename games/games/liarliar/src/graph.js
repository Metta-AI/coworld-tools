export function defaultPlayers(count = 6) {
  return Array.from({ length: count }, (_, slot) => ({ name: `Player ${slot + 1}` }));
}

export function buildGraph(config, count) {
  if (config?.type === 'custom') return customGraph(config.edges, count);
  if (config?.type === 'grid') return gridGraph(count, config);
  if (config?.type === 'torus') return gridGraph(count, { ...config, wrap: true });
  if (config?.type === 'circle' || config?.type === 'ring') {
    return circleGraph(count, Number(config.radius ?? 2));
  }
  if (config?.type === 'balanced') return balancedGraph(count, Number(config.degree ?? Math.min(4, count - 1)));
  if (!config) return circleGraph(count, 2);
  return balancedGraph(count, Number(config.degree ?? Math.min(4, count - 1)));
}

export function circleGraph(count, radius = 2) {
  const graph = emptyGraph(count);
  const maxRadius = Math.max(0, Math.floor(Number(radius) || 0));
  for (let slot = 0; slot < count; slot += 1) {
    const neighbors = new Set();
    for (let delta = 1; delta <= maxRadius; delta += 1) {
      neighbors.add((slot + delta) % count);
      neighbors.add((slot - delta + count) % count);
    }
    graph[slot] = [...neighbors].filter((other) => other !== slot).sort((a, b) => a - b);
  }
  return graph;
}

export function gridGraph(count, config = {}) {
  const [rows, cols] = gridDimensions(count, config);
  const wrap = Boolean(config.wrap);
  const graph = emptyGraph(count);
  for (let slot = 0; slot < count; slot += 1) {
    const row = Math.floor(slot / cols);
    const col = slot % cols;
    const neighbors = new Set();
    for (const [nextRow, nextCol] of [
      [row - 1, col],
      [row + 1, col],
      [row, col - 1],
      [row, col + 1],
    ]) {
      if (wrap) {
        neighbors.add(slotAt((nextRow + rows) % rows, (nextCol + cols) % cols, cols));
      } else if (nextRow >= 0 && nextRow < rows && nextCol >= 0 && nextCol < cols) {
        neighbors.add(slotAt(nextRow, nextCol, cols));
      }
    }
    graph[slot] = [...neighbors].filter((other) => other !== slot).sort((a, b) => a - b);
  }
  return graph;
}

export function balancedGraph(count, degree) {
  const graph = emptyGraph(count);
  for (let slot = 0; slot < count; slot += 1) {
    let distance = 1;
    while (graph[slot].length < degree && distance < count) {
      for (const other of [(slot + distance) % count, (slot - distance + count) % count]) {
        if (other !== slot && !graph[slot].includes(other)) graph[slot].push(other);
        if (graph[slot].length >= degree) break;
      }
      distance += 1;
    }
    graph[slot].sort((a, b) => a - b);
  }
  return graph;
}

export function customGraph(edges = [], count) {
  const graph = emptyGraph(count);
  for (const edge of edges) {
    const [a, b] = edge;
    if (!Number.isInteger(a) || !Number.isInteger(b) || a < 0 || b < 0 || a >= count || b >= count || a === b) {
      throw new Error(`Invalid graph edge: ${JSON.stringify(edge)}`);
    }
    if (!graph[a].includes(b)) graph[a].push(b);
    if (!graph[b].includes(a)) graph[b].push(a);
  }
  for (const slot of Object.keys(graph)) graph[slot].sort((a, b) => a - b);
  return graph;
}

export function canTalk(graph, from, to) {
  return graph[from]?.includes(to) ?? false;
}

export function distributeHints(hints, hintGraph, players, redundancy = 1.3) {
  const heldHints = players.map(() => []);
  const load = players.map(() => 0);
  const expectedCopies = Math.max(1, Number(redundancy) || 1);
  const guaranteedCopies = Math.floor(expectedCopies);
  const extraChance = expectedCopies - guaranteedCopies;
  const orderedHints = [...hints].sort((a, b) => stableNumber(a.id) - stableNumber(b.id));
  for (const hint of orderedHints) {
    const candidates = [...new Set(hintGraph[hint.targetSlot] ?? [])].filter((slot) => slot !== hint.targetSlot);
    if (candidates.length === 0) continue;
    let copies = Math.min(guaranteedCopies, candidates.length);
    if (copies < candidates.length && (stableNumber(`${hint.id}:redundant`) % 1000) / 1000 < extraChance) copies += 1;
    const used = new Set();
    for (let i = 0; i < copies; i += 1) {
      const slot = chooseLowestLoad(candidates.filter((candidate) => !used.has(candidate)), load, `${hint.id}:${i}`);
      if (slot === null) break;
      used.add(slot);
      heldHints[slot].push(hint);
      load[slot] += 1;
    }
  }
  return heldHints;
}

export function stableNumber(value) {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function emptyGraph(count) {
  const graph = {};
  for (let slot = 0; slot < count; slot += 1) graph[slot] = [];
  return graph;
}

function gridDimensions(count, config) {
  const rows = Number(config.rows ?? config.m);
  const cols = Number(config.cols ?? config.n);
  if (Number.isInteger(rows) || Number.isInteger(cols)) {
    if (!Number.isInteger(rows) || !Number.isInteger(cols) || rows < 3 || cols < 3 || rows * cols !== count) {
      throw new Error(`Invalid grid graph dimensions for ${count} players: ${JSON.stringify(config)}`);
    }
    return [rows, cols];
  }
  const factors = [];
  for (let rowsCandidate = 3; rowsCandidate <= Math.sqrt(count); rowsCandidate += 1) {
    if (count % rowsCandidate !== 0) continue;
    const colsCandidate = count / rowsCandidate;
    if (colsCandidate >= 3) factors.push([rowsCandidate, colsCandidate]);
  }
  if (factors.length === 0) throw new Error(`Cannot generate grid graph for ${count} players; no m x n factorization with m,n >= 3`);
  return factors.sort((a, b) => Math.abs(a[0] - a[1]) - Math.abs(b[0] - b[1]))[0];
}

function slotAt(row, col, cols) {
  return row * cols + col;
}

function chooseLowestLoad(candidates, load, salt) {
  if (candidates.length === 0) return null;
  const minLoad = Math.min(...candidates.map((slot) => load[slot]));
  const lightest = candidates.filter((slot) => load[slot] === minLoad);
  return lightest[stableNumber(salt) % lightest.length];
}
