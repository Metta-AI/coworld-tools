import type { CogAction, CogDecisionInput, DebateTactic } from "../../shared/types.js";
import type { CogController } from "./cog-controller.js";
import { buildControllerDecisionPrompt, controllerDecisionChoices, type ControllerDecisionChoice } from "./decision-prompt.js";
import { fallbackTacticForCog } from "./fallback-tactic.js";

export type LlmFetch = (input: string | URL, init?: RequestInit) => Promise<Response>;

export type LlmControllerConfig = {
  apiKey?: string;
  baseUrl?: string;
  disabledReason?: string;
  fetch?: LlmFetch;
  model?: string;
  strict?: boolean;
  timeoutMs?: number;
};

const ANTHROPIC_API_VERSION = "2023-06-01";
const DEFAULT_ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages";
const DEFAULT_MODEL = "claude-haiku-4-5-20251001";
const DEFAULT_TIMEOUT_MS = 5_000;
const DEFAULT_MAX_TOKENS = 320;

export class LlmController implements CogController {
  private readonly apiKey: string | undefined;
  private readonly baseUrl: string;
  private readonly fetch: LlmFetch;
  private readonly model: string;
  private readonly strict: boolean;
  private readonly timeoutMs: number;

  constructor(config: LlmControllerConfig) {
    this.apiKey = nonEmpty(config.apiKey);
    this.baseUrl = config.baseUrl ?? DEFAULT_ANTHROPIC_MESSAGES_URL;
    this.fetch = config.fetch ?? fetch;
    this.model = normalizeAnthropicModelId(config.model ?? DEFAULT_MODEL);
    this.strict = config.strict ?? false;
    this.timeoutMs = config.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  }

  async decide(input: CogDecisionInput): Promise<CogAction> {
    let responseBody: unknown;
    try {
      responseBody = await this.requestDecision(input);
    } catch (error) {
      const message = requestErrorMessage(error, this.timeoutMs);
      if (this.strict) {
        throw new Error(message, { cause: error });
      }
      return providerFailureAction(input, message);
    }

    if (!responseBody) {
      if (this.strict) {
        throw new Error("Anthropic response was not valid JSON");
      }
      return invalidProviderAction(input);
    }

    try {
      const action = actionFromProviderText(extractProviderText(responseBody), input, this.strict);
      if (!action && this.strict) {
        throw new Error("LLM response did not include a legal action");
      }
      return action ?? invalidProviderAction(input);
    } catch (error) {
      if (this.strict) {
        throw error;
      }
      return invalidProviderAction(input);
    }
  }

  private async requestDecision(input: CogDecisionInput): Promise<unknown> {
    if (!this.apiKey) {
      throw new Error("Anthropic API key is not configured");
    }

    const abortController = new AbortController();
    let timeout: ReturnType<typeof setTimeout> | undefined;
    const timeoutPromise = new Promise<never>((_resolve, reject) => {
      timeout = setTimeout(() => {
        abortController.abort();
        reject(providerTimeoutError(this.timeoutMs));
      }, this.timeoutMs);
    });

    try {
      const requestPromise = this.fetch(this.baseUrl, {
        method: "POST",
        headers: {
          accept: "application/json",
          "anthropic-version": ANTHROPIC_API_VERSION,
          "content-type": "application/json",
          "x-api-key": this.apiKey,
        },
        body: JSON.stringify(providerRequestBody(input, this.model)),
        signal: abortController.signal,
      });
      const response = await Promise.race([requestPromise, timeoutPromise]);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${trimErrorDetail(await response.text())}`);
      }

      try {
        return (await response.json()) as unknown;
      } catch {
        return undefined;
      }
    } finally {
      if (timeout) {
        clearTimeout(timeout);
      }
    }
  }
}

function nonEmpty(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed || undefined;
}

function normalizeAnthropicModelId(model: string): string {
  const trimmed = model.trim();
  const vertexModel = normalizedVertexAnthropicModelId(trimmed);
  return (vertexModel ?? trimmed)
    .replace(/^(?:global|us|eu|au|apac|jp)\.anthropic\./, "")
    .replace(/^anthropic\./, "")
    .replace(/-v1:0$/, "");
}

function normalizedVertexAnthropicModelId(model: string): string | undefined {
  const match = model.match(/^(claude-.+)@(\d{8})$/);
  return match ? `${match[1]}-${match[2]}` : undefined;
}

function providerRequestBody(input: CogDecisionInput, model: string): Record<string, unknown> {
  return {
    model,
    system: [
      "You are the Cogshambo decision engine.",
      "Choose exactly one legal action for this tick using only the supplied local observation.",
      "The prompt lists legal actions as a numbered multiple choice list under Pick an action.",
      "Return `Thoughts:` with brief reasoning, then `Choice:` with one legal action number.",
      "Always include a non-empty `Thoughts:` section before `Choice:`.",
      "If a debate prompt includes Random and you need randomness, choose Random.",
      "Do not return JSON.",
      "Debate tactics are exactly reason, spin, and passion. Do not use actually, vibes, lore, or talk-to-the-hand.",
    ].join(" "),
    messages: [{ role: "user", content: buildControllerDecisionPrompt(input) }],
    max_tokens: DEFAULT_MAX_TOKENS,
    temperature: 0.35,
  };
}

function actionFromProviderText(text: string, input: CogDecisionInput, strict = false): CogAction | undefined {
  const choices = controllerDecisionChoices(input);
  if (choices.length === 0) {
    return undefined;
  }

  const parsed = parseProviderDecision(text);
  if (strict && !parsed.thoughts) {
    throw new Error("LLM response missing Thoughts");
  }

  const choiceNumber = parsed.choiceNumber;
  if (choiceNumber !== undefined && choiceNumber >= 1 && choiceNumber <= choices.length) {
    return actionForProviderChoice(choices[choiceNumber - 1], choiceNumber, parsed.thoughts);
  }

  const labelChoiceIndex = choiceIndexFromLabel(parsed.choiceText, choices);
  if (labelChoiceIndex !== undefined) {
    return actionForProviderChoice(choices[labelChoiceIndex], labelChoiceIndex + 1, parsed.thoughts);
  }

  const reason = choiceNumber === undefined ? "missing choice number" : `invalid choice ${choiceNumber}`;
  if (strict) {
    throw new Error(`LLM returned ${reason}`);
  }
  return randomChoiceAction(choices, reason, parsed.thoughts);
}

function parseProviderDecision(text: string): { choiceNumber: number | undefined; choiceText: string | undefined; thoughts: string | undefined } {
  const trimmed = text.trim();
  return {
    choiceNumber: parseChoiceNumber(trimmed),
    choiceText: parseChoiceText(trimmed),
    thoughts: parseThoughts(trimmed),
  };
}

function parseChoiceNumber(text: string): number | undefined {
  const choiceMatch = text.match(/(?:^|\n)\s*Choice:\s*#?\s*(\d+)\b/i);
  const directNumberMatch = text.match(/^#?\s*(\d+)\b/i);
  const token = choiceMatch?.[1] ?? directNumberMatch?.[1];
  if (!token) {
    return undefined;
  }

  return Number.parseInt(token, 10);
}

function parseChoiceText(text: string): string | undefined {
  const match = text.match(/(?:^|\n)\s*Choice:\s*(.+?)(?=\n|$)/i);
  return match?.[1]?.trim() || undefined;
}

function parseThoughts(text: string): string | undefined {
  const match = text.match(/(?:^|\n)\s*Thoughts:\s*([\s\S]*?)(?=\n\s*Choice:|\s*$)/i);
  const thoughts = match?.[1]?.trim();
  return thoughts || undefined;
}

function choiceIndexFromLabel(choiceText: string | undefined, choices: ControllerDecisionChoice[]): number | undefined {
  if (!choiceText) {
    return undefined;
  }

  const normalizedChoice = normalizeChoiceLabel(choiceText);
  const index = choices.findIndex((choice) => normalizedChoice.startsWith(normalizeChoiceLabel(choice.label)));
  return index === -1 ? undefined : index;
}

function normalizeChoiceLabel(label: string): string {
  return label
    .replace(/^#?\d+[.)]?\s*/, "")
    .replace(/[.。]+$/, "")
    .trim()
    .toLowerCase();
}

function extractProviderText(body: unknown): string {
  if (!body || typeof body !== "object") {
    return "";
  }

  const record = body as Record<string, unknown>;
  const anthropicText = outputTextFromAnthropicContent(record.content);
  if (anthropicText) {
    return anthropicText;
  }

  return "";
}

function outputTextFromAnthropicContent(content: unknown): string {
  if (!Array.isArray(content)) {
    return "";
  }

  return content
    .flatMap((part) => {
      if (!part || typeof part !== "object") {
        return [];
      }

      const block = part as Record<string, unknown>;
      return block.type === "text" && typeof block.text === "string" ? [block.text] : [];
    })
    .join("\n");
}

function requestErrorMessage(error: unknown, timeoutMs: number): string {
  if (error instanceof Error && error.name === "AbortError") {
    return `Anthropic request failed: timed out after ${timeoutMs}ms`;
  }

  return error instanceof Error ? `Anthropic request failed: ${error.message}` : "Anthropic request failed";
}

function providerTimeoutError(timeoutMs: number): Error {
  const error = new Error(`timed out after ${timeoutMs}ms`);
  error.name = "AbortError";
  return error;
}

function trimErrorDetail(detail: string): string {
  const trimmed = detail.trim().replace(/\s+/g, " ");
  return trimmed.length > 240 ? `${trimmed.slice(0, 237)}...` : trimmed;
}

function providerFailureAction(input: CogDecisionInput, message: string): CogAction {
  if (input.allowedActions.includes("chooseTactic") || input.observation.cog.debate) {
    const tactic = fallbackDebateTactic(input);
    return { type: "chooseTactic", tactic, intent: `${message}; defaulting to ${tactic}` };
  }

  return { type: "wait", intent: message };
}

function invalidProviderAction(input: CogDecisionInput): CogAction {
  const choices = controllerDecisionChoices(input);
  if (choices.length > 0) {
    return randomChoiceAction(choices, "invalid response");
  }

  if (input.allowedActions.includes("chooseTactic") || input.observation.cog.debate) {
    const tactic = fallbackDebateTactic(input);
    return {
      type: "chooseTactic",
      tactic,
      intent: `LLM returned invalid debate action; defaulting to ${tactic}`,
    };
  }

  return { type: "wait", intent: "LLM returned invalid action; defaulting to wait" };
}

function randomChoiceAction(choices: ControllerDecisionChoice[], reason: string, thoughts?: string): CogAction {
  const index = Math.min(choices.length - 1, Math.floor(Math.random() * choices.length));
  return {
    ...withIntent(actionForChoice(choices[index]), `LLM returned ${reason}; randomly selected option ${index + 1}`),
    choiceNumber: index + 1,
    ...(thoughts ? { thoughts } : {}),
  } as CogAction;
}

function cloneAction(action: CogAction): CogAction {
  return { ...action } as CogAction;
}

function withProviderDecisionMetadata(action: CogAction, choiceNumber: number, thoughts: string | undefined): CogAction {
  return {
    ...cloneAction(action),
    choiceNumber,
    ...(thoughts ? { thoughts } : {}),
  } as unknown as CogAction;
}

function actionForProviderChoice(choice: ControllerDecisionChoice, choiceNumber: number, thoughts: string | undefined): CogAction {
  return withProviderDecisionMetadata(actionForChoice(choice), choiceNumber, thoughts);
}

function actionForChoice(choice: ControllerDecisionChoice): CogAction {
  if (!choice.randomTactic) {
    return choice.action;
  }

  return { type: "chooseTactic", tactic: randomDebateTactic() };
}

function withIntent(action: CogAction, intent: string): CogAction {
  return { ...action, intent } as CogAction;
}

function fallbackDebateTactic(input: CogDecisionInput): DebateTactic {
  return fallbackTacticForCog(input.observation.cog);
}

function randomDebateTactic(): DebateTactic {
  const tactics: DebateTactic[] = ["reason", "spin", "passion"];
  return tactics[Math.min(tactics.length - 1, Math.floor(Math.random() * tactics.length))] ?? "reason";
}
