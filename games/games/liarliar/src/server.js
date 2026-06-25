import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { LiarLiarGame } from './game.js';
import { readJson, writeJson } from './io.js';
import { handleUpgrade } from './ws.js';

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const PUBLIC = join(ROOT, 'public');

export async function startServer(options = {}) {
  const replayUri = process.env.COGAME_LOAD_REPLAY_URI ?? options.replayUri;
  const port = Number(process.env.COGAME_PORT ?? process.env.PORT ?? options.port ?? 8080);
  const host = process.env.COGAME_HOST ?? process.env.HOST ?? options.host ?? '0.0.0.0';
  if (replayUri) return startReplayServer(port, await readJson(replayUri));

  const configUri = process.env.COGAME_CONFIG_URI ?? options.configUri;
  const resultsUri = process.env.COGAME_RESULTS_URI ?? options.resultsUri;
  const saveReplayUri = process.env.COGAME_SAVE_REPLAY_URI ?? options.saveReplayUri;
  const resultsMethod = process.env.COGAME_RESULTS_METHOD ?? options.resultsMethod ?? 'POST';
  const saveReplayMethod = process.env.COGAME_SAVE_REPLAY_METHOD ?? options.saveReplayMethod ?? 'POST';
  const config = options.config ?? (configUri ? await readJson(configUri) : null);
  if (!config) throw new Error('Missing COGAME_CONFIG_URI or explicit config');

  const game = new LiarLiarGame(config, {
    writeResults: (results) => (resultsUri ? writeJson(resultsUri, results, resultsMethod) : Promise.resolve()),
    writeReplay: (replay) => (saveReplayUri ? writeJson(saveReplayUri, replay, saveReplayMethod) : Promise.resolve()),
  });

  const server = http.createServer((request, response) => routeHttp(request, response, game));
  server.on('upgrade', (request, socket, head) => {
    const url = new URL(request.url, 'http://localhost');
    if (url.pathname === '/player') {
      const slot = Number(url.searchParams.get('slot'));
      const token = url.searchParams.get('token') ?? '';
      if (!Number.isInteger(slot) || slot < 0 || slot >= game.players.length || game.config.tokens[slot] !== token) {
        socket.write('HTTP/1.1 403 Forbidden\r\n\r\n');
        socket.destroy();
        return;
      }
    }
    handleUpgrade(request, socket, head, {
      '/player': (ws, _request, url) => {
        const slot = Number(url.searchParams.get('slot'));
        const token = url.searchParams.get('token') ?? '';
        game.connectPlayer(slot, token, ws);
      },
      '/global': (ws) => game.connectGlobal(ws),
      '/admin': (ws) => game.connectAdmin(ws),
    });
  });

  game.on('finished', () => {
    if (!options.keepAlive) {
      setTimeout(() => server.close(() => process.exit(0)), 500);
    }
  });

  await listen(server, port, host);
  setTimeout(() => game.start(), game.config.player_connect_timeout_seconds * 1000).unref();
  return { server, game, port, host };
}

async function startReplayServer(port, replay) {
  const host = process.env.HOST ?? '0.0.0.0';
  const server = http.createServer((request, response) => routeReplayHttp(request, response));
  server.on('upgrade', (request, socket, head) => {
    handleUpgrade(request, socket, head, {
      '/replay': (ws) => {
        ws.sendJson({ type: 'replay', replay });
        ws.on('message', (raw) => ws.sendJson({ type: 'control', command: safeJson(raw) }));
      },
    });
  });
  await listen(server, port, host);
  return { server, replay, port, host };
}

function listen(server, port, host) {
  return new Promise((resolve, reject) => {
    const onError = (error) => reject(error);
    server.once('error', onError);
    server.listen(port, host, () => {
      server.off('error', onError);
      resolve();
    });
  });
}

async function routeHttp(request, response, game) {
  const url = new URL(request.url, 'http://localhost');
  try {
    if (url.pathname === '/healthz') return json(response, 200, { ok: true });
    if (url.pathname === '/client/player') return html(response, await readFile(join(PUBLIC, 'player.html'), 'utf8'));
    if (url.pathname === '/client/global') return html(response, await readFile(join(PUBLIC, 'global.html'), 'utf8'));
    if (url.pathname === '/client/admin') return html(response, await readFile(join(PUBLIC, 'admin.html'), 'utf8'));
    if (url.pathname === '/client/replay') return html(response, await readFile(join(PUBLIC, 'replay.html'), 'utf8'));
    if (url.pathname === '/client.js') return js(response, await readFile(join(PUBLIC, 'client.js'), 'utf8'));
    if (url.pathname === '/style.css') return css(response, await readFile(join(PUBLIC, 'style.css'), 'utf8'));
    if (url.pathname === '/state.json') return json(response, 200, game.globalView());
    return text(response, 404, 'Not found');
  } catch (error) {
    return text(response, 500, error.stack ?? String(error));
  }
}

async function routeReplayHttp(request, response) {
  const url = new URL(request.url, 'http://localhost');
  try {
    if (url.pathname === '/healthz') return json(response, 200, { ok: true });
    if (url.pathname === '/client/replay') return html(response, await readFile(join(PUBLIC, 'replay.html'), 'utf8'));
    if (url.pathname === '/client.js') return js(response, await readFile(join(PUBLIC, 'client.js'), 'utf8'));
    if (url.pathname === '/style.css') return css(response, await readFile(join(PUBLIC, 'style.css'), 'utf8'));
    return text(response, 404, 'Not found');
  } catch (error) {
    return text(response, 500, error.stack ?? String(error));
  }
}

function html(response, body) {
  response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
  response.end(body);
}

function js(response, body) {
  response.writeHead(200, { 'content-type': 'text/javascript; charset=utf-8' });
  response.end(body);
}

function css(response, body) {
  response.writeHead(200, { 'content-type': 'text/css; charset=utf-8' });
  response.end(body);
}

function json(response, status, value) {
  response.writeHead(status, { 'content-type': 'application/json; charset=utf-8' });
  response.end(JSON.stringify(value, null, 2));
}

function text(response, status, body) {
  response.writeHead(status, { 'content-type': 'text/plain; charset=utf-8' });
  response.end(body);
}

function safeJson(raw) {
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  startServer().catch((error) => {
    console.error(error);
    process.exit(1);
  });
}
