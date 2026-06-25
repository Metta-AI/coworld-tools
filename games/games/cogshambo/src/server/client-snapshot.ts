import type { Cog, WorldSnapshot } from "../shared/types.js";

export const CLIENT_COG_CONVERSATION_LOG_LIMIT = 20;
export const CLIENT_DEBATE_LOG_LIMIT = 240;

export function compactWorldSnapshot(snapshot: WorldSnapshot): WorldSnapshot {
  return {
    ...snapshot,
    cogs: snapshot.cogs.map(compactCog),
    debateLog: snapshot.debateLog?.slice(-CLIENT_DEBATE_LOG_LIMIT),
  };
}

function compactCog(cog: Cog): Cog {
  return {
    ...cog,
    conversationLog: cog.conversationLog.slice(-CLIENT_COG_CONVERSATION_LOG_LIMIT),
  };
}
