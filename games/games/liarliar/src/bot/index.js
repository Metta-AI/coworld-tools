import { scriptedDecisions } from './brain.js';
import { llmDecisions, llmTelemetry } from './llm.js';

const mode = process.env.BOT_MODE ?? 'scripted';
const url = process.env.COGAMES_ENGINE_WS_URL;
if (!url) throw new Error('COGAMES_ENGINE_WS_URL is required');
const slot = slotFromUrl(url);
const label = slot === null ? 'bot' : `P${slot + 1}`;
const llmInfo = llmTelemetry();

const sharedHintIds = new Set();
let lastActionAt = 0;
let finishing = false;
let readySent = false;

log('start', { mode, provider: llmInfo.provider, model: llmInfo.model });

const ws = new WebSocket(url);
ws.addEventListener('message', async (event) => {
  const message = JSON.parse(event.data);
  if (message.type === 'final') {
    finishing = true;
    ws.close();
    return;
  }
  if (message.type !== 'view') return;
  const now = Date.now();
  if (now - lastActionAt < 750 && message.view?.phase !== 'lobby') return;
  lastActionAt = now;
  const { decisions, source, elapsedMs, error } = await chooseDecisions(message.view);
  if (error) log('llm_error_fallback', { error, fallbackActions: decisions.length });
  if (decisions.length > 0) log('decisions', { source, elapsedMs, actions: summarizeDecisions(decisions) });
  for (const decision of decisions.slice(0, 4)) {
    ws.send(JSON.stringify(decision));
  }
});

ws.addEventListener('close', () => process.exit(0));
ws.addEventListener('error', (error) => {
  if (!finishing) {
    console.error(error.message ?? error);
    process.exit(1);
  }
});

async function chooseDecisions(view) {
  if (view?.phase === 'lobby') {
    if (readySent || view.ready) return { decisions: [], source: 'scripted_lobby', elapsedMs: 0 };
    readySent = true;
    return { decisions: scriptedDecisions(view, sharedHintIds), source: 'scripted_lobby', elapsedMs: 0 };
  }
  if (mode !== 'llm') {
    return { decisions: scriptedDecisions(view, sharedHintIds), source: 'scripted', elapsedMs: 0 };
  }
  const started = Date.now();
  try {
    return { decisions: await llmDecisions(view), source: 'llm', elapsedMs: Date.now() - started };
  } catch (error) {
    return {
      decisions: scriptedDecisions(view, sharedHintIds),
      source: 'scripted_fallback',
      elapsedMs: Date.now() - started,
      error: formatError(error),
    };
  }
}

function summarizeDecisions(decisions) {
  return decisions.slice(0, 4).map((decision) => {
    if (decision.type === 'operate') return `operate:${decision.moduleId}`;
    if (decision.type === 'chat') return `chat:P${Number(decision.to) + 1}`;
    if (decision.type === 'calculate') return `calculate:${decision.code}`;
    return decision.type;
  });
}

function log(event, data = {}) {
  console.error(`[bot ${label}] ${event} ${JSON.stringify({ at: new Date().toISOString(), ...data })}`);
}

function formatError(error) {
  const message = error?.message ?? String(error);
  return message.replace(/\s+/g, ' ').trim().slice(0, 600);
}

function slotFromUrl(value) {
  try {
    const parsed = new URL(value);
    const slotValue = Number(parsed.searchParams.get('slot'));
    return Number.isInteger(slotValue) ? slotValue : null;
  } catch {
    return null;
  }
}
