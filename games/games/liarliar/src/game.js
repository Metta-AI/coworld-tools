import { EventEmitter } from 'node:events';
import { buildGraph, canTalk, defaultPlayers, distributeHints } from './graph.js';
import {
  MODULE_DEFS,
  MODULE_REGISTRY,
  createInitialModules,
  createModule,
  getModule,
  metaManuals,
  moduleOrder,
  publicModule,
  telephoneTransform,
} from './modules.js';

export class LiarLiarGame extends EventEmitter {
  constructor(config, sinks = {}) {
    super();
    this.config = normalizeConfig(config);
    this.sinks = sinks;
    this.players = this.config.players;
    this.communicationGraph = buildGraph(this.config.communication_graph, this.players.length);
    this.hintGraph = buildGraph(this.config.hint_graph ?? this.config.communication_graph, this.players.length);
    this.durationMs = this.config.duration_seconds * 1000;
    this.seed = this.config.seed;
    this.startedAt = null;
    this.finishedAt = null;
    this.finalizedAt = null;
    this.interval = null;
    this.playerSockets = new Map();
    this.globalSockets = new Set();
    this.adminSockets = new Set();
    this.readySlots = new Set();
    this.directMessages = [];
    this.systemMessages = [];
    this.recoveredHints = this.players.map(() => []);
    this.scores = this.players.map(() => 0);
    this.penalties = this.players.map(() => 0);
    this.calculatorResults = this.players.map(() => []);
    this.rpsChoices = new Map();
    this.coupVotes = this.players.map(() => new Set());
    this.events = [];
    this.nextInstance = new Map();
    const initial = createInitialModules(this.players, Date.now(), this.seed, this.communicationGraph);
    this.bombs = initial.bombs;
    this.heldHints = distributeHints(initial.allHints, this.hintGraph, this.players, this.config.hint_redundancy);
  }

  start() {
    if (this.startedAt) return;
    this.startedAt = Date.now();
    for (const bomb of this.bombs) {
      for (const module of bomb.modules) {
        if (module.status !== 'active') continue;
        const timer = MODULE_DEFS[module.kind]?.timer;
        if (!Number.isFinite(timer)) {
          module.startedAt = null;
          module.expiresAt = null;
          continue;
        }
        module.startedAt = this.startedAt;
        module.expiresAt = this.startedAt + timer * 1000;
      }
    }
    this.record('game_started', {});
    this.interval = setInterval(() => this.tick(), 1000 / this.config.tick_rate);
    this.broadcast();
  }

  maybeAutoStart() {
    if (this.startedAt) return;
    if (this.playerSockets.size >= this.players.length && this.readySlots.size >= this.players.length) this.start();
  }

  connectPlayer(slot, token, socket) {
    if (!Number.isInteger(slot) || slot < 0 || slot >= this.players.length || this.config.tokens[slot] !== token) {
      socket.close(1008, 'invalid slot or token');
      return false;
    }
    if (this.finishedAt) {
      socket.sendJson({ type: 'final', view: null, results: this.results() });
      socket.close();
      return true;
    }
    this.playerSockets.set(slot, socket);
    socket.on('message', (raw) => this.handlePlayerMessage(slot, raw));
    socket.on('close', () => {
      if (this.playerSockets.get(slot) === socket) {
        this.playerSockets.delete(slot);
        if (!this.startedAt) this.readySlots.delete(slot);
        this.broadcast();
      }
    });
    this.sendPlayerView(slot);
    this.record('player_connected', { slot });
    this.maybeAutoStart();
    return true;
  }

  connectGlobal(socket) {
    this.globalSockets.add(socket);
    socket.on('close', () => this.globalSockets.delete(socket));
    socket.sendJson({ type: 'global', state: this.globalView() });
  }

  connectAdmin(socket) {
    this.adminSockets.add(socket);
    socket.on('close', () => this.adminSockets.delete(socket));
    socket.on('message', (raw) => {
      const message = safeJson(raw);
      if (message?.type === 'start') this.start();
      if (message?.type === 'finish') this.finish('admin');
    });
    socket.sendJson({ type: 'admin', state: this.globalView() });
  }

  handlePlayerMessage(slot, raw) {
    const message = safeJson(raw);
    if (!message || typeof message.type !== 'string') return;
    if (message.type === 'ready') this.setReady(slot, message.ready !== false);
    if (message.type === 'chat') this.chat(slot, Number(message.to), String(message.text ?? ''));
    if (message.type === 'calculate') this.calculate(slot, String(message.code ?? ''));
    if (message.type === 'operate' && this.startedAt) this.operate(slot, String(message.moduleId ?? ''), message.action ?? {});
  }

  setReady(slot, ready, { silent = false } = {}) {
    if (this.startedAt || this.finishedAt) return;
    const nextReady = Boolean(ready);
    if (this.readySlots.has(slot) === nextReady) {
      if (!silent) this.maybeAutoStart();
      return;
    }
    if (nextReady) this.readySlots.add(slot);
    else this.readySlots.delete(slot);
    this.record('player_ready', { slot, ready: nextReady });
    if (!silent) {
      this.broadcast();
      this.maybeAutoStart();
    }
  }

  chat(from, to, text) {
    if (!canTalk(this.communicationGraph, from, to) || !text.trim()) return;
    if (this.bombs[from]?.detonated || this.bombs[to]?.detonated) return;
    const entry = { id: `msg:${this.directMessages.length + 1}`, at: Date.now(), from, to, text: text.slice(0, 1200) };
    this.directMessages.push(entry);
    this.record('direct_chat', entry);
    this.sendPlayerView(from);
    this.sendPlayerView(to);
    this.sendGlobal();
  }

  operate(slot, moduleId, action) {
    const bomb = this.bombs[slot];
    if (!bomb || bomb.detonated) return;
    const module = bomb.modules.find((candidate) => candidate.id === moduleId);
    if (!module || module.status !== 'active') return;
    getModule(module.kind)?.operate?.(this, slot, module, action);
  }

  calculate(slot, code) {
    if (!this.startedAt || this.finishedAt || this.bombs[slot]?.detonated || !/^\d{4}$/.test(code)) return;
    const output = telephoneTransform(slot, code, this.seed);
    const entry = { at: Date.now(), input: code, output };
    this.calculatorResults[slot].push(entry);
    this.calculatorResults[slot] = this.calculatorResults[slot].slice(-8);
    this.record('telephone_calculated', { slot, input: code, output });
    this.sendPlayerView(slot);
    this.sendGlobal();
    return output;
  }

  acceptsTelephoneCode(module, code) {
    if (!/^\d{4}$/.test(code)) return false;
    const accepted = new Set([module.initialCode]);
    for (const slot of module.route) {
      const next = new Set();
      for (const candidate of accepted) {
        next.add(telephoneTransform(slot, candidate, this.seed));
        if (this.bombs[slot]?.detonated) next.add(candidate);
      }
      accepted.clear();
      for (const candidate of next) accepted.add(candidate);
    }
    return accepted.has(code);
  }

  resolveSimple(slot, module, ok, action) {
    if (ok) {
      module.status = 'solved';
      module.solvedAt = Date.now();
      const points = this.pointsFor(module);
      this.scores[slot] += points;
      this.record('module_solved', { slot, moduleId: module.id, kind: module.kind, points, action });
    } else if (module.lethal) {
      this.detonate(slot, `failed ${module.kind}`, { moduleId: module.id, action });
    } else {
      module.status = 'expired';
      this.penalties[slot] += 3;
      this.scores[slot] -= 3;
      this.record('module_reset', { slot, moduleId: module.id, kind: module.kind, action });
      this.refreshModule(slot, module.kind);
    }
    this.broadcast();
  }

  refreshModule(slot, kind) {
    const key = `${slot}:${kind}`;
    const next = (this.nextInstance.get(key) ?? 1) + 1;
    this.nextInstance.set(key, next);
    const module = createModule(kind, slot, next, Date.now(), this.seed, {
      playerCount: this.players.length,
      communicationGraph: this.communicationGraph,
    });
    this.bombs[slot].modules.push(module);
    const distributed = distributeHints(module.hints, this.hintGraph, this.players, this.config.hint_redundancy);
    distributed.forEach((hints, holder) => this.heldHints[holder].push(...hints));
    this.record('module_refreshed', { slot, kind, moduleId: module.id, hintIds: module.hints.map((hint) => hint.id) });
  }

  detonate(slot, reason, details = {}) {
    const bomb = this.bombs[slot];
    if (!bomb || bomb.detonated) return;
    bomb.detonated = true;
    bomb.detonatedAt = Date.now();
    bomb.detonationReason = reason;
    this.scores[slot] -= 25;
    for (const entry of MODULE_REGISTRY) entry.onDetonation?.(this, slot);
    for (const module of bomb.modules) {
      if (module.status === 'active' && module.lethal) module.status = 'failed';
    }
    const recipients = new Set([slot, ...(this.hintGraph[slot] ?? []), ...(this.communicationGraph[slot] ?? [])]);
    for (const hint of this.heldHints[slot]) {
      for (const recipient of recipients) {
        if (recipient !== slot) this.recoveredHints[recipient].push({ ...hint, recoveredFrom: slot, recoveredAt: Date.now() });
      }
    }
    this.record('detonation', { slot, reason, recoveredHintCount: this.heldHints[slot].length, ...details });
    this.broadcast();
  }

  finalizeRound(reason = 'time') {
    if (this.finalizedAt) return;
    this.finalizedAt = Date.now();
    this.record('round_finalizing', { reason });
    for (const bomb of this.bombs) {
      if (bomb.detonated) continue;
      const unresolved = bomb.modules.find((module) => shouldDetonateAtFinalization(module));
      if (unresolved) this.detonate(bomb.slot, `unresolved ${unresolved.kind}`, { moduleId: unresolved.id, finalizing: true });
    }
    for (const entry of MODULE_REGISTRY) entry.finalize?.(this);
  }

  tick() {
    if (!this.startedAt || this.finishedAt) return;
    const now = Date.now();
    for (const bomb of this.bombs) {
      if (bomb.detonated) continue;
      for (const module of bomb.modules) {
        if (!module.timed || now < module.expiresAt) continue;
        if (module.status === 'solved' && module.refresh && !module.refreshedAt) {
          module.refreshedAt = now;
          this.refreshModule(bomb.slot, module.kind);
          continue;
        }
        if (module.status !== 'active') continue;
        if (module.lethal) this.detonate(bomb.slot, `timed out ${module.kind}`, { moduleId: module.id });
        else {
          module.status = 'expired';
          this.record('module_expired', { slot: bomb.slot, moduleId: module.id, kind: module.kind });
          this.refreshModule(bomb.slot, module.kind);
        }
      }
    }
    if (now - this.startedAt >= this.durationMs) this.finish('time');
    else if (this.bombs.every((bomb) => bomb.detonated)) this.finish('all detonated');
    else if (this.bombs.every((bomb) => bomb.detonated || bomb.modules.every((module) => moduleAddressed(module)))) this.finish('all modules addressed');
    else this.broadcast();
  }

  async finish(reason = 'time') {
    if (this.finishedAt) return;
    this.finalizeRound(reason);
    this.finishedAt = Date.now();
    clearInterval(this.interval);
    this.record('game_finished', { reason });
    const results = this.results();
    const replay = { config: this.config, events: this.events, results };
    if (this.sinks.writeResults) await this.sinks.writeResults(results);
    if (this.sinks.writeReplay) await this.sinks.writeReplay(replay);
    for (const socket of this.playerSockets.values()) socket.sendJson({ type: 'final', view: null, results });
    this.sendGlobal();
    this.emit('finished', results);
  }

  pointsFor(module) {
    return module.points;
  }

  viewFor(slot) {
    const visibleMessages = this.directMessages.filter((message) => message.from === slot || message.to === slot);
    const knownHints = [
      ...this.heldHints[slot].map((hint) => publicHint(hint, 'held')),
      ...this.recoveredHints[slot].map((hint) => publicHint(hint, 'recovered')),
    ];
    return {
      type: 'player_view',
      slot,
      player: this.players[slot],
      phase: this.phase(),
      now: Date.now(),
      started: Boolean(this.startedAt),
      ready: this.readySlots.has(slot),
      lobby: this.lobbyView(),
      timeRemainingMs: this.startedAt ? Math.max(0, this.startedAt + this.durationMs - Date.now()) : this.durationMs,
      score: this.scores[slot],
      calculatorResults: this.calculatorResults[slot],
      metaManuals: metaManuals(),
      communication: {
        graph: this.communicationGraph,
        neighbors: this.communicationGraph[slot] ?? [],
        neighborStates: (this.communicationGraph[slot] ?? []).map((neighbor) => ({
          slot: neighbor,
          detonated: Boolean(this.bombs[neighbor]?.detonated),
          detonationReason: this.bombs[neighbor]?.detonationReason ?? null,
          revealedHintsForYou: knownHints.filter((hint) => hint.targetSlot === slot && hint.recoveredFrom === neighbor),
        })),
        directMessages: visibleMessages,
      },
      hints: this.startedAt ? knownHints : [],
      legalActions: this.startedAt ? this.legalActions(slot) : [],
      bomb: this.startedAt
        ? {
            ...this.bombs[slot],
            modules: visibleBombModules(this.bombs[slot].modules).map(publicModule),
          }
        : null,
    };
  }

  legalActions(slot) {
    const bomb = this.bombs[slot];
    if (bomb.detonated) return [];
    return bomb.modules
      .filter((module) => module.status === 'active')
      .map((module) => ({ moduleId: module.id, kind: module.kind, actionSchema: actionSchema(module.kind) }));
  }

  globalView() {
    return {
      type: 'global_view',
      phase: this.phase(),
      now: Date.now(),
      started: Boolean(this.startedAt),
      finished: Boolean(this.finishedAt),
      timeRemainingMs: this.startedAt ? Math.max(0, this.startedAt + this.durationMs - Date.now()) : this.durationMs,
      players: this.players,
      lobby: this.lobbyView(),
      scores: this.scores,
      communicationGraph: this.communicationGraph,
      hintGraph: this.hintGraph,
      bombs: this.bombs.map((bomb) => ({ ...bomb, modules: visibleBombModules(bomb.modules).map(publicModule) })),
      recentEvents: this.events.slice(-60),
    };
  }

  phase() {
    if (this.finishedAt) return 'finished';
    if (this.startedAt) return 'playing';
    return 'lobby';
  }

  lobbyView() {
    return {
      connected: this.players.map((_, slot) => this.playerSockets.has(slot)),
      ready: this.players.map((_, slot) => this.readySlots.has(slot)),
      connectedCount: this.playerSockets.size,
      readyCount: this.readySlots.size,
      requiredCount: this.players.length,
    };
  }

  results() {
    return {
      scores: this.scores.map((score) => Number(score.toFixed(2))),
      survived: this.bombs.map((bomb) => !bomb.detonated),
      detonated: this.bombs.map((bomb) => bomb.detonated),
      modules_solved: this.bombs.map((bomb) => bomb.modules.filter((module) => module.status === 'solved').length),
      modules_failed: this.bombs.map((bomb) => bomb.modules.filter((module) => ['failed', 'expired'].includes(module.status)).length),
      rps_outcomes: this.events
        .filter((event) => ['rps_draw', 'rps_win', 'rps_autopass'].includes(event.type))
        .map((event) => ({ type: event.type, ...event.data })),
      hint_recoveries: this.recoveredHints.map((hints) => hints.length),
      duration_seconds: Math.round(((this.finishedAt ?? Date.now()) - (this.startedAt ?? Date.now())) / 1000),
    };
  }

  sendPlayerView(slot) {
    this.playerSockets.get(slot)?.sendJson({ type: 'view', view: this.viewFor(slot) });
  }

  sendGlobal() {
    const message = { type: 'global', state: this.globalView() };
    for (const socket of this.globalSockets) socket.sendJson(message);
    for (const socket of this.adminSockets) socket.sendJson({ type: 'admin', state: message.state });
  }

  broadcast() {
    for (let slot = 0; slot < this.players.length; slot += 1) this.sendPlayerView(slot);
    this.sendGlobal();
  }

  record(type, data) {
    this.events.push({ at: Date.now(), type, data });
  }
}

export function normalizeConfig(config) {
  const players = config.players?.length ? config.players : defaultPlayers(config.tokens?.length ?? 6);
  const communicationGraph = config.communication_graph ?? { type: 'circle', radius: 2 };
  const hintGraph = config.hint_graph ?? communicationGraph;
  return {
    tokens: config.tokens ?? players.map((_, slot) => `dev-token-${slot}`),
    players,
    seed: config.seed ?? 'liarliar',
    duration_seconds: Number(config.duration_seconds ?? 300),
    tick_rate: Number(config.tick_rate ?? 1),
    player_connect_timeout_seconds: Number(config.player_connect_timeout_seconds ?? 180),
    hint_redundancy: Number(config.hint_redundancy ?? 1.3),
    communication_graph: communicationGraph,
    hint_graph: hintGraph,
  };
}

function actionSchema(kind) {
  return getModule(kind)?.actionSchema ?? {};
}

function moduleAddressed(module) {
  return module.utility || module.status !== 'active' || Boolean(getModule(module.kind)?.addressed?.(module));
}

function shouldDetonateAtFinalization(module) {
  if (module.status !== 'active' || !module.lethal) return false;
  return getModule(module.kind)?.detonatesAtFinalization?.(module) ?? true;
}

function visibleBombModules(modules) {
  const byKind = new Map();
  for (const module of modules) {
    const existing = byKind.get(module.kind);
    if (!existing || module.instance > existing.instance) byKind.set(module.kind, module);
  }
  return [...byKind.values()].sort((a, b) => moduleOrder(a.kind) - moduleOrder(b.kind) || a.kind.localeCompare(b.kind));
}

function safeJson(raw) {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function publicHint(hint, source) {
  const { data, ...rest } = hint;
  void data;
  return { ...rest, source };
}
