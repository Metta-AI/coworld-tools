import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { llmDecisions, llmTelemetry } from './src/bot/llm.js';

test('native sidecar overrides local provider settings and attributes the seat', async () => {
  const received = [];
  const server = createServer(async (req, res) => {
    let raw = '';
    for await (const chunk of req) raw += chunk;
    received.push({ path: req.url, slot: req.headers['x-coworld-player-slot'], body: JSON.parse(raw) });
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify({ content: [{ type: 'text', text: '[{"type":"ready","ready":true}]' }] }));
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const previous = { ...process.env };
  process.env.COWORLD_LLM_ENDPOINT = `http://127.0.0.1:${server.address().port}/`;
  process.env.COWORLD_LLM_MODEL = 'anthropic/claude-sonnet-4.6';
  process.env.BOT_PROVIDER = 'bedrock';
  try {
    assert.deepEqual(await llmDecisions({ slot: 2 }), [{ type: 'ready', ready: true }]);
    assert.deepEqual(llmTelemetry(), { provider: 'sidecar', model: 'anthropic/claude-sonnet-4.6' });
  } finally {
    process.env = previous;
    await new Promise((resolve) => server.close(resolve));
  }
  assert.equal(received.length, 1);
  assert.equal(received[0].path, '/v1/messages');
  assert.equal(received[0].slot, '2');
  assert.equal(received[0].body.model, 'anthropic/claude-sonnet-4.6');
  assert.equal('anthropic_version' in received[0].body, false);
});
