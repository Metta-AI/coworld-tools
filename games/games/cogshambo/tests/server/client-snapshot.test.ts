import { describe, expect, it } from "vitest";
import {
  CLIENT_COG_CONVERSATION_LOG_LIMIT,
  CLIENT_DEBATE_LOG_LIMIT,
  compactWorldSnapshot,
} from "../../src/server/client-snapshot.js";
import { createSeedWorld } from "../../src/server/simulation/seed-world.js";
import { worldSnapshotSchema } from "../../src/shared/protocol.js";
import type { CogConversationMessage, DebateLogEntry, WorldSnapshot } from "../../src/shared/types.js";

describe("client snapshot compaction", () => {
  it("keeps the transport payload bounded without mutating full world history", () => {
    const snapshot = createSeedWorld().snapshot();
    const verbose = {
      ...snapshot,
      cogs: snapshot.cogs.map((cog) => ({
        ...cog,
        conversationLog: conversationLog(CLIENT_COG_CONVERSATION_LOG_LIMIT + 3),
      })),
      debateLog: debateLog(CLIENT_DEBATE_LOG_LIMIT + 3),
    } satisfies WorldSnapshot;

    const compact = compactWorldSnapshot(verbose);

    expect(worldSnapshotSchema.safeParse(compact).success).toBe(true);
    expect(compact.cogs[0]?.conversationLog).toHaveLength(CLIENT_COG_CONVERSATION_LOG_LIMIT);
    expect(compact.cogs[0]?.conversationLog[0]?.id).toBe("msg_3");
    expect(compact.debateLog).toHaveLength(CLIENT_DEBATE_LOG_LIMIT);
    expect(compact.debateLog?.[0]?.id).toBe("debate_3");
    expect(verbose.cogs[0]?.conversationLog).toHaveLength(CLIENT_COG_CONVERSATION_LOG_LIMIT + 3);
    expect(verbose.debateLog).toHaveLength(CLIENT_DEBATE_LOG_LIMIT + 3);
  });
});

function conversationLog(count: number): CogConversationMessage[] {
  return Array.from({ length: count }, (_value, index) => ({
    id: `msg_${index}`,
    tick: index,
    role: index % 2 === 0 ? "assistant" : "user",
    content: `message ${index}`,
  }));
}

function debateLog(count: number): DebateLogEntry[] {
  return Array.from({ length: count }, (_value, index) => ({
    id: `debate_${index}`,
    tick: index,
    round: 1,
    outcome: "draw",
    actions: [
      { cogId: "red", cogName: "Red", color: "red", tactic: "reason" },
      { cogId: "blue", cogName: "Blue", color: "blue", tactic: "spin" },
    ],
    changes: [],
    conversions: [],
  }));
}
