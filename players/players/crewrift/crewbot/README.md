# Crewbot

Crewbot is the recommended starter policy for Crewrift. It keeps the
compact Nim movement, tasking, body reporting, imposter behavior, vote cursor
navigation, and deterministic fallback voting from notsus, then adds a bounded
LLM hook during meetings. The LLM can only add meeting chat or choose a legal
vote target from the current voting screen.

The Docker build checks out the canonical `coworld-crewrift` repo at the pinned
ref in `Dockerfile`, overlays this player under `players/crewbot`, compiles
the Nim binary, and copies a small Python helper into the runtime image.

## LLM meetings

`CREWBOT_LLM_MEETINGS=1` enables the helper. `USE_BEDROCK=1` uses
Anthropic Bedrock via the tournament-provided AWS environment; pass the upload or
runner option that injects Bedrock credentials when submitting this image. Without
Bedrock, set `ANTHROPIC_API_KEY` for direct Anthropic. If the helper is disabled,
times out, returns too late, or returns no legal target, the original notsus vote
decision is used. The helper is intentionally time-boxed and advisory: low
confidence `submit_vote` responses are treated as tentative votes, and crewmates
cast non-skip votes only on repeated same-target sus/body evidence or revenge votes.

When Coworld provides a `slot=` in `COWORLD_PLAYER_WS_URL` or via `--slot`,
Crewbot pins its self color from that slot. That keeps meeting context and
self-vote filtering stable when vote-screen marker reads are noisy.

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
players/crewrift/crewbot/build.sh --tag crewbot:test
```

Run a local Crewrift slot gate with zero vote timeouts allowed:

```sh
uv run --project ~/Code/co-gas python -m co_gas.gates.crewrift_slot_matrix_runner \
  --candidate-image crewbot:test \
  --manifest ~/Code/co-gas/cogas-agents/coworlds/crewrift/vendor/coworld-crewrift/coworld_manifest.json \
  --seed 679961 \
  --run /bin/crewbot \
  --use-bedrock \
  --aws-region "${AWS_REGION:-us-west-2}" \
  --slots 4,7 \
  --pair 4,7 \
  --max-candidate-vote-timeouts 0 \
  --allow-fail
```
