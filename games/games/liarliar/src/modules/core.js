export function baseModule(def, kind, id, targetSlot, instance, now, extra = {}) {
  return {
    id,
    kind,
    name: def.name,
    targetSlot,
    instance,
    lethal: def.lethal,
    points: def.points,
    maxPoints: def.points,
    utility: Boolean(def.utility),
    timed: Number.isFinite(def.timer),
    timerSeconds: Number.isFinite(def.timer) ? def.timer : null,
    startedAt: Number.isFinite(def.timer) ? now : null,
    expiresAt: Number.isFinite(def.timer) ? now + def.timer * 1000 : null,
    status: 'active',
    refresh: def.refresh,
    ...extra,
  };
}

export function hint(moduleId, targetSlot, key, text, data = {}) {
  const [kind, slot, instance] = moduleId.split(':');
  return {
    id: `hint:${moduleId}:${key}`,
    targetSlot,
    targetLabel: `Player ${targetSlot + 1}`,
    moduleId,
    moduleKind: kind,
    moduleInstance: Number(instance),
    label: `For Player ${Number(slot) + 1} / ${kind} / instance ${instance}`,
    text,
    data,
  };
}

export function publicModule(module) {
  const hidden = new Set(['solution', 'hints']);
  return Object.fromEntries(Object.entries(module).filter(([key]) => !hidden.has(key)));
}

export function pick(items, rng) {
  return items[Math.floor(rng() * items.length) % items.length];
}

export function fourDigit(value) {
  return String(Number(value) % 10000).padStart(4, '0');
}

export function makeRng(seed) {
  let state = 2166136261;
  for (let i = 0; i < seed.length; i += 1) {
    state ^= seed.charCodeAt(i);
    state = Math.imul(state, 16777619);
  }
  return () => {
    state += 0x6d2b79f5;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}
