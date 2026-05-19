import { mkdir, writeFile } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { defaultPlayers } from './graph.js';
import { startServer } from './server.js';

const LOCAL_DIR = resolve('.local');
const options = parseArgs(process.argv.slice(2));
const playerCount = options.players;
const PORT = Number(options.port ?? process.env.PORT ?? 8080);

const tokens = Array.from({ length: playerCount }, (_, slot) => `local-token-${slot}-${Math.random().toString(36).slice(2)}`);
const config = {
  seed: process.env.SEED ?? 'local',
  duration_seconds: Number(process.env.DURATION_SECONDS ?? 300),
  tick_rate: 1,
  player_connect_timeout_seconds: Number(process.env.PLAYER_CONNECT_TIMEOUT_SECONDS ?? 300),
  hint_redundancy: Number(process.env.HINT_REDUNDANCY ?? 1.3),
  tokens,
  players: defaultPlayers(playerCount),
  communication_graph: defaultGraph(playerCount),
  hint_graph: defaultGraph(playerCount),
};

await mkdir(LOCAL_DIR, { recursive: true });
const configPath = resolve(LOCAL_DIR, 'config.json');
const resultsPath = resolve(LOCAL_DIR, 'results.json');
const replayPath = resolve(LOCAL_DIR, 'replay.json');
const sessionPath = resolve(LOCAL_DIR, 'session.json');
const session = {
  port: PORT,
  players: tokens.map((token, slot) => ({
    slot,
    token,
    url: `http://127.0.0.1:${PORT}/clients/player?slot=${slot}&token=${encodeURIComponent(token)}`,
    wsUrl: `ws://127.0.0.1:${PORT}/player?slot=${slot}&token=${encodeURIComponent(token)}`,
  })),
  globalUrl: `http://127.0.0.1:${PORT}/clients/global`,
  adminUrl: `http://127.0.0.1:${PORT}/clients/admin`,
  replayPath,
};
await writeFile(configPath, JSON.stringify(config, null, 2));
await writeFile(sessionPath, JSON.stringify(session, null, 2));

process.env.COGAME_CONFIG_URI = pathToFileURL(configPath).href;
process.env.COGAME_RESULTS_URI = pathToFileURL(resultsPath).href;
process.env.COGAME_SAVE_REPLAY_URI = pathToFileURL(replayPath).href;
process.env.PORT = String(PORT);
process.env.HOST = process.env.HOST ?? '127.0.0.1';

await startServer({ keepAlive: true });

const botSlots = botSlotsFor(options.bots, playerCount, options.humanSlot);
const children = startBots(botSlots, options.botMode, session.players);

console.log(`Liar Liar, Cut the Wire! running at http://127.0.0.1:${PORT}`);
console.log(`Global: http://127.0.0.1:${PORT}/clients/global`);
console.log(`Admin:  http://127.0.0.1:${PORT}/clients/admin`);
if (botSlots.size > 0) console.log(`Bots:   ${[...botSlots].map((slot) => `P${slot + 1}`).join(', ')} (${options.botMode})`);
const humanSlots = session.players.map((player) => player.slot).filter((slot) => !botSlots.has(slot));
for (const slot of humanSlots) {
  console.log(`P${slot + 1}:   ${session.players[slot].url}`);
}
if (humanSlots.length === 0) console.log('Humans: none; use the global link to observe the bot game.');

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    for (const child of children) child.kill(signal);
    process.exit(signal === 'SIGINT' ? 130 : 143);
  });
}

function parseArgs(args) {
  const parsed = {
    players: Number(process.env.PLAYERS ?? 6),
    bots: process.env.BOTS ?? '0',
    botMode: process.env.BOT_MODE ?? 'scripted',
    humanSlot: Number(process.env.HUMAN_SLOT ?? 0),
    port: undefined,
  };
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === '--players') parsed.players = Number(args[++index]);
    else if (arg === '--bots') parsed.bots = args[++index];
    else if (arg === '--bot-mode') parsed.botMode = args[++index];
    else if (arg === '--human-slot') parsed.humanSlot = Number(args[++index]);
    else if (arg === '--port') parsed.port = Number(args[++index]);
    else if (arg === '--help') {
      printHelp();
      process.exit(0);
    }
  }
  if (!Number.isInteger(parsed.players) || parsed.players < 1) throw new Error('--players must be a positive integer');
  if (!['scripted', 'llm'].includes(parsed.botMode)) throw new Error('--bot-mode must be scripted or llm');
  if (!Number.isInteger(parsed.humanSlot) || parsed.humanSlot < 0 || parsed.humanSlot >= parsed.players) {
    throw new Error('--human-slot must be a valid zero-based player slot');
  }
  return parsed;
}

function botSlotsFor(value, count, humanSlot) {
  const normalized = String(value ?? '0').toLowerCase();
  let slots;
  if (['0', 'none', 'human', 'humans'].includes(normalized)) slots = [];
  else if (['n-1', 'all-but-one', 'all_but_one', 'one-human'].includes(normalized)) {
    slots = Array.from({ length: count }, (_, slot) => slot).filter((slot) => slot !== humanSlot);
  } else if (['n', 'all'].includes(normalized)) slots = Array.from({ length: count }, (_, slot) => slot);
  else if (/^\d+$/.test(normalized)) slots = Array.from({ length: Math.min(Number(normalized), count) }, (_, slot) => slot);
  else throw new Error('--bots must be 0, n-1, n, none, all-but-one, all, or a numeric count');
  return new Set(slots);
}

function startBots(botSlots, mode, players) {
  const children = [];
  for (const slot of botSlots) {
    const child = spawn(process.execPath, ['src/bot/index.js'], {
      stdio: 'inherit',
      env: {
        ...process.env,
        BOT_MODE: mode,
        COGAMES_ENGINE_WS_URL: players[slot].wsUrl,
      },
    });
    children.push(child);
  }
  return children;
}

function defaultGraph(count) {
  return { type: 'circle', radius: count > 1 ? Math.min(2, Math.floor(count / 2)) : 0 };
}

function printHelp() {
  console.log(`Usage: npm run dev -- [options]

Options:
  --players N              Number of fixed player slots (default: 6)
  --bots 0|n-1|n           Auto-connect no bots, all but one slot, or every slot (default: 0)
  --bot-mode scripted|llm  Bot implementation to use (default: scripted)
  --human-slot SLOT        Zero-based slot kept human when --bots n-1 (default: 0)
  --port PORT              Local HTTP port (default: PORT env or 8080)

Examples:
  npm run dev -- --bots 0
  npm run dev -- --bots n-1 --bot-mode llm
  npm run dev -- --bots n --bot-mode scripted
`);
}
