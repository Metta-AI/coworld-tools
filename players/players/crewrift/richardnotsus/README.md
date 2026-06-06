# RichardNotsus

RichardNotsus is the notsus Crewrift baseline with one bounded LLM hook during
meetings. The Nim player keeps notsus movement, tasking, body reporting, imposter
behavior, vote cursor navigation, and deterministic fallback voting. The LLM can
only add meeting chat or choose a legal vote target from the current voting
screen.

The Docker build checks out the canonical `coworld-crewrift` repo at the pinned
ref in `Dockerfile`, overlays this player under `players/richardnotsus`, compiles
the Nim binary, and copies a small Python helper into the runtime image.

## LLM meetings

`RICHARDNOTSUS_LLM_MEETINGS=1` enables the helper. `USE_BEDROCK=1` uses
Anthropic Bedrock via the tournament-provided AWS environment. Without Bedrock,
set `ANTHROPIC_API_KEY` for direct Anthropic. If the helper is disabled, times
out, or returns no legal target, the original notsus vote decision is used.

The helper receives a compact JSON meeting frame with visible players, parsed
votes, chat, deterministic fallback vote, and canonical memory observations such
as "I saw red near the reported body." It returns one JSON object:

```json
{
  "schema_version": 1,
  "action": "send_chat",
  "chat_text": "body near medbay",
  "vote_target": "",
  "reason": "share body location",
  "confidence": 0.5
}
```

Build locally:

```sh
players/crewrift/richardnotsus/build.sh --tag richardnotsus:test
```
