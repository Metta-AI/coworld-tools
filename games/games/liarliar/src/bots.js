import { readFile } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { resolve } from 'node:path';

const modeArg = process.argv.includes('--mode') ? process.argv[process.argv.indexOf('--mode') + 1] : 'scripted';
const onlySlots = parseSlotList(valueAfter('--slots') ?? process.env.BOT_SLOTS);
const excludeSlots = parseSlotList(valueAfter('--exclude-slot') ?? process.env.BOT_EXCLUDE_SLOTS);
const session = JSON.parse(await readFile(resolve('.local/session.json'), 'utf8'));
const children = [];

for (const player of session.players.filter(shouldRunBot)) {
  const child = spawn(process.execPath, ['src/bot/index.js'], {
    stdio: 'inherit',
    env: {
      ...process.env,
      BOT_MODE: modeArg,
      COWORLD_PLAYER_WS_URL: player.wsUrl,
    },
  });
  children.push(child);
}

process.on('SIGINT', () => {
  for (const child of children) child.kill('SIGINT');
  process.exit(130);
});

await Promise.all(children.map((child) => new Promise((resolveChild) => child.on('exit', resolveChild))));

function valueAfter(flag) {
  const index = process.argv.indexOf(flag);
  return index >= 0 ? process.argv[index + 1] : undefined;
}

function parseSlotList(value) {
  if (!value) return null;
  return new Set(
    String(value)
      .split(',')
      .map((part) => Number(part.trim()))
      .filter(Number.isInteger),
  );
}

function shouldRunBot(player) {
  if (onlySlots && !onlySlots.has(player.slot)) return false;
  if (excludeSlots && excludeSlots.has(player.slot)) return false;
  return true;
}
