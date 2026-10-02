import assert from "node:assert/strict";
import { createServer } from "node:http";
import { LlmClient } from "../bots/llm_client.js";

const requests: { path: string; headers: Record<string, unknown>; body: any }[] = [];
const server = createServer(async (req, res) => {
  let text = "";
  for await (const chunk of req) text += chunk;
  requests.push({ path: req.url!, headers: req.headers, body: JSON.parse(text) });
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify({ choices: [{ message: { content: "Meet Demeter", tool_calls: [{ id: "tool1", function: { name: "tasks", arguments: '{"goal":"find partner"}' } }] }, finish_reason: "tool_calls" }], usage: { prompt_tokens: 2, completion_tokens: 3, total_tokens: 5 } }));
});
await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
const address = server.address() as { port: number };
process.env.COWORLD_LLM_ENDPOINT = `http://127.0.0.1:${address.port}`;
process.env.COWORLD_LLM_MODEL = "anthropic/claude-haiku-4.5";
process.env.AWS_ENDPOINT_URL_BEDROCK_RUNTIME = "http://127.0.0.1:1";
delete process.env.AWS_ACCESS_KEY_ID;
delete process.env.AWS_SECRET_ACCESS_KEY;
try {
  const client = new LlmClient("us-west-2");
  const result = await client.complete({
    modelId: "us.anthropic.claude-sonnet-4-6", system: [{ text: "Play" }],
    messages: [
      { role: "user", content: [{ text: "Start" }] },
      { role: "assistant", content: [{ toolUse: { toolUseId: "prior", name: "tasks", input: { goal: "explore" } } }] },
      { role: "user", content: [{ toolResult: { toolUseId: "prior", content: [{ json: { ok: true } }] } }] },
    ],
    toolConfig: { tools: [{ toolSpec: { name: "tasks", inputSchema: { json: { type: "object" } } } }] },
    inferenceConfig: { maxTokens: 800, temperature: 0.3 },
  });
  assert.equal(result.output!.message!.content![1].toolUse!.name, "tasks");
  assert.deepEqual(result.output!.message!.content![1].toolUse!.input, { goal: "find partner" });
  assert.equal(result.stopReason, "tool_use");
  assert.equal(result.usage!.totalTokens, 5);
  assert.equal(requests[0].path, "/v1/chat/completions");
  assert.equal(requests[0].headers["x-coworld-player-slot"], undefined);
  assert.equal(requests[0].body.model, "anthropic/claude-haiku-4.5");
  assert.equal(requests[0].body.messages[3].role, "tool");
  assert.equal(requests[0].body.messages[3].tool_call_id, "prior");
  assert.equal(requests[0].body.tools[0].function.name, "tasks");
  delete process.env.COWORLD_LLM_MODEL;
  await client.complete({ messages: [{ role: "user", content: [{ text: "Observe" }] }] });
  assert.equal(requests[1].body.model, "anthropic/claude-sonnet-4.6");
  await assert.rejects(client.complete({ messages: [] }, { abortSignal: AbortSignal.abort() }));
  console.log("native player, observer, skill transport and tool roundtrip passed");
} finally {
  server.closeAllConnections();
  await new Promise<void>(resolve => server.close(() => resolve()));
}
