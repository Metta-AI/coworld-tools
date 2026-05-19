import { describe, expect, it, vi } from "vitest";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { DEFAULT_GAME_CONFIG, cloneGameConfig } from "../../src/shared/rules.js";
import type { CogDecisionInput } from "../../src/shared/types.js";
import { createControllerRegistry, llmControllerConfigFromEnv } from "../../src/server/controllers/cog-controller.js";
import { buildControllerDecisionPrompt } from "../../src/server/controllers/decision-prompt.js";
import { LlmController, type LlmFetch } from "../../src/server/controllers/llm-controller.js";
import { StubController } from "../../src/server/controllers/stub-controller.js";
import { WanderController } from "../../src/server/controllers/wander-controller.js";

const input: CogDecisionInput = {
  tick: 1,
  allowedActions: ["wait", "move"],
  observation: {
    dimensions: { width: 10, height: 10 },
    visibleEntities: [],
    visibleTerrain: [],
    visibleCells: [{ x: 1, y: 1 }],
    recentEvents: [],
    cog: {
      id: "cog_test",
      name: "Test",
      behaviorPrompt: "",
      position: { x: 1, y: 1 },
      spriteSheetKey: "cog-test",
      attributes: { energy: 5 },
      color: "red",
      defensiveTrait: "stubborn",
      activeTrait: "forceful",
      personalGoal: "majority",
      personalScore: 0,
      certainty: 100,
      controllerId: "stub",
      movementCooldown: 0,
      conversationLog: [],
    },
  },
};

const TEST_ANTHROPIC_API_KEY = "test-anthropic-key";

type AnthropicCall = {
  init: RequestInit;
  url: string;
};

function anthropicTextResponse(text: string): Response {
  return Response.json({ content: [{ type: "text", text }] });
}

function anthropicFetchForText(text: string, onInput?: (call: AnthropicCall) => void): LlmFetch {
  return async (url, init) => {
    onInput?.({ url: String(url), init: init ?? {} });
    return anthropicTextResponse(text);
  };
}

function anthropicRequestBody(call: AnthropicCall | undefined): Record<string, unknown> {
  return JSON.parse(String(call?.init.body)) as Record<string, unknown>;
}

describe("cog controllers", () => {
  it("stub controller returns a deterministic wait action", async () => {
    const action = await new StubController().decide(input);

    expect(action).toEqual({ type: "wait", intent: "observing" });
  });

  it("wander controller returns valid movement decisions", async () => {
    const controller = new WanderController(123);
    const action = await controller.decide(input);

    expect(["move", "wait"]).toContain(action.type);
  });

  it("wander controller returns wait when only wait is allowed", async () => {
    const controller = new WanderController(123);
    const action = await controller.decide({
      ...input,
      allowedActions: ["wait"],
    });

    expect(action.type).toBe("wait");
  });

  it("wander controller returns a valid move when only move is allowed", async () => {
    const controller = new WanderController(1972);
    const action = await controller.decide({
      ...input,
      allowedActions: ["move"],
    });

    expect(action.type).toBe("move");
    if (action.type !== "move") {
      throw new Error(`Expected move action, received ${action.type}`);
    }
    expect(["north", "south", "east", "west"]).toContain(action.direction);
  });

  it("wander controller does not choose debate targets when debate is available", async () => {
    const controller = new WanderController(123);
    const action = await controller.decide({
      ...input,
      allowedActions: ["wait", "move", "debate"],
      observation: {
        ...input.observation,
        visibleEntities: [
          {
            kind: "cog",
            id: "cog_neighbor",
            name: "Neighbor",
            position: { x: 2, y: 1 },
            color: "blue",
            spriteSheetKey: "cog-neighbor",
          },
        ],
      },
    });

    expect(action.type).not.toBe("debate");
  });

  it("wander controller does not debate same-team adjacent cogs", async () => {
    const controller = new WanderController(123);
    const action = await controller.decide({
      ...input,
      allowedActions: ["wait", "move", "debate"],
      observation: {
        ...input.observation,
        visibleEntities: [
          {
            kind: "cog",
            id: "cog_teammate",
            name: "Teammate",
            position: { x: 2, y: 1 },
            color: "red",
            spriteSheetKey: "cog-teammate",
          },
        ],
      },
    });

    expect(action.type).not.toBe("debate");
  });

  it("wander controller returns a debate tactic when debating", async () => {
    const controller = new WanderController(123);
    const action = await controller.decide({
      ...input,
      allowedActions: ["chooseTactic"],
      observation: {
        ...input.observation,
        cog: {
          ...input.observation.cog,
          debate: { opponentId: "cog_neighbor", startedTick: 0, nextRoundTick: 0, roundsResolved: 0 },
        },
      },
    });

    expect(action.type).toBe("chooseTactic");
    if (action.type !== "chooseTactic") {
      throw new Error(`Expected chooseTactic action, received ${action.type}`);
    }
    expect(["reason", "spin", "passion"]).toContain(action.tactic);
  });

  it("wander controller rejects empty allowed actions", async () => {
    const controller = new WanderController(123);

    await expect(
      controller.decide({
        ...input,
        allowedActions: [],
      }),
    ).rejects.toThrow("WanderController requires at least one allowed action");
  });

  it.each([
    [["wait"]],
    [["move"]],
    [["wait", "move"]],
  ] as const)("wander controller returns an allowed action for %j", async (allowedActions) => {
    const controller = new WanderController(123);
    const action = await controller.decide({
      ...input,
      allowedActions: [...allowedActions],
    });

    expect(allowedActions).toContain(action.type);
  });

  it("llm controller fails closed to wait when Anthropic credentials are unavailable", async () => {
    const controller = new LlmController({
      fetch: anthropicFetchForText("Thoughts: testing\nChoice: 1"),
    });
    const action = await controller.decide(input);

    expect(action.type).toBe("wait");
    expect(action.intent).toContain("Anthropic request failed");
    expect(action.intent).toContain("API key");
  });

  it("strict llm controller rejects when Anthropic credentials are unavailable", async () => {
    const controller = new LlmController({
      fetch: anthropicFetchForText("Thoughts: testing\nChoice: 1"),
      strict: true,
    });

    await expect(controller.decide(input)).rejects.toThrow("API key");
  });

  it("llm controller asks Anthropic HTTP for thoughts and a numbered legal action", async () => {
    const calls: AnthropicCall[] = [];
    const thoughts = "Moving north gets me closer to a room with more red cogs, so I should take that path now.";
    const controller = new LlmController({
      apiKey: TEST_ANTHROPIC_API_KEY,
      fetch: anthropicFetchForText(`Thoughts: ${thoughts}\nChoice: 1`, (call) => calls.push(call)),
      model: "anthropic.claude-haiku-4-5-20251001-v1:0",
    });

    const action = await controller.decide({
      ...input,
      allowedActions: ["move", "wait"],
      allowedDirections: ["north"],
    });

    expect(action).toEqual({
      type: "move",
      direction: "north",
      choiceNumber: 1,
      thoughts,
    });
    expect(calls).toHaveLength(1);
    expect(calls[0]?.url).toBe("https://api.anthropic.com/v1/messages");
    expect(calls[0]?.init.method).toBe("POST");
    expect(calls[0]?.init.headers).toMatchObject({
      accept: "application/json",
      "anthropic-version": "2023-06-01",
      "content-type": "application/json",
      "x-api-key": TEST_ANTHROPIC_API_KEY,
    });
    const body = anthropicRequestBody(calls[0]);
    expect(body.model).toBe("claude-haiku-4-5-20251001");
    expect(body.max_tokens).toBeGreaterThanOrEqual(320);
    expect(body.system).toContain("Thoughts:");
    expect(body.system).toContain("Choice:");
    expect(body.messages).toEqual([
      {
        role: "user",
        content: expect.stringContaining("Instructions:"),
      },
    ]);
    expect(body).not.toHaveProperty("anthropic_version");
    expect(body).not.toHaveProperty("modelId");
  });

  it.each([
    ["claude-haiku-4-5-20251001", "claude-haiku-4-5-20251001"],
    ["anthropic.claude-haiku-4-5-20251001-v1:0", "claude-haiku-4-5-20251001"],
    ["claude-opus-4-1@20250805", "claude-opus-4-1-20250805"],
    ["us.anthropic.claude-haiku-4-5-20251001-v1:0", "claude-haiku-4-5-20251001"],
    ["global.anthropic.claude-haiku-4-5-20251001-v1:0", "claude-haiku-4-5-20251001"],
  ])("normalizes model id %s for Anthropic HTTP", async (configuredModel, expectedModel) => {
    const calls: AnthropicCall[] = [];
    const controller = new LlmController({
      apiKey: TEST_ANTHROPIC_API_KEY,
      fetch: anthropicFetchForText("Thoughts: testing model normalization\nChoice: 1", (call) => calls.push(call)),
      model: configuredModel,
    });

    await controller.decide({
      ...input,
      allowedActions: ["move", "wait"],
      allowedDirections: ["north"],
    });

    expect(anthropicRequestBody(calls[0]).model).toBe(expectedModel);
  });

  it("llm controller does not offer wait beside a debate choice", async () => {
    let requestBody: Record<string, unknown> | undefined;
    const thoughts = "The room has opponents nearby, so I want the loop to start a debate here.";
    const controller = new LlmController({
      apiKey: TEST_ANTHROPIC_API_KEY,
      fetch: anthropicFetchForText(`Thoughts: ${thoughts}\nChoice: 1`, (call) => {
        requestBody = anthropicRequestBody(call);
      }),
    });

    const action = await controller.decide({
      ...input,
      allowedActions: ["debate", "wait"],
      observation: {
        ...input.observation,
        visibleEntities: [
          {
            kind: "cog",
            id: "cog_babbage",
            name: "Babbage",
            position: { x: 2, y: 1 },
            color: "blue",
            certainty: 80,
            spriteSheetKey: "cog-babbage",
          },
          {
            kind: "cog",
            id: "cog_curie",
            name: "Curie",
            position: { x: 1, y: 2 },
            color: "blue",
            certainty: 60,
            spriteSheetKey: "cog-curie",
          },
        ],
      },
    });

    expect(action).toEqual({
      type: "debate",
      choiceNumber: 1,
      thoughts,
    });
    const prompt = (requestBody?.messages as Array<{ content: string }>)[0]?.content ?? "";
    expect(prompt).toContain("1. Debate");
    expect(prompt).not.toContain("Wait");
    expect(prompt).not.toContain("Debate Babbage");
    expect(prompt).not.toContain("Debate Curie");
  });

  it("controller prompt reads like a party role prompt with transcript and debate choices", () => {
    const prompt = buildControllerDecisionPrompt({
      ...input,
      allowedActions: ["chooseTactic"],
      tick: 12,
      observation: {
        ...input.observation,
        venue: {
          rooms: [{ id: "theater", label: "Theater", spotIds: ["stage"], neighborIds: [] }],
          spots: [{ id: "stage", roomId: "theater", position: { x: 1, y: 1 } }],
          objects: [],
        },
        visibleEntities: [
          {
            kind: "cog",
            id: "bob",
            name: "Bob",
            position: { x: 1, y: 2 },
            location: { roomId: "theater", spotId: "stage" },
            color: "blue",
            certainty: 25,
            activity: "debating",
            spriteSheetKey: "bob",
          },
        ],
        recentEvents: [
          { id: "enter", tick: 9, type: "move", actorId: "cog_test", message: "Test enters the Theater", position: { x: 1, y: 1 } },
          { id: "debate", tick: 10, type: "debateStart", actorId: "cog_test", targetId: "bob", message: "Test and Bob start debating" },
        ],
        cog: {
          ...input.observation.cog,
          name: "Ada",
          color: "red",
          certainty: 30,
          defensiveTrait: "stubborn",
          activeTrait: "charismatic",
          location: { roomId: "theater", spotId: "stage" },
          debate: { opponentId: "bob", startedTick: 10, nextRoundTick: 12, roundsResolved: 2 },
        },
      },
    });

    expect(prompt).toContain("Instructions:");
    expect(prompt).toContain("Your name is Ada");
    expect(prompt).toContain("party at the Grey Area Foundation");
    expect(prompt).toContain("You are on team Red, and are 30% certain");
    expect(prompt).toContain("A debate is one two-cog session against a single opponent.");
    expect(prompt).toContain("A debate can last up to five rounds.");
    expect(prompt).toContain("Each round, choose Reason, Spin, or Passion to convince your opponent.");
    expect(prompt).toContain("Reason beats Spin");
    expect(prompt).toContain("You are:");
    expect(prompt).toContain("[Stubborn]");
    expect(prompt).toContain("[Charismatic]");
    expect(prompt).toContain("Your achievements are:");
    expect(prompt).toContain("Current State:");
    expect(prompt).toContain("You're in [Theater] debating Bob (Blue, certainty 25)");
    expect(prompt).toContain("Transcript:");
    expect(prompt).toContain("You and Bob start debating");
    expect(prompt).toContain("Pick an action:");
    expect(prompt).toContain("Return a Thoughts paragraph, then return Choice with one valid action number.");
    expect(prompt).not.toContain("Random choice:");
    expect(prompt).toContain("1. Reason");
    expect(prompt).toContain("2. Spin");
    expect(prompt).toContain("3. Passion");
    expect(prompt).toContain("4. Random");
    expect(prompt).not.toContain("Game Rules");
    expect(prompt).not.toContain("Valid Actions");
  });

  it("controller prompt includes the cog behavior prompt as guidance", () => {
    const prompt = buildControllerDecisionPrompt({
      ...input,
      observation: {
        ...input.observation,
        cog: {
          ...input.observation.cog,
          behaviorPrompt: "Prefer decisive debates in crowded rooms and choose spin when momentum stalls.",
        },
      },
    });

    expect(prompt).toContain("Your approach:");
    expect(prompt).toContain("Prefer decisive debates in crowded rooms and choose spin when momentum stalls.");
    expect(prompt.indexOf("Your approach:")).toBeLessThan(prompt.indexOf("Current State:"));
  });

  it("controller prompt names the witnessing state for same-room debates", () => {
    const prompt = buildControllerDecisionPrompt({
      ...input,
      allowedActions: ["wait", "move"],
      observation: {
        ...input.observation,
        venue: {
          rooms: [{ id: "bar", label: "Bar", spotIds: ["ada", "mira", "turing"], neighborIds: [] }],
          spots: [
            { id: "ada", roomId: "bar", label: "Ada", position: { x: 1, y: 1 } },
            { id: "mira", roomId: "bar", label: "Mira", position: { x: 2, y: 1 } },
            { id: "turing", roomId: "bar", label: "Turing", position: { x: 3, y: 1 } },
          ],
          objects: [],
        },
        cog: {
          ...input.observation.cog,
          location: { roomId: "bar", spotId: "ada" },
        },
        visibleEntities: [
          {
            kind: "cog",
            id: "mira",
            name: "Mira",
            position: { x: 2, y: 1 },
            location: { roomId: "bar", spotId: "mira" },
            color: "red",
            certainty: 40,
            activity: "debating",
            debate: { opponentId: "turing", startedTick: 3, nextRoundTick: 4, roundsResolved: 1 },
            spriteSheetKey: "mira",
          },
          {
            kind: "cog",
            id: "turing",
            name: "Turing",
            position: { x: 3, y: 1 },
            location: { roomId: "bar", spotId: "turing" },
            color: "blue",
            certainty: 30,
            activity: "debating",
            debate: { opponentId: "mira", startedTick: 3, nextRoundTick: 4, roundsResolved: 1 },
            spriteSheetKey: "turing",
          },
        ],
      },
    });

    expect(prompt).toContain("You're in [Bar] witnessing Mira and Turing debate.");
  });

  it("controller prompt uses concise rule descriptions with actual configured changes", () => {
    const gameConfig = cloneGameConfig(DEFAULT_GAME_CONFIG);
    gameConfig.traitConfig.iconoclast.dominantDoubtMultiplier = 0.6;
    gameConfig.traitConfig.rationalist.winDoubtMultiplier = 1.4;
    gameConfig.traitConfig.rationalist.receivedDoubtMultiplier = 1.2;
    const prompt = buildControllerDecisionPrompt({
      ...input,
      gameConfig,
      observation: {
        ...input.observation,
        cog: {
          ...input.observation.cog,
          defensiveTrait: "iconoclast",
          activeTrait: "rationalist",
          personalGoal: "underdog",
        },
      },
    });

    expect(prompt).toContain("[Iconoclast] - Largest-team pressure costs 40% less certainty.");
    expect(prompt).toContain(
      "[Rationalist] - Reason wins cost opponents 40% more certainty; reason losses cost you 20% more certainty.",
    );
    expect(prompt).toContain("Your achievements are:");
    expect(prompt).toContain("No active achievements.");
    expect(prompt).not.toContain("Underdog:");
    expect(prompt).not.toContain("configured");
  });

  it("llm controller does not expose speak as an action or schema field", async () => {
    let requestBody: Record<string, unknown> | undefined;
    const controller = new LlmController({
      apiKey: TEST_ANTHROPIC_API_KEY,
      fetch: anthropicFetchForText("1", (call) => {
        requestBody = anthropicRequestBody(call);
      }),
    });

    const action = await controller.decide({
      ...input,
      allowedActions: ["wait", "move"],
    });

    expect(action.type).toBe("wait");
    expect(requestBody?.messages).toEqual([
      {
        role: "user",
        content: expect.not.stringContaining("speak"),
      },
    ]);
    expect((requestBody?.messages as Array<{ content: string }>)[0]?.content).not.toContain("Speech");
    expect(requestBody).toBeDefined();
    expect(requestBody).not.toHaveProperty("text");
  });

  it("llm controller picks a random valid action when the provider returns an invalid number", async () => {
    const random = vi.spyOn(Math, "random").mockReturnValue(0.75);
    const controller = new LlmController({
      apiKey: TEST_ANTHROPIC_API_KEY,
      fetch: anthropicFetchForText("99"),
    });

    try {
      const action = await controller.decide({
        ...input,
        allowedActions: ["chooseTactic"],
        observation: {
          ...input.observation,
          cog: {
            ...input.observation.cog,
            activeTrait: "forceful",
            debate: { opponentId: "cog_neighbor", startedTick: 0, nextRoundTick: 0, roundsResolved: 0 },
          },
        },
      });

      expect(action.type).toBe("chooseTactic");
      if (action.type !== "chooseTactic") {
        throw new Error(`Expected chooseTactic action, received ${action.type}`);
      }
      expect(action.tactic).toBe("passion");
      expect(action.intent).toContain("invalid choice 99");
    } finally {
      random.mockRestore();
    }
  });

  it("llm controller accepts provider choice labels when the number is missing", async () => {
    const controller = new LlmController({
      apiKey: TEST_ANTHROPIC_API_KEY,
      fetch: anthropicFetchForText("Thoughts: Moving north follows my behavior prompt.\nChoice: Move north"),
    });

    const action = await controller.decide({
      ...input,
      allowedActions: ["wait", "move"],
      allowedDirections: ["north"],
    });

    expect(action).toEqual({
      type: "move",
      direction: "north",
      choiceNumber: 2,
      thoughts: "Moving north follows my behavior prompt.",
    });
  });

  it("llm controller lets the provider pick random as choice four", async () => {
    const random = vi.spyOn(Math, "random").mockReturnValue(0.4);
    let requestBody: Record<string, unknown> | undefined;
    const controller = new LlmController({
      apiKey: TEST_ANTHROPIC_API_KEY,
      fetch: anthropicFetchForText("Thoughts: I need a random tactic.\nChoice: 4", (call) => {
        requestBody = anthropicRequestBody(call);
      }),
    });

    try {
      const action = await controller.decide({
        ...input,
        allowedActions: ["chooseTactic"],
        observation: {
          ...input.observation,
          cog: {
            ...input.observation.cog,
            debate: { opponentId: "cog_neighbor", startedTick: 0, nextRoundTick: 0, roundsResolved: 0 },
          },
        },
      });

      expect(action.type).toBe("chooseTactic");
      if (action.type !== "chooseTactic") {
        throw new Error(`Expected chooseTactic action, received ${action.type}`);
      }
      expect(action.tactic).toBe("spin");
      expect(action.choiceNumber).toBe(4);
      expect(requestBody?.system).toContain("choose Random");
      expect(requestBody?.system).not.toContain("you may return that number as Choice");
    } finally {
      random.mockRestore();
    }
  });

  it("llm controller fails closed when the Anthropic request fails", async () => {
    const controller = new LlmController({
      apiKey: TEST_ANTHROPIC_API_KEY,
      fetch: async () => {
        throw new Error("rate limited");
      },
    });

    const action = await controller.decide({
      ...input,
      allowedActions: ["move", "wait"],
    });

    expect(action.type).toBe("wait");
    expect(action.intent).toContain("Anthropic request failed");
    expect(action.intent).toContain("rate limited");
  });

  it("strict llm controller rejects when the Anthropic request fails", async () => {
    const controller = new LlmController({
      apiKey: TEST_ANTHROPIC_API_KEY,
      fetch: async () => {
        throw new Error("rate limited");
      },
      strict: true,
    });

    await expect(controller.decide(input)).rejects.toThrow("rate limited");
  });

  it("llm controller fails closed with HTTP status details when Anthropic rejects a request", async () => {
    const controller = new LlmController({
      apiKey: TEST_ANTHROPIC_API_KEY,
      fetch: async () => new Response("rate limited", { status: 429 }),
    });

    const action = await controller.decide({
      ...input,
      allowedActions: ["move", "wait"],
    });

    expect(action.type).toBe("wait");
    expect(action.intent).toContain("Anthropic request failed");
    expect(action.intent).toContain("HTTP 429");
    expect(action.intent).toContain("rate limited");
  });

  it("strict llm controller rejects with HTTP status details when Anthropic rejects a request", async () => {
    const controller = new LlmController({
      apiKey: TEST_ANTHROPIC_API_KEY,
      fetch: async () => new Response("invalid model", { status: 404 }),
      strict: true,
    });

    await expect(controller.decide(input)).rejects.toThrow("HTTP 404");
    await expect(controller.decide(input)).rejects.toThrow("invalid model");
  });

  it("strict llm controller rejects provider decisions without thoughts", async () => {
    const controller = new LlmController({
      apiKey: TEST_ANTHROPIC_API_KEY,
      fetch: anthropicFetchForText("Choice: 1"),
      strict: true,
    });

    await expect(
      controller.decide({
        ...input,
        allowedActions: ["move", "wait"],
        allowedDirections: ["north"],
      }),
    ).rejects.toThrow("missing Thoughts");
  });

  it("uses a 5 second default timeout for provider requests", async () => {
    vi.useFakeTimers();
    const controller = new LlmController({
      apiKey: TEST_ANTHROPIC_API_KEY,
      fetch: async (_url, init) =>
        new Promise<never>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            const error = new Error("aborted");
            error.name = "AbortError";
            reject(error);
          });
        }),
    });

    try {
      const actionPromise = controller.decide(input);
      await vi.advanceTimersByTimeAsync(5_000);
      const action = await actionPromise;

      expect(action.type).toBe("wait");
      expect(action.intent).toContain("timed out after 5000ms");
    } finally {
      vi.useRealTimers();
    }
  });

  it("fails closed when an Anthropic request ignores the abort signal", async () => {
    vi.useFakeTimers();
    const controller = new LlmController({
      apiKey: TEST_ANTHROPIC_API_KEY,
      fetch: async () => new Promise<never>(() => undefined),
    });

    try {
      const actionPromise = controller.decide(input);
      await vi.advanceTimersByTimeAsync(5_000);
      await Promise.resolve();
      await Promise.resolve();
      const resultPromise = Promise.race([
        actionPromise.then((action) => action.intent ?? action.type),
        new Promise<string>((resolve) => setTimeout(() => resolve("pending"), 1)),
      ]);
      await vi.advanceTimersByTimeAsync(1);
      const result = await resultPromise;

      expect(result).toContain("timed out after 5000ms");
      await expect(actionPromise).resolves.toMatchObject({ type: "wait" });
    } finally {
      vi.useRealTimers();
    }
  });

  it("controller registry creates every controller", () => {
    const registry = createControllerRegistry();

    expect(registry.stub).toBeInstanceOf(StubController);
    expect(registry.wander).toBeInstanceOf(WanderController);
    expect(registry.llm).toBeInstanceOf(LlmController);
  });

  it("controller registry can route llm controller ids through scripted decisions", () => {
    const registry = createControllerRegistry({ scriptLlm: true });

    expect(registry.llm).toBeInstanceOf(WanderController);
  });

  it("controller registry requires LLM config without making malformed provider choices fatal", async () => {
    const previousEnableLiveTests = process.env.COGSHAMBO_ENABLE_LIVE_LLM_TESTS;
    const previousApiKey = process.env.ANTHROPIC_API_KEY;
    const previousModel = process.env.COGSHAMBO_LLM_MODEL;
    process.env.COGSHAMBO_ENABLE_LIVE_LLM_TESTS = "1";
    process.env.ANTHROPIC_API_KEY = TEST_ANTHROPIC_API_KEY;
    process.env.COGSHAMBO_LLM_MODEL = "claude-haiku-4-5-20251001";
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(anthropicFetchForText("Thoughts: I know what I want, but forgot the choice line.") as typeof fetch);

    try {
      const registry = createControllerRegistry({ requireLlm: true });
      const action = await registry.llm.decide({ ...input, allowedActions: ["wait"] });

      expect(action.type).toBe("wait");
      expect(action.intent).toContain("missing choice number");
    } finally {
      fetchSpy.mockRestore();
      if (previousEnableLiveTests === undefined) {
        delete process.env.COGSHAMBO_ENABLE_LIVE_LLM_TESTS;
      } else {
        process.env.COGSHAMBO_ENABLE_LIVE_LLM_TESTS = previousEnableLiveTests;
      }
      if (previousApiKey === undefined) {
        delete process.env.ANTHROPIC_API_KEY;
      } else {
        process.env.ANTHROPIC_API_KEY = previousApiKey;
      }
      if (previousModel === undefined) {
        delete process.env.COGSHAMBO_LLM_MODEL;
      } else {
        process.env.COGSHAMBO_LLM_MODEL = previousModel;
      }
    }
  });

  it("loads Anthropic controller configuration from .env when env vars are not exported", () => {
    const directory = mkdtempSync(path.join(tmpdir(), "cogshambo-env-"));
    const envPath = path.join(directory, ".env");
    writeFileSync(
      envPath,
      [
        "ANTHROPIC_API_KEY=test-env-key",
        "COGSHAMBO_LLM_MODEL=claude-haiku-4-5-20251001",
        "COGSHAMBO_LLM_TIMEOUT_MS=1234",
      ].join("\n"),
    );

    try {
      expect(llmControllerConfigFromEnv({}, envPath)).toEqual({
        apiKey: "test-env-key",
        model: "claude-haiku-4-5-20251001",
        timeoutMs: 1234,
      });
    } finally {
      rmSync(directory, { force: true, recursive: true });
    }
  });

  it("prefers Anthropic-specific env names over generic LLM names", () => {
    expect(
      llmControllerConfigFromEnv(
        {
          COGSHAMBO_ANTHROPIC_API_KEY: "preferred-key",
          COGSHAMBO_ANTHROPIC_MODEL: "claude-sonnet-4-5-20250929",
          COGSHAMBO_ANTHROPIC_TIMEOUT_MS: "1234",
          ANTHROPIC_API_KEY: "fallback-key",
          COGSHAMBO_LLM_MODEL: "claude-haiku-4-5-20251001",
          COGSHAMBO_LLM_TIMEOUT_MS: "5678",
        },
        path.join(tmpdir(), "missing-cogshambo-env"),
      ),
    ).toEqual({
      apiKey: "preferred-key",
      model: "claude-sonnet-4-5-20250929",
      timeoutMs: 1234,
    });
  });

  it("does not use live Anthropic configuration automatically in test mode", () => {
    expect(
      llmControllerConfigFromEnv({
        ANTHROPIC_API_KEY: TEST_ANTHROPIC_API_KEY,
        COGSHAMBO_LLM_MODEL: "claude-haiku-4-5-20251001",
        NODE_ENV: "test",
      }),
    ).toEqual({
      disabledReason: "Cogshambo requires Anthropic credentials for LLM decisions",
      apiKey: undefined,
      model: undefined,
      timeoutMs: undefined,
    });
  });
});
