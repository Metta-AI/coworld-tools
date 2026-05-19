import { baseModule, fourDigit, pick, makeRng } from './core.js';

const def = { name: 'Telephone Relay', lethal: false, points: 40, timer: null, refresh: false };

export const telephoneRelayModule = {
  kind: 'telephone_relay',
  order: 60,
  initial: true,
  def,
  metaManual:
    'Send the 4-digit code through the listed players in order. Each relay player must use their private calculator and pass the 4-digit output onward. Enter the returned code.',
  actionSchema: { type: 'operate', action: { code: '0000' } },
  create({ id, targetSlot, instance, now, seed, rng, options }) {
    const initialCode = fourDigit(Math.floor(rng() * 10000));
    const route = telephoneRoute(targetSlot, options.playerCount ?? 6, options.communicationGraph ?? {}, rng);
    const finalCode = route.reduce((code, slot) => telephoneTransform(slot, code, seed), initialCode);
    return baseModule(def, 'telephone_relay', id, targetSlot, instance, now, {
      initialCode,
      route,
      routeLabels: route.map((slot) => `Player ${slot + 1}`),
      solution: { code: finalCode },
      hints: [],
    });
  },
  operate(game, slot, module, action) {
    game.resolveSimple(slot, module, game.acceptsTelephoneCode(module, String(action?.code ?? '')), action);
  },
};

export function telephoneTransform(slot, code, seed = 'liarliar') {
  if (!/^\d{4}$/.test(String(code))) return null;
  const rng = makeRng(`${seed}:telephone-calculator:${slot}`);
  const multiplier = 1 + Math.floor(rng() * 4999) * 2;
  const offset = Math.floor(rng() * 10000);
  return fourDigit((Number(code) * multiplier + offset) % 10000);
}

function telephoneRoute(targetSlot, playerCount, graph, rng) {
  const allOthers = Array.from({ length: playerCount }, (_, slot) => slot).filter((slot) => slot !== targetSlot);
  const ownerNeighbors = graph[targetSlot] ?? allOthers;
  const nonNeighbors = allOthers.filter((slot) => !ownerNeighbors.includes(slot));
  const middle = nonNeighbors.length ? pick(nonNeighbors, rng) : pick(allOthers, rng);
  const bridgeCandidates = ownerNeighbors.filter((slot) => graph[slot]?.includes(middle));
  const first = pick(bridgeCandidates.length ? bridgeCandidates : ownerNeighbors, rng);
  const thirdCandidates = (bridgeCandidates.length ? bridgeCandidates : ownerNeighbors).filter((slot) => slot !== first);
  const third = thirdCandidates.length ? pick(thirdCandidates, rng) : first;
  return [first, middle, third];
}
