import { BedrockRuntimeClient, ConverseCommand, type ConverseCommandInput, type ConverseCommandOutput, type ContentBlock } from "@aws-sdk/client-bedrock-runtime";

interface ChatResponse {
  choices: { message: { content: string | null; tool_calls?: { id: string; function: { name: string; arguments: string } }[] }; finish_reason: string }[];
  usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
}

/** Shared inference transport for the player, observer, and skills. */
export class LlmClient {
  private readonly endpoint = process.env.COWORLD_LLM_ENDPOINT;
  private readonly local: BedrockRuntimeClient | undefined;

  constructor(region: string) {
    if (!this.endpoint) this.local = new BedrockRuntimeClient({ region });
  }

  async complete(input: ConverseCommandInput, options: { abortSignal?: AbortSignal } = {}): Promise<ConverseCommandOutput> {
    if (!this.endpoint) return this.local!.send(new ConverseCommand(input), options);
    const messages: object[] = [{ role: "system", content: input.system?.map(block => block.text ?? "").join("\n") ?? "" }];
    for (const message of input.messages ?? []) {
      const text = (message.content ?? []).filter(block => block.text !== undefined).map(block => block.text).join("\n");
      const calls = (message.content ?? []).filter(block => block.toolUse).map(block => ({
        id: block.toolUse!.toolUseId, type: "function", function: { name: block.toolUse!.name, arguments: JSON.stringify(block.toolUse!.input) },
      }));
      if (text || calls.length) messages.push({ role: message.role, content: text || null, ...(calls.length ? { tool_calls: calls } : {}) });
      for (const block of message.content ?? []) {
        if (block.toolResult) messages.push({ role: "tool", tool_call_id: block.toolResult.toolUseId, content: block.toolResult.content!.map(item => item.text ?? JSON.stringify(item.json)).join("\n") });
      }
    }
    const body = {
      model: process.env.COWORLD_LLM_MODEL ?? "anthropic/claude-sonnet-4.6",
      messages,
      max_tokens: input.inferenceConfig?.maxTokens,
      temperature: input.inferenceConfig?.temperature,
      ...(input.toolConfig ? { tools: input.toolConfig.tools!.map(tool => ({ type: "function", function: { name: tool.toolSpec!.name, description: tool.toolSpec!.description, parameters: tool.toolSpec!.inputSchema!.json } })) } : {}),
    };
    const response = await fetch(`${this.endpoint.replace(/\/$/, "")}/v1/chat/completions`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: options.abortSignal,
    });
    if (!response.ok) throw new Error(`Coworld LLM ${response.status}: ${await response.text()}`);
    const result: ChatResponse = await response.json();
    const choice = result.choices[0];
    const content: ContentBlock[] = [];
    if (choice.message.content) content.push({ text: choice.message.content });
    for (const call of choice.message.tool_calls ?? []) content.push({ toolUse: { toolUseId: call.id, name: call.function.name, input: JSON.parse(call.function.arguments) } });
    return { $metadata: {}, output: { message: { role: "assistant", content } }, stopReason: choice.finish_reason === "tool_calls" ? "tool_use" : "end_turn", usage: { inputTokens: result.usage.prompt_tokens, outputTokens: result.usage.completion_tokens, totalTokens: result.usage.total_tokens }, metrics: { latencyMs: 0 } };
  }
}
