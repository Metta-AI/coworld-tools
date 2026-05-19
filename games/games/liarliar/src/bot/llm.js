import { mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

export async function llmDecisions(view) {
  const provider = process.env.BOT_PROVIDER ?? 'bedrock';
  const prompt = buildPrompt(view);
  const text = provider === 'openai' ? await openAiCompatible(prompt) : await bedrockClaude(prompt);
  const parsed = parseJsonBlock(text);
  return Array.isArray(parsed) ? parsed.filter(isDecision) : [];
}

export function llmTelemetry() {
  const provider = process.env.BOT_PROVIDER ?? 'bedrock';
  return {
    provider,
    model: provider === 'openai' ? process.env.OPENAI_MODEL : bedrockModelId(),
  };
}

function buildPrompt(view) {
  return [
    'You are playing Liar Liar, Cut the Wire. Respond only with a JSON array of actions.',
    'Allowed action shapes:',
    '{"type":"ready","ready":true}',
    '{"type":"chat","to":1,"text":"..."}',
    '{"type":"calculate","code":"0000"}',
    '{"type":"operate","moduleId":"...","action":{...}}',
    'Use only direct neighbors. If communicating hints, write them as ordinary chat text. Solve from visible hints. Do not invent hidden information.',
    JSON.stringify(view),
  ].join('\n\n');
}

async function openAiCompatible(prompt) {
  const baseUrl = process.env.OPENAI_BASE_URL ?? 'https://api.openai.com/v1';
  const model = process.env.OPENAI_MODEL;
  const apiKey = process.env.OPENAI_API_KEY;
  if (!model || !apiKey) throw new Error('OPENAI_MODEL and OPENAI_API_KEY are required');
  const response = await fetch(`${baseUrl.replace(/\/$/, '')}/chat/completions`, {
    method: 'POST',
    headers: { authorization: `Bearer ${apiKey}`, 'content-type': 'application/json' },
    body: JSON.stringify({
      model,
      messages: [{ role: 'user', content: prompt }],
      temperature: 0,
    }),
  });
  if (!response.ok) throw new Error(`OpenAI-compatible request failed: ${response.status}`);
  const data = await response.json();
  return data.choices?.[0]?.message?.content ?? '';
}

async function bedrockClaude(prompt) {
  const modelId = bedrockModelId();
  const workdir = await mkdtemp(join(tmpdir(), 'liarliar-bedrock-'));
  const inputPath = join(workdir, 'input.json');
  const outputPath = join(workdir, 'output.json');
  await writeFile(
    inputPath,
    JSON.stringify({
      anthropic_version: 'bedrock-2023-05-31',
      max_tokens: 1200,
      temperature: 0,
      messages: [{ role: 'user', content: [{ type: 'text', text: prompt }] }],
    }),
  );
  const result = spawnSync(
    'aws',
    [
      'bedrock-runtime',
      'invoke-model',
      '--model-id',
      modelId,
      '--body',
      `file://${inputPath}`,
      '--cli-binary-format',
      'raw-in-base64-out',
      outputPath,
    ],
    { encoding: 'utf8' },
  );
  if (result.status !== 0) throw new Error(result.stderr || 'aws bedrock-runtime invoke-model failed');
  const data = JSON.parse(await readFile(outputPath, 'utf8'));
  return data.content?.map((part) => part.text ?? '').join('\n') ?? '';
}

function bedrockModelId() {
  const raw = process.env.BEDROCK_MODEL_ID ?? 'global.anthropic.claude-sonnet-4-5-20250929-v1:0';
  if (raw === 'anthropic.claude-sonnet-4-5-20250929-v1:0') return 'global.anthropic.claude-sonnet-4-5-20250929-v1:0';
  return raw;
}

function parseJsonBlock(text) {
  const trimmed = text.trim();
  try {
    return JSON.parse(trimmed);
  } catch {
    const match = /```(?:json)?\s*([\s\S]*?)```/.exec(trimmed) ?? /(\[[\s\S]*\])/.exec(trimmed);
    if (!match) return [];
    return JSON.parse(match[1]);
  }
}

function isDecision(value) {
  return value && ['ready', 'chat', 'calculate', 'operate'].includes(value.type);
}
