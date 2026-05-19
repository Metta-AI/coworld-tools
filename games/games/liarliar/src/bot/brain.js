const COLORS = ['red', 'blue', 'yellow', 'white', 'black'];
const SYMBOLS = ['star', 'moon', 'bolt', 'wave', 'ring', 'cross'];

export function scriptedDecisions(view, sharedHintIds = new Set()) {
  const decisions = [];
  if (view.phase === 'lobby' && !view.ready) {
    decisions.push({ type: 'ready', ready: true });
    return decisions;
  }
  for (const hint of view.hints.filter((candidate) => candidate.source === 'held')) {
    if (sharedHintIds.has(hint.id)) continue;
    if (view.communication.neighbors.includes(hint.targetSlot)) {
      sharedHintIds.add(hint.id);
      decisions.push({ type: 'chat', to: hint.targetSlot, text: `${hint.label}: ${hint.text}` });
    }
  }
  if (!view.started || view.bomb.detonated) return decisions;
  const knownHints = knownHintsFromView(view);
  for (const module of view.bomb.modules.filter((candidate) => candidate.status === 'active')) {
    const action = solveModule(module, knownHints);
    if (action) decisions.push({ type: 'operate', moduleId: module.id, action });
  }
  return decisions;
}

export function knownHintsFromView(view) {
  return [...view.hints, ...hintsFromMessages(view.communication?.directMessages ?? [])];
}

export function hintsFromMessages(messages) {
  return messages
    .map((message) => {
      const match = /^For Player (\d+) \/ ([a-z_]+) \/ instance (\d+): (.+)$/i.exec(message.text ?? '');
      if (!match) return null;
      const targetSlot = Number(match[1]) - 1;
      const moduleKind = match[2];
      const moduleInstance = Number(match[3]);
      return {
        id: `chat:${message.id}`,
        targetSlot,
        moduleId: `${moduleKind}:${targetSlot}:${moduleInstance}`,
        moduleKind,
        moduleInstance,
        text: match[4],
        source: 'chat',
      };
    })
    .filter(Boolean);
}

export function solveModule(module, hints) {
  const moduleHints = hints.filter((hint) => hint.moduleId === module.id);
  if (module.kind === 'wire_cut') {
    const text = moduleHints.map((hint) => hint.text).join(' ').toLowerCase();
    const wire = COLORS.find((color) => text.includes(color));
    return wire ? { wire } : null;
  }
  if (module.kind === 'keypad_calibration') {
    const text = moduleHints.map((hint) => hint.text).join(' ').toLowerCase();
    const pair = SYMBOLS.filter((symbol) => text.includes(symbol));
    const position = text.includes('first') ? 0 : text.includes('second') ? 1 : null;
    const answer = position === null ? null : pair[position];
    return answer ? { answer } : null;
  }
  if (module.kind === 'switch_panel') {
    const text = moduleHints.map((hint) => hint.text).join('\n');
    const first = /Switch 1 is (ON|OFF)/i.exec(text);
    const rest = /Switches 2 and 3 are (ON|OFF) then (ON|OFF)/i.exec(text);
    if (!first || !rest) return null;
    return { settings: [first[1].toUpperCase() === 'ON', rest[1].toUpperCase() === 'ON', rest[2].toUpperCase() === 'ON'] };
  }
  if (module.kind === 'two_truths_lie') {
    const claims = moduleHints
      .map((hint) => /Claim (\d+): The safe word is ([a-z]+)/i.exec(hint.text))
      .filter(Boolean)
      .map((match) => ({ claim: Number(match[1]), word: match[2].toLowerCase() }));
    if (claims.length < 3) return null;
    const counts = new Map();
    for (const claim of claims) counts.set(claim.word, (counts.get(claim.word) ?? 0) + 1);
    const trueWord = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
    const falseClaim = claims.find((claim) => claim.word !== trueWord)?.claim;
    return falseClaim ? { falseClaim } : null;
  }
  if (module.kind === 'rps_duel') {
    return { choice: 'rock' };
  }
  return null;
}
