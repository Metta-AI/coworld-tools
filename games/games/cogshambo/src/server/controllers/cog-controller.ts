import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import type { CogAction, CogDecisionInput, ControllerId } from "../../shared/types.js";
import { LlmController, type LlmControllerConfig } from "./llm-controller.js";
import { StubController } from "./stub-controller.js";
import { WanderController } from "./wander-controller.js";

export interface CogController {
  decide(input: CogDecisionInput): Promise<CogAction>;
}

export type ControllerRegistry = Record<ControllerId, CogController>;

export type ControllerRegistryOptions = {
  requireLlm?: boolean;
  scriptLlm?: boolean;
};

const TEST_LIVE_ANTHROPIC_DISABLED_REASON = "Cogshambo requires Anthropic credentials for LLM decisions";

export function createControllerRegistry(options: ControllerRegistryOptions = {}): ControllerRegistry {
  const llmConfig = llmControllerConfigFromEnv();
  if (options.requireLlm) {
    assertLlmControllerConfig(llmConfig);
  }

  return {
    stub: new StubController(),
    wander: new WanderController(0xc09_5a4b0),
    llm: options.scriptLlm
      ? new WanderController(0xc09_11_4c)
      : new LlmController(llmConfig),
  };
}

type EnvSource = Record<string, string | undefined>;

export function llmControllerConfigFromEnv(env: EnvSource = process.env, envFilePath = path.resolve(".env")): LlmControllerConfig {
  if (env.NODE_ENV === "test" && env.COGSHAMBO_ENABLE_LIVE_LLM_TESTS !== "1") {
    return {
      disabledReason: TEST_LIVE_ANTHROPIC_DISABLED_REASON,
      apiKey: undefined,
      model: undefined,
      timeoutMs: undefined,
    };
  }

  const dotenv = readDotEnv(envFilePath);
  const value = (...keys: string[]): string | undefined => {
    for (const key of keys) {
      const candidate = env[key] ?? dotenv[key];
      if (candidate) {
        return candidate;
      }
    }

    return undefined;
  };

  return {
    apiKey: value("COGSHAMBO_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY", "COGSHAMBO_LLM_API_KEY"),
    model: value("COGSHAMBO_ANTHROPIC_MODEL", "ANTHROPIC_MODEL", "COGSHAMBO_LLM_MODEL"),
    timeoutMs: positiveInteger(value("COGSHAMBO_ANTHROPIC_TIMEOUT_MS", "COGSHAMBO_LLM_TIMEOUT_MS")),
  };
}

export function assertLlmControllerConfig(config: LlmControllerConfig): void {
  if (config.disabledReason) {
    throw new Error(`${config.disabledReason}. Use --scripted to run scripted controllers.`);
  }
  if (!config.apiKey?.trim()) {
    throw new Error("Cogshambo requires ANTHROPIC_API_KEY or COGSHAMBO_LLM_API_KEY for LLM decisions. Use --scripted to run scripted controllers.");
  }
}

function readDotEnv(envFilePath: string): EnvSource {
  if (!existsSync(envFilePath)) {
    return {};
  }

  const env: EnvSource = {};
  for (const line of readFileSync(envFilePath, "utf8").split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (!match?.[1]) {
      continue;
    }

    env[match[1]] = unquoteEnvValue(match[2] ?? "");
  }

  return env;
}

function unquoteEnvValue(value: string): string {
  const trimmed = value.trim();
  const quote = trimmed[0];
  if ((quote === '"' || quote === "'") && trimmed.endsWith(quote)) {
    return trimmed.slice(1, -1);
  }

  return trimmed;
}

function positiveInteger(value: string | undefined): number | undefined {
  if (value === undefined) {
    return undefined;
  }

  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
}
